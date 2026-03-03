"""
gui/widgets/log_dock.py
=======================
LogDock — collapsible bottom dock that shows timestamped processing messages.
"""

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QTextCharFormat, QColor, QTextCursor
from PyQt6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QPlainTextEdit, QLabel,
)


class LogDock(QDockWidget):
    """Bottom dock widget containing a timestamped log panel."""

    def __init__(self, parent=None):
        super().__init__("Log", parent)
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetMovable
        )

        # ── inner widget ────────────────────────────────────────────────────
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # toolbar row
        toolbar = QHBoxLayout()
        lbl = QLabel("Output log")
        lbl.setStyleSheet("font-weight: bold; color: #555;")
        toolbar.addWidget(lbl)
        toolbar.addStretch()
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(56)
        clear_btn.setFixedHeight(22)
        clear_btn.clicked.connect(self._clear)
        toolbar.addWidget(clear_btn)
        layout.addLayout(toolbar)

        # text area
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(2000)   # cap memory use
        # Use a monospace font available on macOS/Windows/Linux
        for _fname in ("Menlo", "Consolas", "DejaVu Sans Mono", "Monospace"):
            font = QFont(_fname, 11)
            if font.exactMatch():
                break
        del _fname
        self._text.setFont(font)
        self._text.setStyleSheet(
            "background:#1e1e1e; color:#d4d4d4; border:none; padding:4px;"
        )
        layout.addWidget(self._text)

        self.setWidget(inner)
        self.setMinimumHeight(120)

    # ── public API ──────────────────────────────────────────────────────────

    def append_line(self, msg: str, level: str = "info") -> None:
        """Append a timestamped line. level ∈ {'info','warn','error','ok'}."""
        ts = datetime.now().strftime("%H:%M:%S")
        colours = {
            "info":  "#d4d4d4",
            "warn":  "#dcdcaa",
            "error": "#f44747",
            "ok":    "#4ec9b0",
        }
        colour = colours.get(level, "#d4d4d4")
        html = (
            f'<span style="color:#858585">[{ts}]</span> '
            f'<span style="color:{colour}">{msg}</span>'
        )
        self._text.appendHtml(html)
        # auto-scroll to bottom
        self._text.verticalScrollBar().setValue(
            self._text.verticalScrollBar().maximum()
        )

    def _clear(self) -> None:
        self._text.clear()
