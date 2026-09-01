"""Loads and applies the QSS theme, with a light fade-in on switch."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from instacore_sync.core.resource_paths import bundled_resource_dir, is_frozen


def _theme_dir() -> Path:
    """Where dark_theme.qss/light_theme.qss actually live.

    Regression fix: this used to be `Path(__file__).parent`, which is
    correct running from source but broken once this module is frozen
    into a PyInstaller build — a module bundled into the PYZ archive
    (this spec's `noarchive=False`) has no real on-disk `__file__` to
    resolve a sibling file against, so this would have raised
    `FileNotFoundError` reading the QSS file on the very first window a
    packaged .exe ever tries to show (`MainWindow.__init__` applies the
    theme unconditionally). The .qss files are bundled as `datas` in
    `packaging/pyinstaller.spec` alongside `settings.example.yaml`, so
    they're resolved the same frozen-aware way.
    """
    if is_frozen():
        return bundled_resource_dir() / "instacore_sync" / "ui" / "theme"
    return Path(__file__).resolve().parent


class ThemeManager:
    def __init__(self) -> None:
        self._current = "dark"

    def stylesheet_for(self, theme: str) -> str:
        filename = "dark_theme.qss" if theme != "light" else "light_theme.qss"
        path = _theme_dir() / filename
        return path.read_text(encoding="utf-8")

    def apply(self, widget: QWidget, theme: str) -> None:
        self._current = theme
        widget.setStyleSheet(self.stylesheet_for(theme))

    @property
    def current(self) -> str:
        return self._current

    @staticmethod
    def fade_in(widget: QWidget, duration_ms: int = 220) -> QPropertyAnimation:
        """A small, tasteful opacity fade — used when switching views/theme."""
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", widget)
        animation.setDuration(duration_ms)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        return animation
