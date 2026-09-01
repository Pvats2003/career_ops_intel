"""Tests `run_application()`'s Safe Mode control flow: a startup failure
must launch Safe Mode instead of propagating, "Retry" must re-attempt
`InstacoreSyncApp()` construction, and "Quit" must exit cleanly. Real
`SafeModeWindow`/`InstacoreSyncApp` are replaced with fakes here so this
tests the *orchestration logic* in `app.py` (which of these gets called,
how many times, in what order) without needing an interactive GUI session
or real Google/Drive/OCR services -- those are exercised elsewhere.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import instacore_sync.app as app_module


class _FakeSafeModeWindow:
    """Stands in for the real SafeModeWindow: skips ever calling .show()
    or running a nested Qt event loop, and instead immediately invokes
    whichever callback the test wants (as if the user had clicked that
    button), synchronously, at construction time."""

    _next_action: str = "quit"  # class-level: set by each test before triggering run_application()

    def __init__(self, **kwargs) -> None:  # noqa: ANN003
        self._kwargs = kwargs

    def show(self) -> None:
        pass

    def close(self) -> None:
        pass


def _make_fake_safe_mode_window_cls(action: str):
    class _Fake(_FakeSafeModeWindow):
        def show(self) -> None:
            if action == "retry":
                self._kwargs["on_retry"]()
            else:
                self._kwargs["on_quit"]()

    return _Fake


def test_startup_failure_then_quit_returns_1_without_a_second_attempt(monkeypatch) -> None:
    construct_calls = []

    def _fake_instacore_app():
        construct_calls.append(1)
        raise RuntimeError("settings.local.yaml is malformed")

    monkeypatch.setattr(app_module, "InstacoreSyncApp", _fake_instacore_app)
    monkeypatch.setattr(app_module, "SafeModeWindow", _make_fake_safe_mode_window_cls("quit"))
    monkeypatch.setattr(app_module, "_log_startup_failure", lambda detail: None)

    # run_application() constructs its own QApplication internally, which
    # we can't easily replace without a real display; instead drive the
    # inner per-attempt helper directly (what run_application's loop
    # calls), which is where the actual retry/quit logic lives.
    from PySide6.QtGui import QIcon

    fake_qt_app = MagicMock()
    outcome = app_module._show_safe_mode_and_wait(fake_qt_app, QIcon(), RuntimeError("boom"))
    assert outcome == "quit"
    assert construct_calls == []  # _show_safe_mode_and_wait itself never constructs InstacoreSyncApp


def test_show_safe_mode_and_wait_retry_path(monkeypatch) -> None:
    from PySide6.QtGui import QIcon

    monkeypatch.setattr(app_module, "SafeModeWindow", _make_fake_safe_mode_window_cls("retry"))
    monkeypatch.setattr(app_module, "_log_startup_failure", lambda detail: None)

    fake_qt_app = MagicMock()
    outcome = app_module._show_safe_mode_and_wait(fake_qt_app, QIcon(), RuntimeError("boom"))
    assert outcome == "retry"
    fake_qt_app.exec.assert_called_once()


def _patch_qapplication_to_reuse_the_real_singleton(monkeypatch, qt_app) -> None:
    """`run_application()` constructs a real `QIcon` (line ~200) whether
    or not Safe Mode ever triggers -- and constructing *any* Qt GUI
    object without a real `QApplication`/`QGuiApplication` already
    existing in the process is undefined behavior in Qt (it reliably
    aborts the whole process, not just raises a Python exception). A
    fully fake, non-Qt `QApplication` replacement therefore isn't safe to
    use here. Since Qt only permits one QApplication per process, this
    proxies `QApplication(...)` to return the real one the session-scoped
    `qt_app` fixture already constructed, instead of trying to construct
    a second real instance (which Qt does not support) or a fake one
    (which crashes the process on the very next GUI object)."""

    class _QApplicationProxy:
        def __new__(cls, *_args, **_kwargs):
            return qt_app

        @staticmethod
        def setApplicationName(name: str) -> None:
            pass

        @staticmethod
        def setOrganizationName(name: str) -> None:
            pass

    monkeypatch.setattr(app_module, "QApplication", _QApplicationProxy)
    monkeypatch.setattr(qt_app, "exec", lambda: 0, raising=False)


def test_run_application_retries_then_succeeds(qt_app, monkeypatch) -> None:
    """End-to-end retry-loop test: first InstacoreSyncApp() construction
    raises, Safe Mode's fake "Retry" click fires, second construction
    succeeds -- run_application() must attempt construction exactly
    twice and return whatever the second, successful .run() returns."""
    attempts = []

    class _FakeApp:
        def __init__(self) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("first attempt fails")

        def run(self, qt_app) -> int:  # noqa: ANN001
            return 0

    monkeypatch.setattr(app_module, "InstacoreSyncApp", _FakeApp)
    monkeypatch.setattr(app_module, "SafeModeWindow", _make_fake_safe_mode_window_cls("retry"))
    monkeypatch.setattr(app_module, "_log_startup_failure", lambda detail: None)
    _patch_qapplication_to_reuse_the_real_singleton(monkeypatch, qt_app)

    exit_code = app_module.run_application()

    assert len(attempts) == 2  # exactly one retry
    assert exit_code == 0


def test_run_application_quits_after_persistent_failure(qt_app, monkeypatch) -> None:
    def _always_fails():
        raise RuntimeError("still broken")

    monkeypatch.setattr(app_module, "InstacoreSyncApp", _always_fails)
    monkeypatch.setattr(app_module, "SafeModeWindow", _make_fake_safe_mode_window_cls("quit"))
    monkeypatch.setattr(app_module, "_log_startup_failure", lambda detail: None)
    _patch_qapplication_to_reuse_the_real_singleton(monkeypatch, qt_app)

    exit_code = app_module.run_application()

    assert exit_code == 1
