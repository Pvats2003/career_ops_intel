"""Runs the asyncio-based `PipelineOrchestrator` on a dedicated background
thread so it never blocks the Qt GUI event loop.

The QThread's `run()` creates and owns its own asyncio event loop for its
entire lifetime; `stop()` (called from the GUI thread) schedules a
thread-safe shutdown coroutine and blocks briefly for a clean exit.
A `QTimer`-driven poll (started by MainWindow) periodically asks the
orchestrator for fresh `DailyStats`, dispatched back via the same
thread-safe scheduling mechanism.
"""

from __future__ import annotations

import asyncio
import threading

from PySide6.QtCore import QThread

from instacore_sync.core.logging_setup import get_logger
from instacore_sync.services.pipeline.pipeline_orchestrator import PipelineOrchestrator
from instacore_sync.workers.signals import PipelineSignalBus

logger = get_logger(__name__)


class PipelineThread(QThread):
    """Owns the asyncio event loop that drives the whole ingestion pipeline."""

    def __init__(self, orchestrator: PipelineOrchestrator, signal_bus: PipelineSignalBus) -> None:
        super().__init__()
        self._orchestrator = orchestrator
        self._signals = signal_bus
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop_ready.set()
        try:
            self._loop.run_until_complete(self._main())
        except Exception:  # noqa: BLE001
            logger.exception("pipeline_thread.crashed")
            self._signals.on_log_message("ERROR", "The pipeline stopped unexpectedly. Check logs.")
        finally:
            self._loop.close()

    async def _main(self) -> None:
        await self._orchestrator.start()
        # Keep the loop alive until stop() cancels this task via _stop_event.
        self._stop_event = asyncio.Event()
        await self._stop_event.wait()
        await self._orchestrator.stop()

    def wait_until_ready(self, timeout: float = 5.0) -> bool:
        """Blocks until the pipeline's event loop object exists (i.e.
        `start()` was called and the thread has begun running) — used by
        the first-run wizard, which needs `sign_in_interactively()` and
        the other thread-safe proxies below to actually be able to
        schedule work before it shows itself. Returns whether the loop
        became ready within `timeout`."""
        return self._loop_ready.wait(timeout=timeout)

    def stop(self, timeout_ms: int = 10_000) -> None:
        self._loop_ready.wait(timeout=5.0)
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        def _signal_stop() -> None:
            stop_event = getattr(self, "_stop_event", None)
            if stop_event is not None:
                stop_event.set()

        loop.call_soon_threadsafe(_signal_stop)
        self.wait(timeout_ms)

    def request_stats_refresh(self) -> None:
        """Ask the orchestrator to compute+publish fresh stats (thread-safe)."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        def _compute() -> None:
            stats = self._orchestrator.compute_daily_stats()
            self._signals.on_stats_changed(stats)

        loop.call_soon_threadsafe(_compute)

    def pause_uploads(self) -> None:
        """Thread-safe: stop starting new uploads, let in-flight ones finish."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._orchestrator.pause_uploads)

    def resume_uploads(self) -> None:
        """Thread-safe: resume pulling new uploads from the queue."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._orchestrator.resume_uploads)

    def retry_job(self, job_id: str) -> None:
        """Thread-safe: re-queue a FAILED/NEEDS_REVIEW job (Queue view's Retry button)."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._orchestrator.retry_job, job_id)

    def resolve_needs_review(self, job_id: str, manual_device_id: str) -> None:
        """Thread-safe: apply a manually-chosen Device ID and queue for upload."""
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._orchestrator.resolve_needs_review, job_id, manual_device_id)

    def sign_in_interactively(self) -> None:
        """Thread-safe: Settings' "Sign in with Google" button — the only
        path allowed to open an interactive browser consent screen."""
        loop = self._loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(self._orchestrator.sign_in_interactively(), loop)

    def request_health_check(self) -> None:
        """Thread-safe: run the Health Check page's checks and publish
        the results via `health_check_completed` once done. Runs on the
        pipeline thread's own loop (the checks do blocking network/disk
        I/O); emitting the Qt signal from there is safe the same way
        every other `PipelineSignalBus` signal is (see its docstring)."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def _run() -> None:
            results = await self._orchestrator.run_health_check()
            self._signals.health_check_completed.emit(results)

        asyncio.run_coroutine_threadsafe(_run(), loop)

    # -- first-run wizard: per-step validation -----------------------------------

    def verify_drive_folder(self, folder_id: str) -> None:
        """Thread-safe: wizard's "Select Drive Root Folder" step."""
        self._run_wizard_check("drive_folder", self._orchestrator.verify_drive_folder_for_wizard(folder_id))

    def verify_spreadsheet(self, spreadsheet_id: str) -> None:
        """Thread-safe: wizard's "Select Google Sheet" step."""
        self._run_wizard_check(
            "spreadsheet", self._orchestrator.verify_spreadsheet_for_wizard(spreadsheet_id)
        )

    def test_ocr(self) -> None:
        """Thread-safe: wizard's "Test OCR" step."""
        self._run_wizard_check("ocr", self._orchestrator.test_ocr_for_wizard())

    def test_upload(self, folder_id: str) -> None:
        """Thread-safe: wizard's "Test Upload" step."""
        self._run_wizard_check("upload", self._orchestrator.test_upload_for_wizard(folder_id))

    def _run_wizard_check(self, check_name: str, coro) -> None:  # noqa: ANN001
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def _run() -> None:
            result = await coro
            self._signals.wizard_check_result.emit(check_name, result)

        asyncio.run_coroutine_threadsafe(_run(), loop)
