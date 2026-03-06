"""
gui/widgets/gis_canvas.py
=========================
GISCanvas — unified georeferenced map canvas.

Renders any combination of:
  • Raster layers  (GeoTIFF) — imshow with rasterio bounds as extent
  • Vector layers  (Shapefile / GeoJSON string) — geopandas plot

All layers share the same CRS (set from the first raster added).
Vectors are reprojected automatically.

Scroll-wheel zoom, pan-mode drag, +/− /Reset buttons — same as the
old RasterCanvas but coordinate-aware.

Public API
----------
set_project_crs(crs_str)
    Call once with state.crs so vectors are reprojected correctly.
add_raster(name, path, cmap, alpha, zorder)
    Load a GeoTIFF and add it as a named layer (no-op if already loaded).
add_vector(name, source, color, linewidth, alpha, zorder)
    Load a shapefile path or a GeoJSON dict/string as a named layer.
show_layer(name) / hide_layer(name)
    Toggle visibility and re-render.
remove_layer(name)
    Delete a layer from the canvas.
clear()
    Remove all layers.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib.cm as mcm
import matplotlib.colors as mcolors
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

_FIG_BG = "#2b2b2b"
_AX_BG  = "#1e1e1e"
_FG     = "#e8e8e8"
_GREY   = "#555"

# Rasters downsample to this many pixels max (for display performance)
_MAX_PX = 1024

# Default colours for vector layers
_VECTOR_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12",
    "#9b59b6", "#1abc9c", "#e67e22", "#34495e",
]


def _get_cmap(name: str):
    try:
        return mcm.get_cmap(name)
    except Exception:
        return mcm.get_cmap("viridis")


class GISCanvas(QWidget):
    """Unified georeferenced raster + vector map viewer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layers: dict[str, dict] = {}   # name → layer spec dict
        self._crs_str: str | None = None      # project CRS (from first raster or set explicitly)
        self._pan_ref: tuple | None = None
        self._view_reset_pending = True
        self._vec_colour_idx = 0
        self._build_ui()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = QWidget()
        tb.setFixedHeight(32)
        tb.setObjectName("gisToolbar")
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(6, 2, 6, 2)
        tbl.setSpacing(4)

        self._btn_zoom_in  = _tb_btn("+",   "Zoom in  (or scroll up)")
        self._btn_zoom_out = _tb_btn("−",   "Zoom out (or scroll down)")
        self._btn_pan      = _tb_btn("✥",   "Pan — drag to move view", checkable=True)
        self._btn_reset    = _tb_btn("[ ]", "Reset view to full extent")
        for b in (self._btn_zoom_in, self._btn_zoom_out, self._btn_pan, self._btn_reset):
            tbl.addWidget(b)

        tbl.addWidget(_vsep())

        self._crs_label = QLabel("No layers")
        self._crs_label.setObjectName("gisCrsLabel")
        tbl.addWidget(self._crs_label)

        tbl.addStretch()

        self._pixel_label = QLabel("")
        self._pixel_label.setObjectName("gisPixelLabel")
        tbl.addWidget(self._pixel_label)

        root.addWidget(tb)

        # ── Figure ────────────────────────────────────────────────────────────
        self._fig = Figure(facecolor=_FIG_BG)
        self._fig.subplots_adjust(left=0.08, right=0.97, top=0.97, bottom=0.06)
        self._ax  = self._fig.add_subplot(111)
        self._ax.set_facecolor(_AX_BG)
        self._ax.tick_params(colors=_FG, labelsize=7)
        for sp in self._ax.spines.values():
            sp.set_edgecolor(_GREY)

        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        root.addWidget(self._canvas, stretch=1)

        # ── Signal connections ────────────────────────────────────────────────
        self._btn_zoom_in.clicked.connect(lambda: self._zoom(0.75))
        self._btn_zoom_out.clicked.connect(lambda: self._zoom(1.33))
        self._btn_pan.toggled.connect(
            lambda c: self._canvas.setCursor(
                Qt.CursorShape.OpenHandCursor if c else Qt.CursorShape.ArrowCursor
            )
        )
        self._btn_reset.clicked.connect(self._reset_view)

        self._canvas.mpl_connect("scroll_event",         self._on_scroll)
        self._canvas.mpl_connect("button_press_event",   self._on_press)
        self._canvas.mpl_connect("button_release_event", lambda e: setattr(self, "_pan_ref", None))
        self._canvas.mpl_connect("motion_notify_event",  self._on_motion)

        self._show_placeholder()

    # ── Public API ─────────────────────────────────────────────────────────────

    def set_project_crs(self, crs_str: str) -> None:
        """Set the reference CRS for vector reprojection."""
        self._crs_str = crs_str

    def add_raster(
        self,
        name: str,
        path: str,
        cmap: str = "terrain",
        alpha: float = 1.0,
        zorder: int = 0,
    ) -> None:
        """Load a GeoTIFF and register it. No-op if already loaded."""
        if name in self._layers:
            self._layers[name]["visible"] = True
            self._rerender()
            return
        try:
            import rasterio
            from rasterio.enums import Resampling
            with rasterio.open(path) as src:
                factor = max(1, max(src.width, src.height) // _MAX_PX)
                arr = src.read(
                    1,
                    out_shape=(max(1, src.height // factor),
                               max(1, src.width  // factor)),
                    resampling=Resampling.average,
                ).astype(float)
                nd  = src.nodata
                bounds = src.bounds   # BoundingBox(left, bottom, right, top)
                if self._crs_str is None and src.crs:
                    self._crs_str = src.crs.to_string()
        except Exception as exc:
            self._log(f"[GISCanvas] Cannot load {name}: {exc}")
            return

        mask = ~np.isfinite(arr)
        if nd is not None:
            mask |= arr == nd
        arr_m = np.ma.array(arr, mask=mask)

        # matplotlib extent: [left, right, bottom, top]
        extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]

        self._layers[name] = {
            "type": "raster", "path": path, "visible": True,
            "alpha": alpha, "cmap": cmap, "zorder": zorder,
            "arr": arr_m, "extent": extent,
        }
        self._view_reset_pending = True
        self._rerender()
        self._update_crs_label()

    def add_vector(
        self,
        name: str,
        source,                      # file path (str) or GeoJSON dict/str
        color: str | None = None,
        linewidth: float = 1.5,
        alpha: float = 0.85,
        zorder: int = 10,
    ) -> None:
        """Load a shapefile / GeoJSON and register it. No-op if already loaded."""
        if name in self._layers:
            self._layers[name]["visible"] = True
            self._rerender()
            return
        try:
            import geopandas as gpd
            if isinstance(source, (dict, str)) and not Path(str(source)).exists():
                # GeoJSON string or dict
                gdf = gpd.GeoDataFrame.from_features(
                    (source if isinstance(source, dict)
                     else json.loads(source))["features"],
                    crs="EPSG:4326",
                )
            else:
                gdf = gpd.read_file(str(source))

            if gdf.empty:
                return

            # Reproject to canvas CRS
            if self._crs_str and gdf.crs and gdf.crs.to_string() != self._crs_str:
                gdf = gdf.to_crs(self._crs_str)
            elif self._crs_str and gdf.crs is None:
                gdf = gdf.set_crs(self._crs_str)
        except Exception as exc:
            self._log(f"[GISCanvas] Cannot load vector {name}: {exc}")
            return

        if color is None:
            color = _VECTOR_PALETTE[self._vec_colour_idx % len(_VECTOR_PALETTE)]
            self._vec_colour_idx += 1

        self._layers[name] = {
            "type": "vector", "visible": True,
            "alpha": alpha, "color": color, "linewidth": linewidth,
            "zorder": zorder, "gdf": gdf,
        }
        self._rerender()

    def show_layer(self, name: str) -> None:
        if name in self._layers:
            self._layers[name]["visible"] = True
            self._rerender()

    def hide_layer(self, name: str) -> None:
        if name in self._layers:
            self._layers[name]["visible"] = False
            self._rerender()

    def remove_layer(self, name: str) -> None:
        self._layers.pop(name, None)
        self._view_reset_pending = True
        self._rerender()
        self._update_crs_label()

    def clear(self) -> None:
        self._layers.clear()
        self._view_reset_pending = True
        self._vec_colour_idx = 0
        self._show_placeholder()
        self._update_crs_label()

    def has_layer(self, name: str) -> bool:
        return name in self._layers

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

    def _on_scroll(self, event) -> None:
        if event.inaxes is None:
            return
        factor = 0.8 if event.button == "up" else 1.25
        cx, cy = event.xdata, event.ydata
        xl, yl = self._ax.get_xlim(), self._ax.get_ylim()
        self._ax.set_xlim(cx - (cx - xl[0]) * factor, cx + (xl[1] - cx) * factor)
        self._ax.set_ylim(cy - (cy - yl[0]) * factor, cy + (yl[1] - cy) * factor)
        self._canvas.draw_idle()

    def _on_press(self, event) -> None:
        if event.inaxes and self._btn_pan.isChecked() and event.button == 1:
            self._pan_ref = (event.xdata, event.ydata,
                             self._ax.get_xlim(), self._ax.get_ylim())

    def _on_motion(self, event) -> None:
        if event.inaxes is None:
            return
        if self._pan_ref and event.button == 1:
            x0, y0, xl, yl = self._pan_ref
            dx, dy = event.xdata - x0, event.ydata - y0
            self._ax.set_xlim(xl[0] - dx, xl[1] - dx)
            self._ax.set_ylim(yl[0] - dy, yl[1] - dy)
            self._canvas.draw_idle()
        # Coordinate readout
        self._pixel_label.setText(f"X: {event.xdata:.1f}   Y: {event.ydata:.1f}")

    # ── Rendering ──────────────────────────────────────────────────────────────

    def _rerender(self) -> None:
        visible = [v for v in self._layers.values() if v["visible"]]
        if not visible:
            self._show_placeholder()
            return

        reset = self._view_reset_pending
        if not reset:
            saved_xl = self._ax.get_xlim()
            saved_yl = self._ax.get_ylim()

        self._ax.clear()
        self._ax.set_facecolor(_AX_BG)
        self._ax.tick_params(colors=_FG, labelsize=7)
        for sp in self._ax.spines.values():
            sp.set_edgecolor(_GREY)
        self._ax.set_xlabel("Easting (m)", color=_FG, fontsize=8)
        self._ax.set_ylabel("Northing (m)", color=_FG, fontsize=8)

        # Sort by zorder
        ordered = sorted(visible, key=lambda v: v.get("zorder", 0))

        for layer in ordered:
            if layer["type"] == "raster":
                self._draw_raster(layer)
            else:
                self._draw_vector(layer)

        if reset:
            self._view_reset_pending = False
        else:
            self._ax.set_xlim(saved_xl)
            self._ax.set_ylim(saved_yl)

        self._fig.tight_layout(pad=0.4)
        self._canvas.draw_idle()

    def _draw_raster(self, layer: dict) -> None:
        arr  = layer["arr"]
        cmap = _get_cmap(layer["cmap"])
        norm = mcolors.Normalize(vmin=float(np.nanmin(arr)),
                                 vmax=float(np.nanmax(arr)))

        # Special handling for binary masks: transparent outside, coloured inside
        if layer.get("cmap") in ("Greens", "Greens_r") and arr.max() <= 1:
            rgba = cmap(norm(arr.filled(np.nan))).copy()
            rgba[arr.mask, 3] = 0.0
        else:
            rgba = cmap(norm(arr.filled(np.nan))).copy()
            rgba[arr.mask, 3] = 0.0

        self._ax.imshow(
            rgba,
            extent=layer["extent"],   # [left, right, bottom, top]
            origin="upper",
            aspect="equal",
            alpha=layer["alpha"],
            zorder=layer.get("zorder", 0),
        )

    def _draw_vector(self, layer: dict) -> None:
        gdf   = layer["gdf"]
        color = layer["color"]
        alpha = layer["alpha"]
        lw    = layer["linewidth"]
        zo    = layer.get("zorder", 10)

        geom_type = gdf.geometry.geom_type.iloc[0] if not gdf.empty else "Unknown"
        if "Point" in geom_type:
            gdf.plot(ax=self._ax, color=color, alpha=alpha,
                     markersize=6, zorder=zo)
        elif "Line" in geom_type:
            gdf.plot(ax=self._ax, color=color, alpha=alpha,
                     linewidth=lw, zorder=zo)
        else:  # Polygon
            gdf.plot(ax=self._ax, facecolor="none", edgecolor=color,
                     alpha=alpha, linewidth=lw, zorder=zo)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _show_placeholder(self) -> None:
        self._ax.clear()
        self._ax.set_facecolor(_AX_BG)
        self._ax.text(
            0.5, 0.5,
            "Check layers in the Layers panel\nto display them here.",
            ha="center", va="center", color="#555",
            fontsize=13, linespacing=1.8, transform=self._ax.transAxes,
        )
        for sp in self._ax.spines.values():
            sp.set_edgecolor("#333")
        self._ax.set_xticks([])
        self._ax.set_yticks([])
        self._canvas.draw_idle()

    def _update_crs_label(self) -> None:
        rasters = [v for v in self._layers.values() if v["type"] == "raster"]
        if not rasters and not self._layers:
            self._crs_label.setText("No layers")
        elif self._crs_str:
            n = len([v for v in self._layers.values() if v["visible"]])
            self._crs_label.setText(f"{self._crs_str}   ·   {n} layer{'s' if n != 1 else ''} visible")
        else:
            self._crs_label.setText("")

    @staticmethod
    def _log(msg: str) -> None:
        print(msg)


# ── Module helpers ────────────────────────────────────────────────────────────

def _tb_btn(text: str, tooltip: str, checkable: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setFixedSize(28, 24)
    btn.setToolTip(tooltip)
    btn.setObjectName("gisToolBtn")
    btn.setCheckable(checkable)
    return btn


def _vsep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setStyleSheet("color:#555; margin:4px 2px;")
    return f
