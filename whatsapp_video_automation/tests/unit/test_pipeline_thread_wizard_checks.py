"""Regression test: a wizard-check (or health-check, or sign-in) coroutine
that raises an unexpected exception must never leave the wizard UI stuck
forever on "Checking...". `PipelineThread` dispatches these via
`asyncio.run_coroutine_threadsafe(...)` and deliberately never awaits the
returned Future — before this fix, an exception there vanished silently
(nothing logs it, and `wizard_check_result` never fires), so a page that
only re-enables its button/hides its spinner on that signal would wait
forever with no way to know something failed short of restarting the app.
"""

from __future__ import annotations

from PySide6.QtTest import QTest

from instacore_sync.domain.enums import HealthStatus
from instacore_sync.workers.pipeline_thread import PipelineThread
from instacore_sync.workers.signals import PipelineSignalBus


class _RaisingOrchestrator:
    """Just enough of PipelineOrchestrator's interface for PipelineThread's
    `run()`/`stop()` to work, plus one wizard-check coroutine that raises
    an exception type nothing in the real call chain happens to catch —
    exactly the gap this test guards against."""

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def verify_drive_folder_for_wizard(self, folder_id: str):  # noqa: ANN001, ANN201
        raise RuntimeError("simulated unexpected failure")


def _wait_until(predicate, timeout_ms: int = 3000, step_ms: int = 20) -> bool:
    waited = 0
    while not predicate() and waited < timeout_ms:
        QTest.qWait(step_ms)
        waited += step_ms
    return predicate()


def test_wizard_check_exception_still_emits_a_failed_result(qt_app) -> None:  # noqa: ANN001
    signal_bus = PipelineSignalBus()
    thread = PipelineThread(_RaisingOrchestrator(), signal_bus)

    received: list[tuple[str, object]] = []
    signal_bus.wizard_check_result.connect(lambda name, result: received.append((name, result)))

    thread.start()
    assert thread.wait_until_ready(timeout=5.0), "pipeline thread's event loop never became ready"

    thread.verify_drive_folder("some-folder-id")

    assert _wait_until(lambda: len(received) > 0), (
        "wizard_check_result was never emitted after the check coroutine raised — "
        "the wizard UI would be stuck on 'Checking...' forever"
    )

    name, result = received[0]
    assert name == "drive_folder"
    assert result.status == HealthStatus.FAILED
    assert "simulated unexpected failure" in result.message

    thread.stop()
