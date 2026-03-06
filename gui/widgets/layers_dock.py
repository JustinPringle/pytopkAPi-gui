"""
gui/widgets/layers_dock.py
==========================
LayersDock — QGIS-style layers panel.

Shows all loaded project rasters and vector overlays in a grouped tree.
Clicking a raster layer emits raster_selected so MainWindow can display
it in the Raster tab.

Groups match the workflow step that produced the layers:
  DEM · Hydrology · Streams · Soil · Land Cover · Overlays · Subcatchments
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView, QDockWidget, QLabel, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
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

_GROUP_ORDER = ["DEM", "Hydrology", "Streams", "Soil", "Land Cover", "Overlays", "Subcatchments"]

_GROUP_COLOUR = "#9da5b0"
_LAYER_COLOUR = "#e8e8e8"
_VECTOR_COLOUR = "#c8e6c9"
_SUB_COLOUR    = "#ffe082"


class LayersDock(QDockWidget):
    """QGIS-style layers panel docked on the left side."""

    # Emitted when the user clicks a raster layer row
    raster_selected = pyqtSignal(str, str, str)  # display_name, file_path, cmap

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
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._tree.setIndentation(14)
        self._tree.setAnimated(True)
        self._tree.setUniformRowHeights(True)
        self._tree.setObjectName("layersTree")
        self._tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._tree, stretch=1)

        self._status = QLabel("  No layers loaded")
        self._status.setObjectName("layersStatus")
        layout.addWidget(self._status)

        self.setWidget(inner)
        self.setMinimumWidth(190)

        self._groups: dict[str, QTreeWidgetItem] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh_from_state(self, state) -> None:
        """Rebuild the tree from the current ProjectState."""
        self._tree.clear()
        self._groups.clear()

        raster_count = 0

        # ── Raster layers ──────────────────────────────────────────────────────
        for label, attr, cmap, group in _RASTER_DEFS:
            path = getattr(state, attr, None)
            if not path:
                continue
            raster_count += 1
            parent_item = self._group(group)
            child = QTreeWidgetItem(parent_item)
            child.setText(0, f"  {label}")
            child.setForeground(0, QColor(_LAYER_COLOUR))
            child.setToolTip(0, path)
            child.setData(0, Qt.ItemDataRole.UserRole,
                          {"type": "raster", "name": label, "path": path, "cmap": cmap})

        # ── Vector overlays ────────────────────────────────────────────────────
        overlay_names = getattr(state, "overlay_names", []) or []
        overlay_paths = getattr(state, "overlay_paths", []) or []
        for name, path in zip(overlay_names, overlay_paths):
            parent_item = self._group("Overlays")
            child = QTreeWidgetItem(parent_item)
            child.setText(0, f"  {name}")
            child.setForeground(0, QColor(_VECTOR_COLOUR))
            child.setToolTip(0, path)
            child.setData(0, Qt.ItemDataRole.UserRole,
                          {"type": "vector", "name": name, "path": path})

        # ── Subcatchments ──────────────────────────────────────────────────────
        outlets = getattr(state, "subcatchment_outlets", []) or []
        n_cells_list = getattr(state, "subcatchment_n_cells", []) or []
        for i, _ in enumerate(outlets):
            parent_item = self._group("Subcatchments")
            n = n_cells_list[i] if i < len(n_cells_list) else "?"
            child = QTreeWidgetItem(parent_item)
            child.setText(0, f"  Sub-catchment {i + 1}  ({n} cells)")
            child.setForeground(0, QColor(_SUB_COLOUR))
            child.setData(0, Qt.ItemDataRole.UserRole,
                          {"type": "subcatchment", "index": i})

        # Expand groups that have content; collapse empty ones
        for name, item in self._groups.items():
            item.setExpanded(item.childCount() > 0)

        total = raster_count + len(overlay_names) + len(outlets)
        if total == 0:
            self._status.setText("  No layers loaded")
        else:
            self._status.setText(
                f"  {raster_count} raster{'s' if raster_count != 1 else ''}  "
                f"· {len(overlay_names)} overlay{'s' if len(overlay_names) != 1 else ''}  "
                f"· {len(outlets)} sub-catchment{'s' if len(outlets) != 1 else ''}"
            )

    # ── Private ────────────────────────────────────────────────────────────────

    def _group(self, name: str) -> QTreeWidgetItem:
        """Return (creating if needed) the top-level group item for *name*."""
        if name not in self._groups:
            item = QTreeWidgetItem(self._tree)
            item.setText(0, name)
            item.setExpanded(False)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setForeground(0, QColor(_GROUP_COLOUR))
            f = QFont(item.font(0))
            f.setBold(True)
            item.setFont(0, f)
            self._groups[name] = item
        return self._groups[name]

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("type") == "raster":
            self.raster_selected.emit(data["name"], data["path"], data["cmap"])
