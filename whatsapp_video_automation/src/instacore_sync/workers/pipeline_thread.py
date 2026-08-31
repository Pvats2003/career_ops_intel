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
