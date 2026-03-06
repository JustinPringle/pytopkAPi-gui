"""
gui/widgets/layers_dock.py
==========================
LayersDock — QGIS-style layers panel.

Each raster entry shows a small colourmap gradient swatch.
Right-click → "View in Raster Tab" or "Set as Overlay".
"""

from __future__ import annotations

import numpy as np

from PyQt6.QtCore import QSize, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QDockWidget, QLabel, QMenu,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


# (display_name, state_attr, matplotlib_cmap, group)
_RASTER_DEFS: list[tuple[str, str, str, str]] = [
    ("DEM (raw)",          "dem_path",          "terrain",   "DEM"),
    ("DEM (projected)",    "proj_dem_path",      "terrain",   "DEM"),
    ("DEM (filled)",       "filled_dem_path",    "terrain",   "DEM"),
    ("Hillshade",          "hillshade_path",     "gray",      "DEM"),
    ("Flow Direction",     "fdir_path",          "tab20b",    "Hydrology"),
    ("Flow Accumulation",  "accum_path",         "Blues",     "Hydrology"),
    ("Watershed Mask",     "mask_path",          "Greens",    "Hydrology"),
    ("Slope (°)",          "slope_path",         "YlOrRd",    "Hydrology"),
    ("Stream Network",     "streamnet_path",     "Blues",     "Streams"),
    ("Strahler Order",     "strahler_path",      "cool",      "Streams"),
    ("HWSD (clipped)",     "hwsd_clipped_path",  "tab20",     "Soil"),
    ("Soil Depth (m)",     "soil_depth_path",    "YlOrBr",    "Soil"),
    ("Ks (m/s)",           "hwsd_ks_path",       "viridis",   "Soil"),
    ("Theta saturated",    "hwsd_theta_path",    "Blues",     "Soil"),
    ("Theta residual",     "hwsd_theta_r_path",  "Purples",   "Soil"),
    ("Psi bubbling (cm)",  "hwsd_psi_b_path",    "YlOrBr",    "Soil"),
    ("Pore index",         "hwsd_pore_path",     "viridis",   "Soil"),
    ("Manning n_o",        "mannings_path",      "RdYlGn_r",  "Land Cover"),
]

_SWATCH_W = 28   # colourmap swatch width (px)
_SWATCH_H = 10   # colourmap swatch height (px)

_GROUP_FG  = "#9da5b0"
_LAYER_FG  = "#dde3ea"
_VECTOR_FG = "#c8e6c9"
_SUB_FG    = "#ffe082"


def _cmap_icon(name: str) -> QIcon:
    """Render a small horizontal gradient strip from a matplotlib colormap."""
    try:
        import matplotlib.cm as mcm
        cmap = mcm.get_cmap(name)
        xs   = np.linspace(0, 1, _SWATCH_W)
        rgba = (cmap(xs)[:, :3] * 255).astype(np.uint8)            # (W, 3)
        strip = np.tile(rgba, (_SWATCH_H, 1, 1))                    # (H, W, 3)

        # Build QPixmap via QImage (RGB888)
        img = QImage(strip.tobytes(), _SWATCH_W, _SWATCH_H,
                     _SWATCH_W * 3, QImage.Format.Format_RGB888)
        pm = QPixmap(_SWATCH_W + 4, _SWATCH_H + 4)
        pm.fill(QColor("transparent"))
        p = QPainter(pm)
        p.drawImage(2, 2, img)
        p.end()
        return QIcon(pm)
    except Exception:
        return QIcon()


# Cache icons so we don't re-render on every refresh
_ICON_CACHE: dict[str, QIcon] = {}


def _get_icon(cmap_name: str) -> QIcon:
    if cmap_name not in _ICON_CACHE:
        _ICON_CACHE[cmap_name] = _cmap_icon(cmap_name)
    return _ICON_CACHE[cmap_name]


class LayersDock(QDockWidget):
    """QGIS-style layers panel docked on the left side."""

    raster_selected         = pyqtSignal(str, str, str)         # name, path, cmap
    set_as_overlay          = pyqtSignal(str, str, str)         # name, path, cmap
    layer_visibility_changed = pyqtSignal(str, str, str, str, bool)  # name, path, cmap, type, visible

    def __init__(self, parent=None) -> None:
        super().__init__("Layers", parent)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea |
            Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable |
            QDockWidget.DockWidgetFeature.DockWidgetMovable
        )

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setIndentation(12)
        self._tree.setAnimated(True)
        self._tree.setObjectName("layersTree")
        self._tree.setIconSize(QSize(_SWATCH_W + 4, _SWATCH_H + 4))
        self._tree.itemClicked.connect(self._on_clicked)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._tree, stretch=1)

        self._status = QLabel("  No layers loaded")
        self._status.setObjectName("layersStatus")
        layout.addWidget(self._status)

        self.setWidget(inner)
        self.setMinimumWidth(200)

        self._groups: dict[str, QTreeWidgetItem] = {}
        self._suppress_changed = False   # block itemChanged during bulk refresh

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh_from_state(self, state) -> None:
        self._suppress_changed = True
        self._tree.clear()
        self._groups.clear()

        raster_count = 0

        for label, attr, cmap, group in _RASTER_DEFS:
            path = getattr(state, attr, None)
            if not path:
                continue
            raster_count += 1
            item = QTreeWidgetItem(self._group(group))
            item.setText(0, f"  {label}")
            item.setIcon(0, _get_icon(cmap))
            item.setForeground(0, QColor(_LAYER_FG))
            item.setToolTip(0, path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole,
                         {"type": "raster", "name": label, "path": path, "cmap": cmap})

        overlay_names = getattr(state, "overlay_names", []) or []
        overlay_paths = getattr(state, "overlay_paths", []) or []
        for name, path in zip(overlay_names, overlay_paths):
            item = QTreeWidgetItem(self._group("Overlays"))
            item.setText(0, f"  {name}")
            item.setForeground(0, QColor(_VECTOR_FG))
            item.setToolTip(0, path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            item.setData(0, Qt.ItemDataRole.UserRole,
                         {"type": "vector", "name": name, "path": path, "cmap": ""})

        outlets    = getattr(state, "subcatchment_outlets",  []) or []
        n_cells_l  = getattr(state, "subcatchment_n_cells",  []) or []
        for i in range(len(outlets)):
            n = n_cells_l[i] if i < len(n_cells_l) else "?"
            item = QTreeWidgetItem(self._group("Subcatchments"))
            item.setText(0, f"  Sub-catchment {i + 1}  ({n:,} cells)" if isinstance(n, int) else f"  Sub-catchment {i + 1}")
            item.setForeground(0, QColor(_SUB_FG))
            item.setData(0, Qt.ItemDataRole.UserRole,
                         {"type": "subcatchment", "index": i})

        for item in self._groups.values():
            item.setExpanded(item.childCount() > 0)

        self._suppress_changed = False

        n_ov  = len(overlay_names)
        n_sub = len(outlets)
        if raster_count + n_ov + n_sub == 0:
            self._status.setText("  No layers loaded")
        else:
            parts = []
            if raster_count:
                parts.append(f"{raster_count} raster{'s' if raster_count != 1 else ''}")
            if n_ov:
                parts.append(f"{n_ov} overlay{'s' if n_ov != 1 else ''}")
            if n_sub:
                parts.append(f"{n_sub} sub-catchment{'s' if n_sub != 1 else ''}")
            self._status.setText("  " + "  ·  ".join(parts))

    # ── Private ────────────────────────────────────────────────────────────────

    def _group(self, name: str) -> QTreeWidgetItem:
        if name not in self._groups:
            item = QTreeWidgetItem(self._tree)
            item.setText(0, name)
            item.setExpanded(False)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(0, QColor(_GROUP_FG))
            f = QFont(item.font(0))
            f.setBold(True)
            f.setPointSize(f.pointSize() - 1)
            item.setFont(0, f)
            self._groups[name] = item
        return self._groups[name]

    @pyqtSlot(QTreeWidgetItem, int)
    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if self._suppress_changed or col != 0:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") not in ("raster", "vector"):
            return
        visible = item.checkState(0) == Qt.CheckState.Checked
        self.layer_visibility_changed.emit(
            data["name"], data["path"], data.get("cmap", ""),
            data["type"], visible,
        )

    def _on_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "raster":
            self.raster_selected.emit(data["name"], data["path"], data["cmap"])

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") != "raster":
            return
        menu = QMenu(self._tree)
        view_act    = menu.addAction("View in Raster Tab")
        overlay_act = menu.addAction("Set as Overlay")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == view_act:
            self.raster_selected.emit(data["name"], data["path"], data["cmap"])
        elif action == overlay_act:
            self.set_as_overlay.emit(data["name"], data["path"], data["cmap"])
