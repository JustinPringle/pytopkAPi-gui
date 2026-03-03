"""
gui/widgets/raster_canvas.py
============================
RasterCanvas  — matplotlib FigureCanvas embedded in Qt for displaying
                raster arrays (DEMs, flow direction, accumulation,
                masks, slope, etc.) with a colourbar and a simple
                layer switcher.

Usage:
    canvas = RasterCanvas()
    canvas.show_array(arr, title="Filled DEM", cmap="terrain", unit="m")
    canvas.show_file(path)                  # reads single-band GeoTIFF
    tab_widget.addTab(canvas, "Raster")
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import matplotlib.colors as mcolors

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QComboBox,
    QLabel, QPushButton, QSizePolicy,
)
from PyQt6.QtCore import Qt


# ── Matplotlib figure with dark background to match app theme ─────────────────
_FIG_FACECOLOUR = "#2b2b2b"
_AX_FACECOLOUR  = "#1e1e1e"
_TEXT_COLOUR    = "#e8e8e8"


class RasterCanvas(QWidget):
    """Matplotlib raster viewer embedded in Qt.

    Public API
    ----------
    show_array(arr, title, cmap, unit, nodata)
        Display a numpy array.
    show_file(path, band, title, cmap, unit)
        Open a GeoTIFF and display the specified band.
    add_layer(name, arr, cmap, unit, nodata)
        Add a named layer to the internal layer dict; switch via combo.
    clear()
        Remove all layers and blank the canvas.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._layers: dict[str, dict] = {}   # name → {arr, cmap, unit, nodata}
        self._current: str | None = None

        self._build_ui()

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Toolbar ────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(36)
        toolbar.setStyleSheet("background:#3c3f41; border-bottom:1px solid #555;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 2, 8, 2)
        tb_layout.setSpacing(8)

        lbl = QLabel("Layer:")
        lbl.setStyleSheet("color:#aaa; font-size:12px;")
        tb_layout.addWidget(lbl)

        self._layer_combo = QComboBox()
        self._layer_combo.setFixedWidth(220)
        self._layer_combo.currentTextChanged.connect(self._on_layer_changed)
        tb_layout.addWidget(self._layer_combo)

        self._reset_btn = QPushButton("⟳ Reset zoom")
        self._reset_btn.setFixedWidth(100)
        self._reset_btn.setStyleSheet(
            "QPushButton{background:#4a4e50;color:#e8e8e8;border:1px solid #666;"
            "border-radius:3px;padding:2px 8px;font-size:11px;}"
            "QPushButton:hover{background:#5a5e60;}"
        )
        self._reset_btn.clicked.connect(self._reset_zoom)
        tb_layout.addWidget(self._reset_btn)

        tb_layout.addStretch()
        layout.addWidget(toolbar)

        # ── Matplotlib figure ─────────────────────────────────────────────
        self._fig = Figure(facecolor=_FIG_FACECOLOUR, tight_layout=True)
        self._ax  = self._fig.add_subplot(111)
        self._ax.set_facecolor(_AX_FACECOLOUR)
        self._ax.tick_params(colors=_TEXT_COLOUR)
        for spine in self._ax.spines.values():
            spine.set_edgecolor("#555")
        self._cbar = None

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self._canvas)

        # Enable matplotlib's interactive zoom/pan via mouse
        self._canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._show_placeholder()

    # ── Public API ─────────────────────────────────────────────────────────

    def show_array(
        self,
        arr: np.ndarray,
        title: str = "",
        cmap: str = "viridis",
        unit: str = "",
        nodata: float | None = None,
        name: str | None = None,
    ) -> None:
        """Display *arr* immediately and add it as a named layer."""
        layer_name = name or title or "Layer"
        self.add_layer(layer_name, arr, cmap=cmap, unit=unit, nodata=nodata)
        self._layer_combo.setCurrentText(layer_name)

    def show_file(
        self,
        path: str | os.PathLike,
        band: int = 1,
        title: str | None = None,
        cmap: str = "viridis",
        unit: str = "",
    ) -> None:
        """Read *path* (GeoTIFF) and display band *band*."""
        try:
            import rasterio
            with rasterio.open(path) as src:
                arr    = src.read(band).astype(float)
                nodata = src.nodata
        except Exception as exc:
            self._show_error(f"Cannot open raster:\n{exc}")
            return

        name = title or Path(path).name
        self.add_layer(name, arr, cmap=cmap, unit=unit, nodata=nodata)
        self._layer_combo.setCurrentText(name)

    def add_layer(
        self,
        name: str,
        arr: np.ndarray,
        cmap: str = "viridis",
        unit: str = "",
        nodata: float | None = None,
    ) -> None:
        """Add or update a named layer without immediately switching to it."""
        self._layers[name] = {"arr": arr, "cmap": cmap, "unit": unit, "nodata": nodata}
        if name not in [self._layer_combo.itemText(i)
                        for i in range(self._layer_combo.count())]:
            self._layer_combo.addItem(name)

    def clear(self) -> None:
        """Remove all layers and blank the canvas."""
        self._layers.clear()
        self._current = None
        self._layer_combo.clear()
        self._show_placeholder()

    # ── Private helpers ────────────────────────────────────────────────────

    def _on_layer_changed(self, name: str) -> None:
        if name and name in self._layers:
            self._current = name
            self._render(self._layers[name])

    def _render(self, layer: dict) -> None:
        arr    = layer["arr"].copy().astype(float)
        cmap   = layer["cmap"]
        unit   = layer["unit"]
        nodata = layer["nodata"]

        # Mask nodata / inf / nan
        mask = np.zeros(arr.shape, dtype=bool)
        if nodata is not None:
            mask |= (arr == nodata)
        mask |= ~np.isfinite(arr)
        arr_m = np.ma.array(arr, mask=mask)

        self._ax.clear()
        self._ax.set_facecolor(_AX_FACECOLOUR)
        self._ax.tick_params(colors=_TEXT_COLOUR, labelsize=8)
        for spine in self._ax.spines.values():
            spine.set_edgecolor("#555")

        # Remove old colourbar
        if self._cbar is not None:
            try:
                self._cbar.remove()
            except Exception:
                pass
            self._cbar = None

        im = self._ax.imshow(arr_m, cmap=cmap, interpolation="nearest")
        self._cbar = self._fig.colorbar(im, ax=self._ax, fraction=0.03, pad=0.02)
        self._cbar.ax.tick_params(colors=_TEXT_COLOUR, labelsize=8)
        if unit:
            self._cbar.set_label(unit, color=_TEXT_COLOUR, fontsize=9)

        self._ax.set_title(self._current or "", color=_TEXT_COLOUR, fontsize=10)
        self._ax.set_xlabel("Column", color=_TEXT_COLOUR, fontsize=8)
        self._ax.set_ylabel("Row",    color=_TEXT_COLOUR, fontsize=8)

        self._fig.tight_layout()
        self._canvas.draw_idle()

    def _reset_zoom(self) -> None:
        self._ax.autoscale()
        self._canvas.draw_idle()

    def _show_placeholder(self) -> None:
        self._ax.clear()
        self._ax.set_facecolor(_AX_FACECOLOUR)
        self._ax.text(
            0.5, 0.5, "No raster loaded",
            ha="center", va="center", color="#555",
            fontsize=14, transform=self._ax.transAxes,
        )
        for spine in self._ax.spines.values():
            spine.set_edgecolor("#333")
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._canvas.draw_idle()

    def _show_error(self, msg: str) -> None:
        self._ax.clear()
        self._ax.set_facecolor(_AX_FACECOLOUR)
        self._ax.text(
            0.5, 0.5, msg,
            ha="center", va="center", color="#e74c3c",
            fontsize=11, wrap=True, transform=self._ax.transAxes,
        )
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._canvas.draw_idle()
