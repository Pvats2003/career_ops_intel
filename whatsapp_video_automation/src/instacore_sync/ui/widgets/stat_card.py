"""A small glass-panel "stat tile" used across the Dashboard."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout


class StatCard(QFrame):
    def __init__(self, label: str, initial_value: str = "0", icon: str = "", parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setMinimumHeight(96)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        if icon:
            icon_label = QLabel(icon)
            icon_label.setStyleSheet("font-size: 18px;")
            top_row.addWidget(icon_label)
        top_row.addStretch(1)
        outer.addLayout(top_row)

        self._value_label = QLabel(initial_value)
        self._value_label.setObjectName("StatValue")
        outer.addWidget(self._value_label)

        self._name_label = QLabel(label.upper())
        self._name_label.setObjectName("StatLabel")
        outer.addWidget(self._name_label)

        outer.addStretch(1)

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_label(self, label: str) -> None:
        self._name_label.setText(label.upper())
