"""
gui/widgets/layers_dock.py
==========================
LayersDock — QGIS-style layers panel.

Each raster entry shows a small colourmap gradient swatch.
Checked layers are overlaid on the Leaflet map.
Per-layer opacity slider appears when a layer is checked.
Right-click → "Overlay on Map".
"""

from __future__ import annotations

import numpy as np

from PyQt6.QtCore import QSize, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QDockWidget, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QMenu, QPushButton,
    QSlider, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)


# (display_name, state_attr, matplotlib_cmap, group, layer_type)
# layer_type: "raster" or "vector"
_LAYER_DEFS: list[tuple[str, str, str, str, str]] = [
    ("DEM (raw)",          "dem_path",           "terrain",   "DEM",        "raster"),
    ("DEM (projected)",    "proj_dem_path",      "terrain",   "DEM",        "raster"),
    ("DEM (filled)",       "filled_dem_path",    "terrain",   "DEM",        "raster"),
    ("Shaded Relief",      "shaded_relief_path", "",          "DEM",        "raster"),
    ("Flow Direction",     "fdir_path",          "tab20b",    "Hydrology",  "raster"),
    ("Flow Accumulation",  "accum_path",         "Blues",     "Hydrology",  "raster"),
    ("Watershed Mask",     "mask_path",          "Greens",    "Hydrology",  "raster"),
    ("Slope",              "slope_path",         "YlOrRd",    "Hydrology",  "raster"),
    ("Basins (raster)",    "basins_path",        "tab20",     "Hydrology",  "raster"),
    ("Basins (vector)",    "basins_gpkg_path",   "",          "Hydrology",  "vector"),
    ("Stream Network",     "streamnet_path",     "Blues",     "Streams",    "raster"),
    ("Strahler Order",     "strahler_path",      "cool",      "Streams",    "raster"),
    ("Streams (vector)",   "streams_gpkg_path",  "",          "Streams",    "vector"),
    ("HWSD (clipped)",     "hwsd_clipped_path",  "tab20",     "Soil",       "raster"),
    ("Soil Depth (m)",     "soil_depth_path",    "YlOrBr",    "Soil",       "raster"),
    ("Ks (m/s)",           "hwsd_ks_path",       "viridis",   "Soil",       "raster"),
    ("Theta saturated",    "hwsd_theta_path",    "Blues",     "Soil",       "raster"),
    ("Theta residual",     "hwsd_theta_r_path",  "Purples",   "Soil",       "raster"),
    ("Psi bubbling (cm)",  "hwsd_psi_b_path",    "YlOrBr",    "Soil",       "raster"),
    ("Pore index",         "hwsd_pore_path",     "viridis",   "Soil",       "raster"),
    ("Manning n_o",        "mannings_path",      "RdYlGn_r",  "Land Cover", "raster"),
]

_SWATCH_W = 28   # colourmap swatch width (px)
_SWATCH_H = 10   # colourmap swatch height (px)

_GROUP_FG  = "#9da5b0"
_LAYER_FG  = "#dde3ea"
_VECTOR_FG = "#c8e6c9"
_SUB_FG    = "#ffe082"

# Custom role for storing opacity slider widgets
_ROLE_OPACITY = Qt.ItemDataRole.UserRole + 1


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

    raster_selected          = pyqtSignal(str, str, str)              # name, path, cmap
    set_as_overlay           = pyqtSignal(str, str, str)              # name, path, cmap
    layer_visibility_changed = pyqtSignal(str, str, str, str, bool, str)  # name, path, cmap, type, visible, state_attr
    layer_opacity_changed    = pyqtSignal(str, float)                 # name, opacity (0.0–1.0)
    layer_limits_changed     = pyqtSignal(str, object, object)        # state_attr, vmin|None, vmax|None

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
        self.setMinimumWidth(220)

        self._groups: dict[str, QTreeWidgetItem] = {}
        self._suppress_changed = False   # block itemChanged during bulk refresh
        self._checked_layers: set[str] = set()   # layer names that are checked (preserved across refreshes)

    # ── Public API ─────────────────────────────────────────────────────────────

    def refresh_from_state(self, state) -> None:
        # Save which layers are currently checked before rebuilding
        self._save_checked_state()

        self._suppress_changed = True
        self._tree.clear()
        self._groups.clear()

        # Base map toggle (always present at top level)
        basemap_item = QTreeWidgetItem(self._tree)
        basemap_item.setText(0, "  Satellite Base Map")
        basemap_item.setForeground(0, QColor("#88b4e7"))
        basemap_item.setFlags(basemap_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        # Basemap defaults to checked; preserve unchecked if user toggled it off
        if "Satellite Base Map" in self._checked_layers or not self._checked_layers:
            basemap_item.setCheckState(0, Qt.CheckState.Checked)
        else:
            basemap_item.setCheckState(0, Qt.CheckState.Unchecked)
        basemap_item.setData(0, Qt.ItemDataRole.UserRole,
                             {"type": "basemap", "name": "Satellite Base Map"})

        raster_count = 0
        vector_count = 0

        for label, attr, cmap, group, ltype in _LAYER_DEFS:
            path = getattr(state, attr, None)
            if not path:
                continue
            if ltype == "raster":
                raster_count += 1
            else:
                vector_count += 1

            parent = self._group(group)
            item = QTreeWidgetItem(parent)
            item.setText(0, f"  {label}")
            if cmap:
                item.setIcon(0, _get_icon(cmap))
            item.setForeground(0, QColor(_VECTOR_FG if ltype == "vector" else _LAYER_FG))
            item.setToolTip(0, path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            was_checked = label in self._checked_layers
            item.setCheckState(
                0, Qt.CheckState.Checked if was_checked else Qt.CheckState.Unchecked
            )
            item.setData(0, Qt.ItemDataRole.UserRole,
                         {"type": ltype, "name": label, "path": path,
                          "cmap": cmap, "attr": attr})
            # Re-add opacity slider for restored checked layers
            if was_checked:
                self._add_opacity_slider(item)

        # User-loaded vector overlays
        overlay_names = getattr(state, "overlay_names", []) or []
        overlay_paths = getattr(state, "overlay_paths", []) or []
        for name, path in zip(overlay_names, overlay_paths):
            vector_count += 1
            item = QTreeWidgetItem(self._group("Overlays"))
            item.setText(0, f"  {name}")
            item.setForeground(0, QColor(_VECTOR_FG))
            item.setToolTip(0, path)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            was_checked = name in self._checked_layers
            item.setCheckState(
                0, Qt.CheckState.Checked if was_checked else Qt.CheckState.Unchecked
            )
            item.setData(0, Qt.ItemDataRole.UserRole,
                         {"type": "vector", "name": name, "path": path, "cmap": ""})
            if was_checked:
                self._add_opacity_slider(item)

        # Subcatchments
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
        total = raster_count + vector_count + n_ov
        if total + n_sub == 0:
            self._status.setText("  No layers loaded")
        else:
            parts = []
            if raster_count:
                parts.append(f"{raster_count} raster{'s' if raster_count != 1 else ''}")
            vt = vector_count + n_ov
            if vt:
                parts.append(f"{vt} vector{'s' if vt != 1 else ''}")
            if n_sub:
                parts.append(f"{n_sub} sub-catchment{'s' if n_sub != 1 else ''}")
            self._status.setText("  " + "  ·  ".join(parts))

    # ── Private ────────────────────────────────────────────────────────────────

    def _save_checked_state(self) -> None:
        """Scan the tree and remember which layer names are currently checked."""
        checked = set()
        for gi in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(gi)
            data = top.data(0, Qt.ItemDataRole.UserRole)
            if data and top.checkState(0) == Qt.CheckState.Checked:
                checked.add(data.get("name", ""))
            for ci in range(top.childCount()):
                child = top.child(ci)
                child_data = child.data(0, Qt.ItemDataRole.UserRole)
                if (child_data
                        and child_data.get("type") in ("raster", "vector", "basemap")
                        and child.checkState(0) == Qt.CheckState.Checked):
                    checked.add(child_data.get("name", ""))
        self._checked_layers = checked

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

    def _add_opacity_slider(self, item: QTreeWidgetItem) -> None:
        """Insert an opacity slider as a child item below the layer item."""
        # Don't add duplicates
        for ci in range(item.childCount()):
            child_data = item.child(ci).data(0, Qt.ItemDataRole.UserRole)
            if child_data and child_data.get("type") == "opacity_slider":
                return

        slider_item = QTreeWidgetItem(item)
        slider_item.setFlags(slider_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        slider_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "opacity_slider"})

        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(20, 1, 4, 1)
        layout.setSpacing(4)

        lbl = QLabel("Opacity")
        lbl.setStyleSheet("color:#888; font-size:10px;")
        lbl.setFixedWidth(42)
        layout.addWidget(lbl)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(70)
        slider.setFixedHeight(16)
        slider.setStyleSheet(
            "QSlider::groove:horizontal { height:4px; background:#444; border-radius:2px; }"
            "QSlider::handle:horizontal { width:10px; height:10px; margin:-3px 0; "
            "background:#aaa; border-radius:5px; }"
        )
        layout.addWidget(slider, stretch=1)

        pct_label = QLabel("70%")
        pct_label.setStyleSheet("color:#aaa; font-size:10px;")
        pct_label.setFixedWidth(28)
        layout.addWidget(pct_label)

        data = item.data(0, Qt.ItemDataRole.UserRole)
        layer_name = data.get("name", "") if data else ""

        def _on_slider(val):
            pct_label.setText(f"{val}%")
            self.layer_opacity_changed.emit(layer_name, val / 100.0)

        slider.valueChanged.connect(_on_slider)
        self._tree.setItemWidget(slider_item, 0, widget)
        item.setExpanded(True)

    def _remove_opacity_slider(self, item: QTreeWidgetItem) -> None:
        """Remove the opacity slider child from a layer item."""
        for ci in range(item.childCount()):
            child = item.child(ci)
            child_data = child.data(0, Qt.ItemDataRole.UserRole)
            if child_data and child_data.get("type") == "opacity_slider":
                item.removeChild(child)
                return

    @pyqtSlot(QTreeWidgetItem, int)
    def _on_item_changed(self, item: QTreeWidgetItem, col: int) -> None:
        if self._suppress_changed or col != 0:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        visible = item.checkState(0) == Qt.CheckState.Checked
        ltype = data.get("type", "")
        layer_name = data.get("name", "")

        # Track checked state for preservation across refreshes
        if visible:
            self._checked_layers.add(layer_name)
        else:
            self._checked_layers.discard(layer_name)

        if ltype == "basemap":
            self.layer_visibility_changed.emit(
                data["name"], "", "", "basemap", visible, "",
            )
        elif ltype in ("raster", "vector"):
            self.layer_visibility_changed.emit(
                data["name"], data["path"], data.get("cmap", ""),
                ltype, visible, data.get("attr", ""),
            )
            # Show / hide opacity slider
            if visible:
                self._add_opacity_slider(item)
            else:
                self._remove_opacity_slider(item)

    def _on_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        # Only emit raster_selected when the item is checked — prevents re-showing
        # a raster that was just unchecked (itemClicked fires after itemChanged).
        if (data and data.get("type") == "raster"
                and item.checkState(0) == Qt.CheckState.Checked):
            self.raster_selected.emit(data["name"], data["path"], data["cmap"])

    def _context_menu(self, pos) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") not in ("raster", "vector"):
            return
        menu = QMenu(self._tree)
        overlay_act = menu.addAction("Overlay on Map")
        limits_act = None
        if data.get("type") == "raster" and data.get("attr"):
            limits_act = menu.addAction("Set colour limits…")
        action = menu.exec(self._tree.viewport().mapToGlobal(pos))
        if action == overlay_act:
            self.set_as_overlay.emit(
                data["name"], data["path"], data.get("cmap", "")
            )
        elif limits_act and action == limits_act:
            self._open_limits_dialog(data)

    def _open_limits_dialog(self, data: dict) -> None:
        """Open the LayerLimitsDialog for a raster layer."""
        attr = data.get("attr", "")
        if not attr:
            return
        dlg = LayerLimitsDialog(data["name"], attr, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            vmin, vmax = dlg.get_limits()
            self.layer_limits_changed.emit(attr, vmin, vmax)


# ── Colour limits dialog ────────────────────────────────────────────────────

class LayerLimitsDialog(QDialog):
    """Dialog for setting/resetting vmin/vmax colour stretch limits.

    When a checkbox is unchecked the corresponding limit is disabled (None),
    falling back to the automatic 2%–98% percentile stretch.
    """

    _DARK_STYLE = """
        QDialog { background: #252729; color: #d4d4d4; }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #3a3d40;
            border-radius: 4px;
            margin-top: 12px;
            padding-top: 16px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 4px;
            color: #cccccc;
        }
        QPushButton {
            background: #3c3f41; color: #d4d4d4;
            border: 1px solid #3a3d40; border-radius: 4px;
            padding: 6px 12px;
        }
        QPushButton:hover { background: #4e5254; color: #ffffff; }
        QPushButton[primary="true"] {
            background: #1a6fc4; border-color: #1a6fc4; color: #ffffff;
        }
        QPushButton[primary="true"]:hover { background: #2080d4; }
        QDoubleSpinBox, QCheckBox { background: #1e1e1e; color: #d4d4d4;
            border: 1px solid #3a3d40; border-radius: 3px; padding: 4px; }
        QLabel { color: #d4d4d4; }
    """

    def __init__(self, layer_name: str, state_attr: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Colour Limits — {layer_name}")
        self.setMinimumWidth(320)
        self.setStyleSheet(self._DARK_STYLE)

        layout = QVBoxLayout(self)

        hint = QLabel(
            "Set explicit minimum / maximum values for the colour stretch.\n"
            "Uncheck to use the automatic 2%–98% percentile."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#aaa; font-size:11px; padding-bottom:6px;")
        layout.addWidget(hint)

        grp = QGroupBox("Colour stretch limits")
        form = QFormLayout(grp)
        form.setSpacing(8)

        # vmin row
        self._vmin_cb = QCheckBox("Enable")
        self._vmin_cb.setChecked(False)
        self._vmin_spin = QDoubleSpinBox()
        self._vmin_spin.setRange(-1e9, 1e9)
        self._vmin_spin.setDecimals(4)
        self._vmin_spin.setValue(0.0)
        self._vmin_spin.setEnabled(False)
        self._vmin_cb.toggled.connect(self._vmin_spin.setEnabled)
        vmin_row = QWidget()
        vmin_layout = QHBoxLayout(vmin_row)
        vmin_layout.setContentsMargins(0, 0, 0, 0)
        vmin_layout.addWidget(self._vmin_cb)
        vmin_layout.addWidget(self._vmin_spin, stretch=1)
        form.addRow("Minimum (vmin):", vmin_row)

        # vmax row
        self._vmax_cb = QCheckBox("Enable")
        self._vmax_cb.setChecked(False)
        self._vmax_spin = QDoubleSpinBox()
        self._vmax_spin.setRange(-1e9, 1e9)
        self._vmax_spin.setDecimals(4)
        self._vmax_spin.setValue(1.0)
        self._vmax_spin.setEnabled(False)
        self._vmax_cb.toggled.connect(self._vmax_spin.setEnabled)
        vmax_row = QWidget()
        vmax_layout = QHBoxLayout(vmax_row)
        vmax_layout.setContentsMargins(0, 0, 0, 0)
        vmax_layout.addWidget(self._vmax_cb)
        vmax_layout.addWidget(self._vmax_spin, stretch=1)
        form.addRow("Maximum (vmax):", vmax_row)

        layout.addWidget(grp)

        # Reset button (clears both limits)
        reset_btn = QPushButton("Reset to Auto")
        reset_btn.setToolTip("Clear both limits — revert to automatic 2%–98% stretch")
        reset_btn.clicked.connect(self._reset)
        layout.addWidget(reset_btn)

        # OK / Cancel
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setProperty("primary", True)
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _reset(self) -> None:
        """Uncheck both checkboxes (auto stretch on OK)."""
        self._vmin_cb.setChecked(False)
        self._vmax_cb.setChecked(False)

    def get_limits(self) -> tuple:
        """Return (vmin, vmax) — None where the corresponding checkbox is off."""
        vmin = self._vmin_spin.value() if self._vmin_cb.isChecked() else None
        vmax = self._vmax_spin.value() if self._vmax_cb.isChecked() else None
        return vmin, vmax
