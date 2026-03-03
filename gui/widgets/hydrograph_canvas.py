"""
gui/widgets/hydrograph_canvas.py
=================================
HydrographCanvas  — matplotlib twin-axis chart widget (replaces Plotly).

Displays:
  • Hydrograph:    discharge Q (m³/s) vs time  — left axis
  • (optional)     areal rainfall [mm/h]       — right axis, bar chart
  • FDC tab:       Flow Duration Curve
  • Soil moisture: mean catchment % saturation vs time

Usage:
    canvas = HydrographCanvas()
    canvas.plot_hydrograph(times, Q_arr, P_arr, title="Simulation")
    canvas.plot_fdc(Q_arr)
    canvas.plot_soil_moisture(times, Vs_arr)
    tab_widget.addTab(canvas, "Charts")
"""

from __future__ import annotations

import numpy as np

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
    QLabel, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import Qt


_BG   = "#2b2b2b"
_AX   = "#1e1e1e"
_TEXT = "#e8e8e8"
_BLUE = "#3498db"
_RED  = "#e74c3c"
_GREEN = "#2ecc71"
_GREY = "#555"


class HydrographCanvas(QWidget):
    """Multi-chart widget for model results visualisation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        toolbar = QWidget()
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet("background:#3c3f41; border-bottom:1px solid #555;")
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(8, 2, 8, 2)
        tb.setSpacing(8)

        lbl = QLabel("Chart:")
        lbl.setStyleSheet("color:#aaa; font-size:12px;")
        tb.addWidget(lbl)

        self._chart_combo = QComboBox()
        self._chart_combo.setFixedWidth(200)
        for name in ["Hydrograph", "Flow Duration Curve", "Soil Moisture"]:
            self._chart_combo.addItem(name)
        self._chart_combo.currentTextChanged.connect(self._on_chart_changed)
        tb.addWidget(self._chart_combo)
        tb.addStretch()
        layout.addWidget(toolbar)

        # Figure
        self._fig = Figure(facecolor=_BG, tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._canvas)

        self._show_placeholder()

        # Stored data
        self._times: np.ndarray | None = None
        self._Q:     np.ndarray | None = None
        self._P:     np.ndarray | None = None
        self._Vs:    np.ndarray | None = None   # mean % saturation

    # ── Public API ─────────────────────────────────────────────────────────

    def plot_hydrograph(
        self,
        times:  np.ndarray,
        Q_arr:  np.ndarray,
        P_arr:  np.ndarray | None = None,
        title:  str = "Simulated Hydrograph",
    ) -> None:
        """Plot discharge and optional rainfall on twin axes."""
        self._times = times
        self._Q     = Q_arr
        self._P     = P_arr
        self._chart_combo.setCurrentText("Hydrograph")
        self._draw_hydrograph()

    def plot_fdc(self, Q_arr: np.ndarray | None = None) -> None:
        """Plot flow duration curve for *Q_arr* (or stored Q)."""
        if Q_arr is not None:
            self._Q = Q_arr
        self._chart_combo.setCurrentText("Flow Duration Curve")
        self._draw_fdc()

    def plot_soil_moisture(
        self,
        times: np.ndarray | None = None,
        Vs_arr: np.ndarray | None = None,
    ) -> None:
        """Plot mean catchment soil moisture percentage."""
        if times is not None:
            self._times = times
        if Vs_arr is not None:
            self._Vs = Vs_arr
        self._chart_combo.setCurrentText("Soil Moisture")
        self._draw_soil_moisture()

    def clear(self) -> None:
        self._times = self._Q = self._P = self._Vs = None
        self._show_placeholder()

    # ── Private ────────────────────────────────────────────────────────────

    def _on_chart_changed(self, name: str) -> None:
        if name == "Hydrograph":
            self._draw_hydrograph()
        elif name == "Flow Duration Curve":
            self._draw_fdc()
        elif name == "Soil Moisture":
            self._draw_soil_moisture()

    def _draw_hydrograph(self) -> None:
        self._fig.clear()
        if self._Q is None:
            self._show_placeholder()
            return

        if self._P is not None:
            gs  = GridSpec(2, 1, figure=self._fig, height_ratios=[1, 3], hspace=0.05)
            ax_p = self._fig.add_subplot(gs[0])
            ax_q = self._fig.add_subplot(gs[1], sharex=ax_p)
            self._style_ax(ax_p)
            self._style_ax(ax_q)

            x = self._times if self._times is not None else np.arange(len(self._P))
            ax_p.bar(x, self._P, color=_BLUE, alpha=0.6, width=np.diff(x).mean() if len(x) > 1 else 1)
            ax_p.invert_yaxis()
            ax_p.set_ylabel("P (mm/s)", color=_TEXT, fontsize=8)
            ax_p.tick_params(labelbottom=False)
        else:
            ax_q = self._fig.add_subplot(111)
            self._style_ax(ax_q)
            x = self._times if self._times is not None else np.arange(len(self._Q))

        ax_q.plot(x, self._Q, color=_RED, linewidth=1.5, label="Q (m³/s)")
        ax_q.set_ylabel("Q (m³/s)", color=_TEXT, fontsize=8)
        ax_q.set_xlabel("Time step", color=_TEXT, fontsize=8)
        ax_q.legend(facecolor=_AX, edgecolor=_GREY, labelcolor=_TEXT, fontsize=8)

        self._fig.tight_layout()
        self._canvas.draw_idle()

    def _draw_fdc(self) -> None:
        self._fig.clear()
        if self._Q is None:
            self._show_placeholder("No discharge data. Run the model first.")
            return

        ax = self._fig.add_subplot(111)
        self._style_ax(ax)

        Q_sorted = np.sort(self._Q.flatten())[::-1]
        exceedance = np.linspace(0, 100, len(Q_sorted))
        ax.semilogy(exceedance, Q_sorted, color=_RED, linewidth=1.5)
        ax.set_xlabel("Exceedance probability (%)", color=_TEXT, fontsize=8)
        ax.set_ylabel("Q (m³/s)", color=_TEXT, fontsize=8)
        ax.set_title("Flow Duration Curve", color=_TEXT, fontsize=10)
        ax.grid(True, color=_GREY, alpha=0.4, linestyle="--")

        self._fig.tight_layout()
        self._canvas.draw_idle()

    def _draw_soil_moisture(self) -> None:
        self._fig.clear()
        if self._Vs is None:
            self._show_placeholder("No soil moisture data. Run the model first.")
            return

        ax = self._fig.add_subplot(111)
        self._style_ax(ax)

        x = self._times if self._times is not None else np.arange(len(self._Vs))
        ax.plot(x, self._Vs, color=_GREEN, linewidth=1.5, label="Mean Vs (%)")
        ax.set_ylim(0, 100)
        ax.set_ylabel("Soil saturation (%)", color=_TEXT, fontsize=8)
        ax.set_xlabel("Time step", color=_TEXT, fontsize=8)
        ax.legend(facecolor=_AX, edgecolor=_GREY, labelcolor=_TEXT, fontsize=8)
        ax.grid(True, color=_GREY, alpha=0.3, linestyle="--")

        self._fig.tight_layout()
        self._canvas.draw_idle()

    def _show_placeholder(self, msg: str = "No results loaded yet.") -> None:
        self._fig.clear()
        ax = self._fig.add_subplot(111)
        self._style_ax(ax)
        ax.text(0.5, 0.5, msg, ha="center", va="center",
                color="#555", fontsize=14, transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        self._canvas.draw_idle()

    def _style_ax(self, ax) -> None:
        ax.set_facecolor(_AX)
        ax.tick_params(colors=_TEXT, labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor(_GREY)
