"""
gui/widgets/raster_canvas.py
============================
RasterCanvas — enhanced raster viewer with:
  • Scroll-wheel zoom at cursor position
  • Pan mode (toggle button + drag)
  • +/- and Reset buttons
  • Base layer + Overlay layer with per-pixel alpha blending (Porter-Duff "over")
  • Per-layer colormap picker (combo)
  • Stats bar: min / max / mean / pixel count
  • Hover pixel-value readout
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import matplotlib.cm as mcm
import matplotlib.colors as mcolors
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

# ── Theme colours ─────────────────────────────────────────────────────────────
_FIG_BG = "#2b2b2b"
_AX_BG  = "#1e1e1e"
_FG     = "#e8e8e8"
_GREY   = "#555"

# Curated colourmap list
_CMAPS = [
    "terrain", "gist_earth", "gray",
    "viridis", "plasma", "inferno", "magma", "cividis",
    "Blues", "Greens", "YlOrRd", "YlOrBr", "RdYlGn_r",
    "cool", "hot", "Purples", "tab20", "tab20b",
    "RdBu", "seismic", "coolwarm",
]

_NO_OVERLAY = "— none —"


def _get_cmap(name: str):
    try:
        return mcm.get_cmap(name)
    except Exception:
        return mcm.get_cmap("viridis")


class RasterCanvas(QWidget):
    """Matplotlib raster viewer with zoom, pan and alpha-blended overlay.

    Public API
    ----------
    show_array(arr, title, cmap, unit, nodata, name)
        Add a numpy array as the active base layer.
    show_file(path, band, title, cmap, unit)
        Read a GeoTIFF band and display it as the active base layer.
    add_layer(name, arr, cmap, unit, nodata)
        Add a named layer without switching to it.
    set_overlay(name, path, cmap)
        Load *path* and set it as the active overlay layer.
    clear()
        Remove all layers.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layers: dict[str, dict] = {}   # name → {arr, cmap, unit, nodata}
        self._pan_ref: tuple | None = None   # (x0, y0, xlim, ylim) during drag
        self._view_reset_pending = True      # autoscale on next render

        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QWidget()
        tb.setFixedHeight(34)
        tb.setObjectName("rasterToolbar")
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(6, 2, 6, 2)
        tbl.setSpacing(4)

        self._btn_zoom_in  = _tool_btn("+",  "Zoom in  (or scroll up)")
        self._btn_zoom_out = _tool_btn("−",  "Zoom out (or scroll down)")
        self._btn_pan      = _tool_btn("✥",  "Pan — drag to move view", checkable=True)
        self._btn_reset    = _tool_btn("[ ]", "Reset view to full extent")
        for b in (self._btn_zoom_in, self._btn_zoom_out, self._btn_pan, self._btn_reset):
            tbl.addWidget(b)
        tbl.addWidget(_vsep())

        # Base layer
        tbl.addWidget(_lbl("Base:"))
        self._base_combo = QComboBox()
        self._base_combo.setFixedWidth(160)
        self._base_combo.setToolTip("Active base layer")
        tbl.addWidget(self._base_combo)

        self._base_cmap = QComboBox()
        self._base_cmap.addItems(_CMAPS)
        self._base_cmap.setFixedWidth(110)
        self._base_cmap.setToolTip("Base layer colourmap")
        tbl.addWidget(self._base_cmap)

        tbl.addWidget(_vsep())

        # Overlay layer
        tbl.addWidget(_lbl("Overlay:"))
        self._overlay_combo = QComboBox()
        self._overlay_combo.setFixedWidth(160)
        self._overlay_combo.addItem(_NO_OVERLAY)
        self._overlay_combo.setToolTip("Layer to blend on top of base")
        tbl.addWidget(self._overlay_combo)

        self._overlay_cmap = QComboBox()
        self._overlay_cmap.addItems(_CMAPS)
        self._overlay_cmap.setCurrentText("gray")
        self._overlay_cmap.setFixedWidth(110)
        self._overlay_cmap.setToolTip("Overlay layer colourmap")
        tbl.addWidget(self._overlay_cmap)

        # Opacity
        tbl.addWidget(_lbl("α:"))
        self._alpha_slider = QSlider(Qt.Orientation.Horizontal)
        self._alpha_slider.setRange(0, 100)
        self._alpha_slider.setValue(50)
        self._alpha_slider.setFixedWidth(90)
        self._alpha_slider.setToolTip("Overlay opacity (0 = transparent, 100 = opaque)")
        tbl.addWidget(self._alpha_slider)

        self._alpha_lbl = QLabel("50%")
        self._alpha_lbl.setFixedWidth(30)
        self._alpha_lbl.setObjectName("rasterAlphaLabel")
        tbl.addWidget(self._alpha_lbl)

        tbl.addStretch()
        root.addWidget(tb)

        # ── Canvas ────────────────────────────────────────────────────────────
        self._fig = Figure(facecolor=_FIG_BG)
        self._fig.subplots_adjust(left=0.06, right=0.90, top=0.95, bottom=0.06)
        self._ax  = self._fig.add_subplot(111)
        self._ax.set_facecolor(_AX_BG)
        self._ax.tick_params(colors=_FG, labelsize=8)
        for sp in self._ax.spines.values():
            sp.set_edgecolor(_GREY)
        self._cbar = None

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        root.addWidget(self._canvas, stretch=1)

        # ── Stats bar ─────────────────────────────────────────────────────────
        sb = QWidget()
        sb.setFixedHeight(22)
        sb.setObjectName("rasterStatsBar")
        sbl = QHBoxLayout(sb)
        sbl.setContentsMargins(8, 0, 8, 0)
        self._stats_lbl = QLabel("")
        self._stats_lbl.setObjectName("rasterStatsLabel")
        sbl.addWidget(self._stats_lbl)
        sbl.addStretch()
        self._pixel_lbl = QLabel("")
        self._pixel_lbl.setObjectName("rasterStatsLabel")
        sbl.addWidget(self._pixel_lbl)
        root.addWidget(sb)

        # ── Signal connections ────────────────────────────────────────────────
        self._base_combo.currentTextChanged.connect(self._on_base_changed)
        self._base_cmap.currentTextChanged.connect(self._on_base_cmap_changed)
        self._overlay_combo.currentTextChanged.connect(self._do_render)
        self._overlay_cmap.currentTextChanged.connect(self._do_render)
        self._alpha_slider.valueChanged.connect(self._do_render)
        self._alpha_slider.valueChanged.connect(
            lambda v: self._alpha_lbl.setText(f"{v}%")
        )

        self._btn_zoom_in.clicked.connect(lambda: self._zoom(0.75))
        self._btn_zoom_out.clicked.connect(lambda: self._zoom(1.33))
        self._btn_pan.toggled.connect(self._on_pan_toggled)
        self._btn_reset.clicked.connect(self._reset_view)

        self._canvas.mpl_connect("scroll_event",         self._on_scroll)
        self._canvas.mpl_connect("button_press_event",   self._on_press)
        self._canvas.mpl_connect("button_release_event", self._on_release)
        self._canvas.mpl_connect("motion_notify_event",  self._on_motion)

        self._show_placeholder()

    # ── Public API ─────────────────────────────────────────────────────────────

    def show_array(
        self,
        arr: np.ndarray,
        title: str = "",
        cmap: str = "viridis",
        unit: str = "",
        nodata: float | None = None,
        name: str | None = None,
    ) -> None:
        layer_name = name or title or "Layer"
        self.add_layer(layer_name, arr, cmap=cmap, unit=unit, nodata=nodata)
        self._view_reset_pending = True
        self._base_combo.setCurrentText(layer_name)

    def show_file(
        self,
        path: str | os.PathLike,
        band: int = 1,
        title: str | None = None,
        cmap: str = "viridis",
        unit: str = "",
    ) -> None:
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
        self._view_reset_pending = True
        self._base_combo.setCurrentText(name)

    def add_layer(
        self,
        name: str,
        arr: np.ndarray,
        cmap: str = "viridis",
        unit: str = "",
        nodata: float | None = None,
    ) -> None:
        self._layers[name] = {"arr": arr, "cmap": cmap, "unit": unit, "nodata": nodata}
        self._base_combo.blockSignals(True)
        if name not in [self._base_combo.itemText(i) for i in range(self._base_combo.count())]:
            self._base_combo.addItem(name)
        self._base_combo.blockSignals(False)

        self._overlay_combo.blockSignals(True)
        if name not in [self._overlay_combo.itemText(i) for i in range(self._overlay_combo.count())]:
            self._overlay_combo.addItem(name)
        self._overlay_combo.blockSignals(False)

    def set_overlay(self, name: str, path: str, cmap: str = "gray") -> None:
        """Load *path* and select it as the active overlay layer."""
        if name not in self._layers:
            try:
                import rasterio
                with rasterio.open(path) as src:
                    arr    = src.read(1).astype(float)
                    nodata = src.nodata
                self.add_layer(name, arr, cmap=cmap, nodata=nodata)
            except Exception:
                return
        self._overlay_combo.setCurrentText(name)
        if cmap in _CMAPS:
            self._overlay_cmap.setCurrentText(cmap)

    def clear(self) -> None:
        self._layers.clear()
        self._view_reset_pending = True
        self._base_combo.blockSignals(True)
        self._base_combo.clear()
        self._base_combo.blockSignals(False)
        self._overlay_combo.blockSignals(True)
        self._overlay_combo.clear()
        self._overlay_combo.addItem(_NO_OVERLAY)
        self._overlay_combo.blockSignals(False)
        self._stats_lbl.setText("")
        self._pixel_lbl.setText("")
        self._show_placeholder()

    # ── Zoom / pan ─────────────────────────────────────────────────────────────

    def _zoom(self, factor: float) -> None:
        xl = self._ax.get_xlim()
        yl = self._ax.get_ylim()
        cx = (xl[0] + xl[1]) / 2
        cy = (yl[0] + yl[1]) / 2
        self._ax.set_xlim(cx - (xl[1] - xl[0]) * factor / 2,
                          cx + (xl[1] - xl[0]) * factor / 2)
        self._ax.set_ylim(cy - (yl[1] - yl[0]) * factor / 2,
                          cy + (yl[1] - yl[0]) * factor / 2)
        self._canvas.draw_idle()

    def _reset_view(self) -> None:
        self._ax.autoscale()
        self._canvas.draw_idle()

    def _on_pan_toggled(self, checked: bool) -> None:
        self._canvas.setCursor(
            Qt.CursorShape.OpenHandCursor if checked else Qt.CursorShape.ArrowCursor
        )

    def _on_scroll(self, event) -> None:
        if event.inaxes is None:
            return
        factor = 0.8 if event.button == "up" else 1.25
        cx, cy = event.xdata, event.ydata
        xl = self._ax.get_xlim()
        yl = self._ax.get_ylim()
        self._ax.set_xlim(cx - (cx - xl[0]) * factor, cx + (xl[1] - cx) * factor)
        self._ax.set_ylim(cy - (cy - yl[0]) * factor, cy + (yl[1] - cy) * factor)
        self._canvas.draw_idle()

    def _on_press(self, event) -> None:
        if event.inaxes and self._btn_pan.isChecked() and event.button == 1:
            self._pan_ref = (event.xdata, event.ydata,
                             self._ax.get_xlim(), self._ax.get_ylim())

    def _on_release(self, event) -> None:
        self._pan_ref = None

    def _on_motion(self, event) -> None:
        if event.inaxes is None:
            return
        # Pan
        if self._pan_ref and event.button == 1:
            x0, y0, xl, yl = self._pan_ref
            dx, dy = event.xdata - x0, event.ydata - y0
            self._ax.set_xlim(xl[0] - dx, xl[1] - dx)
            self._ax.set_ylim(yl[0] - dy, yl[1] - dy)
            self._canvas.draw_idle()
        # Pixel readout
        col = int(round(event.xdata))
        row = int(round(event.ydata))
        base_name = self._base_combo.currentText()
        if base_name in self._layers:
            arr = self._layers[base_name]["arr"]
            if 0 <= row < arr.shape[0] and 0 <= col < arr.shape[1]:
                self._pixel_lbl.setText(f"row {row}  col {col}  val {arr[row, col]:.5g}")
                return
        self._pixel_lbl.setText("")

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _on_base_changed(self, name: str) -> None:
        self._view_reset_pending = True
        if name in self._layers:
            cmap = self._layers[name].get("cmap", "viridis")
            self._base_cmap.blockSignals(True)
            idx = self._base_cmap.findText(cmap)
            if idx >= 0:
                self._base_cmap.setCurrentIndex(idx)
            self._base_cmap.blockSignals(False)
        self._do_render()

    def _on_base_cmap_changed(self, cmap: str) -> None:
        name = self._base_combo.currentText()
        if name in self._layers:
            self._layers[name]["cmap"] = cmap
        self._do_render()

    def _do_render(self, *_) -> None:
        base_name = self._base_combo.currentText()
        if not base_name or base_name not in self._layers:
            self._show_placeholder()
            return

        base = self._layers[base_name]
        base_cmap_name = self._base_cmap.currentText()

        overlay_name = self._overlay_combo.currentText()
        overlay = (self._layers.get(overlay_name)
                   if overlay_name != _NO_OVERLAY else None)
        alpha = self._alpha_slider.value() / 100.0

        # ── Prepare base RGBA ─────────────────────────────────────────────────
        base_arr = _mask(base["arr"], base["nodata"])
        vmin_b   = float(np.nanmin(base_arr))
        vmax_b   = float(np.nanmax(base_arr))
        norm_b   = mcolors.Normalize(vmin=vmin_b, vmax=vmax_b)
        cmap_b   = _get_cmap(base_cmap_name)
        base_rgba = cmap_b(norm_b(base_arr.filled(np.nan))).copy()
        base_rgba[base_arr.mask, 3] = 0.0

        # ── Composite overlay (Porter-Duff "over") ────────────────────────────
        if (overlay is not None
                and overlay["arr"].shape == base["arr"].shape):
            ov_arr  = _mask(overlay["arr"], overlay["nodata"])
            norm_o  = mcolors.Normalize(vmin=float(np.nanmin(ov_arr)),
                                        vmax=float(np.nanmax(ov_arr)))
            cmap_o  = _get_cmap(self._overlay_cmap.currentText())
            ov_rgba = cmap_o(norm_o(ov_arr.filled(np.nan))).copy()
            ov_rgba[ov_arr.mask, 3] = 0.0
            ov_rgba[..., 3] *= alpha
            a_s  = ov_rgba[..., 3:4]
            a_d  = base_rgba[..., 3:4]
            a_o  = a_s + a_d * (1.0 - a_s)
            with np.errstate(invalid="ignore", divide="ignore"):
                rgb_o = (ov_rgba[..., :3] * a_s
                         + base_rgba[..., :3] * a_d * (1.0 - a_s))
                rgb_o = np.where(a_o > 0, rgb_o / np.maximum(a_o, 1e-8), 0.0)
            composite = np.clip(np.concatenate([rgb_o, a_o], axis=2), 0, 1)
        else:
            composite = base_rgba

        # ── Draw ─────────────────────────────────────────────────────────────
        reset = self._view_reset_pending
        if not reset:
            saved_xl = self._ax.get_xlim()
            saved_yl = self._ax.get_ylim()

        self._ax.clear()
        self._ax.set_facecolor(_AX_BG)
        self._ax.tick_params(colors=_FG, labelsize=8)
        for sp in self._ax.spines.values():
            sp.set_edgecolor(_GREY)

        if self._cbar is not None:
            try:
                self._cbar.remove()
            except Exception:
                pass
            self._cbar = None

        self._ax.imshow(composite, interpolation="nearest", aspect="equal")

        sm = mcm.ScalarMappable(cmap=cmap_b, norm=norm_b)
        sm.set_array([])
        self._cbar = self._fig.colorbar(sm, ax=self._ax, fraction=0.03, pad=0.02)
        self._cbar.ax.tick_params(colors=_FG, labelsize=8)
        unit = base.get("unit", "")
        if unit:
            self._cbar.set_label(unit, color=_FG, fontsize=9)

        self._ax.set_title(base_name, color=_FG, fontsize=10, pad=4)
        self._ax.set_xlabel("Column", color=_FG, fontsize=8)
        self._ax.set_ylabel("Row",    color=_FG, fontsize=8)

        if reset:
            self._view_reset_pending = False
        else:
            self._ax.set_xlim(saved_xl)
            self._ax.set_ylim(saved_yl)

        self._canvas.draw_idle()

        # Stats bar
        valid = base_arr.compressed()
        if len(valid):
            self._stats_lbl.setText(
                f"min {valid.min():.5g}   max {valid.max():.5g}   "
                f"mean {valid.mean():.5g}   {len(valid):,} valid pixels"
            )

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _show_placeholder(self) -> None:
        self._ax.clear()
        self._ax.set_facecolor(_AX_BG)
        self._ax.text(0.5, 0.5, "No raster loaded",
                      ha="center", va="center", color="#555",
                      fontsize=14, transform=self._ax.transAxes)
        for sp in self._ax.spines.values():
            sp.set_edgecolor("#333")
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        if self._cbar is not None:
            try:
                self._cbar.remove()
            except Exception:
                pass
            self._cbar = None
        self._canvas.draw_idle()

    def _show_error(self, msg: str) -> None:
        self._ax.clear()
        self._ax.set_facecolor(_AX_BG)
        self._ax.text(0.5, 0.5, msg, ha="center", va="center",
                      color="#e74c3c", fontsize=11, transform=self._ax.transAxes)
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._canvas.draw_idle()


# ── Module-level helpers ───────────────────────────────────────────────────────

def _mask(arr: np.ndarray, nodata) -> np.ma.MaskedArray:
    a = arr.copy().astype(float)
    m = ~np.isfinite(a)
    if nodata is not None:
        m |= a == nodata
    return np.ma.array(a, mask=m)


def _tool_btn(text: str, tooltip: str, checkable: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedSize(28, 24)
    btn.setToolTip(tooltip)
    btn.setObjectName("rasterToolBtn")
    btn.setCheckable(checkable)
    return btn


def _vsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet("color:#555; margin:4px 2px;")
    return f


def _lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("rasterToolLabel")
    return lbl
