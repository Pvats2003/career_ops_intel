"""Unit tests for SafeModeWindow — constructed and driven directly (no
real windowing system needed beyond the offscreen Qt platform plugin),
verifying its button handlers call the right callbacks and never let a
second failure (e.g. a broken reset) propagate out and defeat the whole
point of Safe Mode."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from PySide6.QtWidgets import QMessageBox

from instacore_sync.ui.safe_mode_window import SafeModeWindow


def _window(tmp_path: Path, **overrides) -> SafeModeWindow:
    kwargs = {
        "error_summary": "Something broke",
        "error_detail": "Traceback (most recent call last):\n  ...\nValueError: boom",
        "settings_dir": tmp_path / "config",
        "log_path": tmp_path / "logs" / "instacore_sync.log",
        "on_retry": MagicMock(),
        "on_reset_settings": MagicMock(return_value=True),
        "on_quit": MagicMock(),
    }
    kwargs.update(overrides)
    return SafeModeWindow(**kwargs)


def test_window_shows_the_error_summary_and_detail(qt_app, tmp_path: Path) -> None:
    from PySide6.QtWidgets import QLabel, QPlainTextEdit

    window = _window(tmp_path, error_summary="Bad YAML", error_detail="full traceback here")

    detail_box = window.findChild(QPlainTextEdit)
    assert detail_box is not None
    assert "full traceback here" in detail_box.toPlainText()

    labels_text = " ".join(label.text() for label in window.findChildren(QLabel))
    assert "Bad YAML" in labels_text


def test_retry_button_calls_on_retry(qt_app, tmp_path: Path) -> None:
    on_retry = MagicMock()
    window = _window(tmp_path, on_retry=on_retry)
    window._on_retry_clicked()
    on_retry.assert_called_once()


def test_quit_button_calls_on_quit(qt_app, tmp_path: Path) -> None:
    on_quit = MagicMock()
    window = _window(tmp_path, on_quit=on_quit)
    window._on_quit_clicked()
    on_quit.assert_called_once()


def test_closing_the_window_counts_as_quit(qt_app, tmp_path: Path) -> None:
    """The window's X button has no "minimize to tray" special case like
    MainWindow -- there's no pipeline running to preserve, so closing it
    must always be equivalent to clicking Quit."""
    on_quit = MagicMock()
    window = _window(tmp_path, on_quit=on_quit)
    window.close()
    on_quit.assert_called_once()


def test_reset_settings_declined_does_not_call_callback(qt_app, tmp_path: Path, monkeypatch) -> None:
    on_reset = MagicMock(return_value=True)
    window = _window(tmp_path, on_reset_settings=on_reset)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.No))

    window._on_reset_clicked()

    on_reset.assert_not_called()


def test_reset_settings_confirmed_calls_callback(qt_app, tmp_path: Path, monkeypatch) -> None:
    on_reset = MagicMock(return_value=True)
    window = _window(tmp_path, on_reset_settings=on_reset)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **kw: None))

    window._on_reset_clicked()

    on_reset.assert_called_once()


def test_reset_settings_callback_raising_does_not_crash_safe_mode(qt_app, tmp_path: Path, monkeypatch) -> None:
    """The whole point of Safe Mode is to never crash -- including when
    the *recovery action itself* fails (a corrupted disk, a permissions
    problem writing the reset file)."""

    def _boom() -> bool:
        raise OSError("disk is on fire")

    window = _window(tmp_path, on_reset_settings=_boom)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **kw: QMessageBox.StandardButton.Yes)
    )
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **kw: None))

    window._on_reset_clicked()  # must not raise


def test_window_handles_no_settings_dir_or_log_path_gracefully(qt_app) -> None:
    """Safe Mode's whole premise is that something upstream already
    failed -- even *locating* the settings dir/log path might not be
    possible. The window must still construct and not offer buttons for
    what it can't act on."""
    window = SafeModeWindow(
        error_summary="boom",
        error_detail="boom",
        settings_dir=None,
        log_path=None,
        on_retry=MagicMock(),
        on_reset_settings=MagicMock(return_value=True),
        on_quit=MagicMock(),
    )
    assert window is not None
