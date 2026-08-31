"""Loads and applies the QSS theme, with a light fade-in on switch."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

_THEME_DIR = Path(__file__).parent


class ThemeManager:
    def __init__(self) -> None:
        self._current = "dark"

    def stylesheet_for(self, theme: str) -> str:
        filename = "dark_theme.qss" if theme != "light" else "light_theme.qss"
        path = _THEME_DIR / filename
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
