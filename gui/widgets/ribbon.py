"""
gui/widgets/ribbon.py
=====================
WorkflowRibbon — a two-row toolbar ribbon for the top of the main window.

Row 1 (stage tabs):  5 clickable stage buttons with 3-state completion badges.
Row 2 (tool bar):    tool buttons for the selected stage — each opens a panel form.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)


# ── Stage → Old panel mapping ────────────────────────────────────────────
# Each stage maps to a list of (old_panel_index, button_label) pairs.
# Clicking a tool button emits panel_requested(old_panel_index).

STAGE_TOOLS: list[list[tuple[int, str]]] = [
    # Stage 0 — Project Setup
    [(0, "Create Project"), (1, "Process DEM")],
    # Stage 1 — Catchment & Streams
    [(2, "Delineate Catchment"), (3, "Stream Network")],
    # Stage 2 — Surface Properties
    [(4, "Soil Parameters"), (5, "Land Cover")],
    # Stage 3 — Run Model
    [(6, "Parameter Files"), (7, "Forcing Data"), (8, "Run Simulation")],
    # Stage 4 — Results
    [(9, "View Results")],
]

# First old-panel index for each stage (used for default map activation)
STAGE_FIRST_PANEL = [tools[0][0] for tools in STAGE_TOOLS]


# ── Titles ────────────────────────────────────────────────────────────────

STAGE_TITLES = [
    "Project Setup",
    "Catchment & Streams",
    "Surface Properties",
    "Run Model",
    "Results",
]

# Short labels for the ribbon tabs
_TAB_LABELS = [
    "Setup",
    "Catchment",
    "Surface",
    "Model",
    "Results",
]

# Old 10-panel titles (used for form dock title bars)
PANEL_TITLES = [
    "Study Area",
    "DEM Processing",
    "Watershed",
    "Stream Network",
    "Soil Parameters",
    "Land Cover",
    "Parameter Files",
    "Forcing Data",
    "Run Model",
    "Results",
]


# ── Colours ────────────────────────────────────────────────────────────────

_BG           = QColor("#1e1e1e")
_TAB_BG       = QColor("#2b2d30")
_TAB_ACTIVE   = QColor("#1a6fc4")
_TAB_HOVER    = QColor("#3e4245")
_TAB_TEXT     = QColor("#cccccc")
_TAB_TEXT_ACT = QColor("#ffffff")
_COMPLETE_DOT = QColor("#2ecc71")
_PARTIAL_DOT  = QColor("#e67e22")
_PENDING_DOT  = QColor("#555555")
_TOOL_BG      = QColor("#252729")
_TOOL_BTN     = QColor("#3c3f41")
_TOOL_BTN_HV  = QColor("#4e5254")
_TOOL_TEXT    = QColor("#d4d4d4")
_BORDER       = QColor("#3a3d40")


class _StepButton(QPushButton):
    """A styled ribbon tab button with a 3-state completion badge."""

    def __init__(self, index: int, label: str, parent=None):
        super().__init__(parent)
        self.index = index
        self._label = label
        self._status = "none"   # "none" | "partial" | "done"
        self._active = False
        self.setCheckable(True)
        self.setFixedHeight(36)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_style()

    def set_status(self, status: str):
        self._status = status
        self._update_style()
        self.update()

    def set_active(self, active: bool):
        self._active = active
        self.setChecked(active)
        self._update_style()

    def _update_style(self):
        if self._active:
            bg = _TAB_ACTIVE.name()
            fg = _TAB_TEXT_ACT.name()
            border_bottom = _TAB_ACTIVE.name()
        else:
            bg = _TAB_BG.name()
            fg = _TAB_TEXT.name()
            border_bottom = "transparent"

        self.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {fg};
                border: none;
                border-bottom: 3px solid {border_bottom};
                padding: 4px 14px 4px 10px;
                font-size: 13px;
                font-weight: {'bold' if self._active else 'normal'};
                text-align: left;
            }}
            QPushButton:hover {{
                background: {_TAB_HOVER.name() if not self._active else bg};
            }}
        """)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Completion dot
        if self._status == "done":
            dot_color = _COMPLETE_DOT
        elif self._status == "partial":
            dot_color = _PARTIAL_DOT
        else:
            dot_color = _PENDING_DOT

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_color)
        y = self.height() // 2
        painter.drawEllipse(4, y - 3, 6, 6)

        # Stage number
        painter.setPen(QColor("#999999") if not self._active else QColor("#ffffff"))
        f = QFont(painter.font())
        f.setPointSize(9)
        painter.setFont(f)
        painter.drawText(13, 4, 16, 14, Qt.AlignmentFlag.AlignCenter, str(self.index + 1))

        # Label
        painter.setPen(QColor("#ffffff") if self._active else _TAB_TEXT)
        f.setPointSize(12)
        f.setBold(self._active)
        painter.setFont(f)
        text_x = 30
        painter.drawText(
            text_x, 0, self.width() - text_x - 4, self.height(),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self._label,
        )
        painter.end()


class WorkflowRibbon(QWidget):
    """Two-row workflow ribbon: 5 stage tabs + tool buttons per stage."""

    step_selected = pyqtSignal(int)       # stage index (0-4)
    panel_requested = pyqtSignal(int)     # old panel index (0-9)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_step = -1
        self._active_tool_panel: int = -1   # old panel index of the highlighted tool
        self._step_buttons: list[_StepButton] = []
        self._tool_buttons: list[QPushButton] = []
        self._tool_panel_indices: list[int] = []   # parallel to _tool_buttons
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Row 1: Stage tabs ─────────────────────────────────────────────
        self._tab_row = QFrame()
        self._tab_row.setStyleSheet(f"background: {_TAB_BG.name()};")
        tab_layout = QHBoxLayout(self._tab_row)
        tab_layout.setContentsMargins(4, 2, 4, 0)
        tab_layout.setSpacing(2)

        for i, label in enumerate(_TAB_LABELS):
            btn = _StepButton(i, label)
            btn.clicked.connect(lambda checked, idx=i: self._on_step_clicked(idx))
            tab_layout.addWidget(btn)
            self._step_buttons.append(btn)
        tab_layout.addStretch()
        layout.addWidget(self._tab_row)

        # ── Row 2: Tool buttons (dynamic) ─────────────────────────────────
        self._tool_row = QFrame()
        self._tool_row.setFixedHeight(38)
        self._tool_row.setStyleSheet(
            f"background: {_TOOL_BG.name()}; "
            f"border-top: 1px solid {_BORDER.name()};"
        )
        self._tool_layout = QHBoxLayout(self._tool_row)
        self._tool_layout.setContentsMargins(8, 4, 8, 4)
        self._tool_layout.setSpacing(6)
        self._tool_row.setVisible(False)
        layout.addWidget(self._tool_row)

    # ── Public API ─────────────────────────────────────────────────────────

    def set_step_complete(self, idx: int, status: str):
        """Set stage completion status: 'none', 'partial', or 'done'."""
        if 0 <= idx < len(self._step_buttons):
            self._step_buttons[idx].set_status(status)

    def set_active_step(self, idx: int):
        self._on_step_clicked(idx, emit=False)

    def set_active_tool(self, panel_idx: int) -> None:
        """Highlight the tool button for *panel_idx* and dim the others."""
        self._active_tool_panel = panel_idx
        for btn, pidx in zip(self._tool_buttons, self._tool_panel_indices):
            if pidx == panel_idx:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {_TAB_ACTIVE.name()};
                        color: #ffffff;
                        border: 1px solid {_TAB_ACTIVE.name()};
                        border-radius: 4px;
                        padding: 3px 10px;
                        font-size: 11px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background: #2080d4;
                        color: #ffffff;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {_TOOL_BTN.name()};
                        color: {_TOOL_TEXT.name()};
                        border: 1px solid {_BORDER.name()};
                        border-radius: 4px;
                        padding: 3px 10px;
                        font-size: 11px;
                    }}
                    QPushButton:hover {{
                        background: {_TOOL_BTN_HV.name()};
                        color: #ffffff;
                    }}
                """)

    @property
    def active_step(self) -> int:
        return self._active_step

    # ── Internals ──────────────────────────────────────────────────────────

    def _on_step_clicked(self, idx: int, emit: bool = True):
        if idx == self._active_step:
            # Re-clicking the active stage opens the first panel's form
            if emit and STAGE_TOOLS[idx]:
                panel_idx = STAGE_TOOLS[idx][0][0]
                self.panel_requested.emit(panel_idx)
            return

        self._active_step = idx
        for i, btn in enumerate(self._step_buttons):
            btn.set_active(i == idx)

        self._rebuild_tool_row(idx)

        if emit:
            self.step_selected.emit(idx)

    def _rebuild_tool_row(self, idx: int):
        # Clear existing tool buttons
        while self._tool_layout.count():
            item = self._tool_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._tool_buttons.clear()
        self._tool_panel_indices.clear()

        tools = STAGE_TOOLS[idx] if idx < len(STAGE_TOOLS) else []

        # Stage label with step indicator
        step_label = QLabel(f"  Step {idx + 1} of 5 — {STAGE_TITLES[idx]}")
        step_label.setStyleSheet(
            f"color: {_TAB_TEXT_ACT.name()}; font-weight: bold; font-size: 12px;"
        )
        self._tool_layout.addWidget(step_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {_BORDER.name()};")
        self._tool_layout.addWidget(sep)

        # Default active tool to the first panel in this stage
        if tools and self._active_tool_panel not in [p for p, _ in tools]:
            self._active_tool_panel = tools[0][0]

        # Tool buttons
        for panel_idx, label in tools:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            is_active = (panel_idx == self._active_tool_panel)
            if is_active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {_TAB_ACTIVE.name()};
                        color: #ffffff;
                        border: 1px solid {_TAB_ACTIVE.name()};
                        border-radius: 4px;
                        padding: 3px 10px;
                        font-size: 11px;
                        font-weight: bold;
                    }}
                    QPushButton:hover {{
                        background: #2080d4;
                        color: #ffffff;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {_TOOL_BTN.name()};
                        color: {_TOOL_TEXT.name()};
                        border: 1px solid {_BORDER.name()};
                        border-radius: 4px;
                        padding: 3px 10px;
                        font-size: 11px;
                    }}
                    QPushButton:hover {{
                        background: {_TOOL_BTN_HV.name()};
                        color: #ffffff;
                    }}
                """)
            btn.clicked.connect(
                lambda checked, pidx=panel_idx: self._on_tool_clicked(pidx)
            )
            self._tool_layout.addWidget(btn)
            self._tool_buttons.append(btn)
            self._tool_panel_indices.append(panel_idx)

        self._tool_layout.addStretch()
        self._tool_row.setVisible(True)

    def _on_tool_clicked(self, panel_idx: int) -> None:
        """Handle tool button click: highlight it and emit panel_requested."""
        self.set_active_tool(panel_idx)
        self.panel_requested.emit(panel_idx)
