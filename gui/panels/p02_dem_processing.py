"""
gui/panels/p02_dem_processing.py
=================================
Step 2 — DEM Processing
  A. Load Existing Rasters   — skip GRASS if you already have them
  B. Reproject DEM           — gdalwarp via DemWorker
  C. GRASS Hydrological      — r.fill.dir + r.watershed via FillWorker
  D. Map Overlays            — load shapefiles/GeoJSON for visual reference
  E. Subcatchments           — click outlets → GRASS r.water.outlet per sub-basin
                               then clip the DEM to a selected sub-basin

Central widget: MapWidget (Folium) — replaces RasterCanvas so the engineer
can zoom, pan, and see overlays interactively.
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.map_widget import MapWidget
from gui.workers.clip_worker import ClipWorker
from gui.workers.dem_worker import DemWorker
from gui.workers.fill_worker import FillWorker
from gui.workers.shapefile_worker import ShapefileWorker
from gui.workers.subcatchment_worker import SubcatchmentWorker


class DEMProcessingPanel(BasePanel):
    """Panel for Step 2: reproject + GRASS fill + flow routing + overlays + subcatchments."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._map_widget: MapWidget | None = None
        self._raster_canvas = None               # RasterCanvas, created lazily
        self._waiting_for_outlet: bool = False   # True while user must click map

    # ──────────────────────────────────────────────────────────────────────────
    # BasePanel interface
    # ──────────────────────────────────────────────────────────────────────────

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 2 — DEM Processing")
        title.setProperty("role", "title")
        layout.addWidget(title)

        layout.addWidget(self._build_section_a())
        layout.addWidget(self._build_section_b())
        layout.addWidget(self._build_section_c())
        layout.addWidget(self._build_section_d())
        layout.addWidget(self._build_section_e())
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        """Populate both the Map tab and the Raster tab when Step 2 is activated."""
        self._ensure_map_widget()
        self._mw.set_map_widget(self._map_widget)
        self._ensure_raster_canvas()
        self._mw.set_raster_widget(self._raster_canvas)
        self._mw.show_map_tab()
        self._rebuild_map()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # ── B: Reproject status ────────────────────────────────────────────
        if s.proj_dem_path and os.path.exists(s.proj_dem_path):
            self._reproj_status.setText(f"✅ {os.path.basename(s.proj_dem_path)}")
            self._reproj_status.setStyleSheet("color:#2ecc71; font-size:11px;")
            self._grass_btn.setEnabled(True)
        elif s.dem_path and os.path.exists(s.dem_path):
            self._reproj_status.setText(
                f"Raw DEM ready: {os.path.basename(s.dem_path)}\n"
                "Click 'Reproject DEM' to convert to project CRS."
            )
            self._reproj_status.setStyleSheet("color:#dcdcaa; font-size:11px;")
            self._grass_btn.setEnabled(bool(s.filled_dem_path))
        else:
            self._reproj_status.setText(
                "No DEM found. Download one in Step 1, or load an existing DEM above."
            )
            self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
            self._grass_btn.setEnabled(bool(s.filled_dem_path))

        # ── C: GRASS output labels ─────────────────────────────────────────
        def _lbl(path, name, widget):
            if path and os.path.exists(path):
                widget.setText(f"{name}  ✅ {os.path.basename(path)}")
                widget.setStyleSheet("font-size:11px; color:#2ecc71;")
            else:
                widget.setText(f"{name}  —")
                widget.setStyleSheet("font-size:11px; color:#aaa;")

        _lbl(s.filled_dem_path, "Filled DEM:      ", self._grass_filled_lbl)
        _lbl(s.fdir_path,       "Flow direction:  ", self._grass_fdir_lbl)
        _lbl(s.accum_path,      "Accumulation:    ", self._grass_accum_lbl)
        _lbl(s.drain_ws_path,   "Drainage (ws):   ", self._grass_drain_lbl)

        # ── C: Hillshade button + status ───────────────────────────────────
        dem_available = bool(
            (s.filled_dem_path and os.path.exists(s.filled_dem_path)) or
            (s.proj_dem_path   and os.path.exists(s.proj_dem_path))
        )
        self._hillshade_btn.setEnabled(dem_available)
        if s.hillshade_path and os.path.exists(s.hillshade_path):
            self._hillshade_status.setText(f"✅ {os.path.basename(s.hillshade_path)}")
            self._hillshade_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._hillshade_status.setText(
                "Not yet generated — click the button above to create."
                if dem_available else "Not yet generated — load a DEM first."
            )
            self._hillshade_status.setStyleSheet("color:#aaa; font-size:11px;")

        # ── D: Overlay list ────────────────────────────────────────────────
        self._refresh_overlay_list()

        # ── E: Subcatchment list ───────────────────────────────────────────
        self._refresh_subcatch_list()

        # ── E: Clip status ─────────────────────────────────────────────────
        if s.clipped_dem_path and os.path.exists(s.clipped_dem_path):
            self._clip_status.setText(
                f"✅ {os.path.basename(s.clipped_dem_path)}"
            )
            self._clip_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._clip_status.setText("No clip generated yet.")
            self._clip_status.setStyleSheet("color:#aaa; font-size:11px;")

        # ── Subcatchment button guard ──────────────────────────────────────
        grass_done = bool(s.filled_dem_path and s.drain_ws_path)
        self._add_outlet_btn.setEnabled(grass_done and not self._waiting_for_outlet)

        # Rebuild map whenever state changes (overlays / subcatchments updated)
        if self._map_widget is not None:
            self._rebuild_map()

        # Refresh raster canvas with any newly available rasters
        if self._raster_canvas is not None:
            self._load_rasters_into_canvas()

    # ──────────────────────────────────────────────────────────────────────────
    # Section builders
    # ──────────────────────────────────────────────────────────────────────────

    def _build_section_a(self) -> QGroupBox:
        box = QGroupBox("A — Load Existing Rasters  (skip processing)")
        form = QFormLayout(box)
        form.setSpacing(6)

        hint = QLabel(
            "Already have GRASS-processed rasters? Load them here and skip B and C."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self._load_dem_btn = QPushButton("Browse…  Filled / Projected DEM")
        self._load_dem_btn.clicked.connect(self._load_dem)
        form.addRow("DEM:", self._load_dem_btn)

        self._load_fdir_btn = QPushButton("Browse…  Flow Direction  (GRASS 1-8)")
        self._load_fdir_btn.clicked.connect(self._load_fdir)
        form.addRow("Flow dir:", self._load_fdir_btn)

        self._load_accum_btn = QPushButton("Browse…  Flow Accumulation")
        self._load_accum_btn.clicked.connect(self._load_accum)
        form.addRow("Accum:", self._load_accum_btn)

        return box

    def _build_section_b(self) -> QGroupBox:
        box = QGroupBox("B — Reproject DEM  (gdalwarp)")
        form = QFormLayout(box)
        form.setSpacing(8)

        self._reproj_status = QLabel("Not yet reprojected.")
        self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._reproj_status.setWordWrap(True)
        form.addRow("Status:", self._reproj_status)

        self._reproj_btn = QPushButton("Reproject DEM →  project CRS")
        self._reproj_btn.setProperty("primary", "true")
        self._reproj_btn.clicked.connect(self._reproject)
        form.addRow("", self._reproj_btn)

        return box

    def _build_section_c(self) -> QGroupBox:
        box = QGroupBox("C — GRASS Hydrological Processing  (r.fill.dir + r.watershed)")
        form = QFormLayout(box)
        form.setSpacing(8)

        grass_hint = QLabel(
            "Runs a single GRASS session:\n"
            "  • r.fill.dir  — fills depressions, writes flow direction "
            "(GRASS 1-8 natively)\n"
            "  • r.watershed — D8 accumulation + drainage direction "
            "(needed for subcatchment delineation)"
        )
        grass_hint.setStyleSheet("color:#aaa; font-size:11px;")
        grass_hint.setWordWrap(True)
        form.addRow("", grass_hint)

        self._grass_filled_lbl = QLabel("Filled DEM:      —")
        self._grass_filled_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("", self._grass_filled_lbl)

        self._grass_fdir_lbl = QLabel("Flow direction:  —")
        self._grass_fdir_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("", self._grass_fdir_lbl)

        self._grass_accum_lbl = QLabel("Accumulation:    —")
        self._grass_accum_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("", self._grass_accum_lbl)

        self._grass_drain_lbl = QLabel("Drainage (ws):   —")
        self._grass_drain_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("", self._grass_drain_lbl)

        self._grass_btn = QPushButton(
            "Fill + Flow Direction + Accumulation  (GRASS)"
        )
        self._grass_btn.setProperty("primary", "true")
        self._grass_btn.setEnabled(False)
        self._grass_btn.clicked.connect(self._run_grass)
        form.addRow("", self._grass_btn)

        form.addRow(QLabel(""))   # spacer

        self._hillshade_btn = QPushButton("⛰  Generate Hillshade  (gdaldem)")
        self._hillshade_btn.setProperty("primary", "true")
        self._hillshade_btn.setEnabled(False)
        self._hillshade_btn.setToolTip(
            "Creates a shaded-relief image from the filled (or projected) DEM.\n"
            "The result is shown in the Raster tab."
        )
        self._hillshade_btn.clicked.connect(self._generate_hillshade)
        form.addRow("", self._hillshade_btn)

        self._hillshade_status = QLabel("Not yet generated.")
        self._hillshade_status.setStyleSheet("color:#aaa; font-size:11px;")
        form.addRow("Hillshade:", self._hillshade_status)

        return box

    def _build_section_d(self) -> QGroupBox:
        """D — Map Overlays: load vector files for reference."""
        box = QGroupBox("D — Map Overlays  (rivers, boundaries, gauges)")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        hint = QLabel(
            "Load shapefiles or GeoJSON files to overlay on the map — useful for "
            "locating stream gauges, identifying rivers, or checking catchment boundaries."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        self._load_shp_btn = QPushButton("📂  Load Shapefile…")
        self._load_shp_btn.setToolTip(
            "Supported: .shp, .geojson, .json, .gpkg, .kml"
        )
        self._load_shp_btn.clicked.connect(self._load_shapefile)
        row.addWidget(self._load_shp_btn)

        self._clear_layers_btn = QPushButton("✕  Clear All")
        self._clear_layers_btn.setToolTip("Remove all overlay layers from the map")
        self._clear_layers_btn.clicked.connect(self._clear_layers)
        row.addWidget(self._clear_layers_btn)
        row.addStretch()
        layout.addLayout(row)

        self._overlay_list = QListWidget()
        self._overlay_list.setMaximumHeight(90)
        self._overlay_list.setToolTip("Loaded overlay layers. Click × to remove.")
        layout.addWidget(self._overlay_list)

        return box

    def _build_section_e(self) -> QGroupBox:
        """E — Subcatchments: click outlets → delineate, then clip."""
        box = QGroupBox("E — Subcatchments  (auto-delineated from outlet clicks)")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        hint = QLabel(
            "Requires: GRASS processing (section C) to be complete first.\n"
            "Click 'Add Outlet on Map', then click a point on the river in the map. "
            "GRASS will delineate the upstream catchment automatically. "
            "Repeat for multiple sub-basins."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._add_outlet_btn = QPushButton("📍  Add Outlet on Map")
        self._add_outlet_btn.setEnabled(False)
        self._add_outlet_btn.setToolTip(
            "Click, then place a marker on the river in the map above. "
            "GRASS will delineate the upstream catchment."
        )
        self._add_outlet_btn.clicked.connect(self._toggle_outlet_capture)
        layout.addWidget(self._add_outlet_btn)

        self._subcatch_list = QListWidget()
        self._subcatch_list.setMaximumHeight(100)
        self._subcatch_list.setToolTip(
            "Delineated sub-basins. Select one, then click 'Clip DEM'."
        )
        layout.addWidget(self._subcatch_list)

        clip_row = QHBoxLayout()
        self._clip_btn = QPushButton("✂  Clip DEM to Selected")
        self._clip_btn.setProperty("primary", "true")
        self._clip_btn.setEnabled(False)
        self._clip_btn.setToolTip(
            "Clips the DEM and creates a binary mask (1=cell, 255=nodata) "
            "for the selected sub-basin."
        )
        self._clip_btn.clicked.connect(self._clip_dem)
        clip_row.addWidget(self._clip_btn)
        clip_row.addStretch()
        layout.addLayout(clip_row)

        self._clip_status = QLabel("No clip generated yet.")
        self._clip_status.setStyleSheet("color:#aaa; font-size:11px;")
        layout.addWidget(self._clip_status)

        # Enable/disable clip button based on selection
        self._subcatch_list.itemSelectionChanged.connect(self._on_subcatch_selection)

        return box

    # ──────────────────────────────────────────────────────────────────────────
    # Map widget
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_map_widget(self) -> None:
        if self._map_widget is not None:
            return
        self._map_widget = MapWidget()
        self._map_widget.outlet_placed.connect(self._on_outlet_placed)

    # ── Raster canvas helpers ──────────────────────────────────────────────────

    def _ensure_raster_canvas(self) -> None:
        """Create the RasterCanvas lazily and populate it."""
        from gui.widgets.raster_canvas import RasterCanvas
        if self._raster_canvas is None:
            self._raster_canvas = RasterCanvas()
        self._load_rasters_into_canvas()

    def _load_rasters_into_canvas(self) -> None:
        """Populate the RasterCanvas with all available Step-2 rasters.

        Layers are added in reverse display-preference order so the most useful
        layer (hillshade if available, else filled DEM) is selected by default.
        """
        if self._raster_canvas is None:
            return
        s      = self._state
        canvas = self._raster_canvas
        canvas.clear()

        # Ordered list: first = preferred default display layer
        rasters = []
        if s.hillshade_path and os.path.exists(s.hillshade_path):
            rasters.append((s.hillshade_path, "Hillshade",         "gray",    ""))
        if s.filled_dem_path and os.path.exists(s.filled_dem_path):
            rasters.append((s.filled_dem_path, "Filled DEM",        "terrain", "m"))
        if s.proj_dem_path and os.path.exists(s.proj_dem_path):
            rasters.append((s.proj_dem_path,   "Projected DEM",     "terrain", "m"))
        if s.accum_path and os.path.exists(s.accum_path):
            rasters.append((s.accum_path,      "Flow Accumulation", "Blues",   "cells"))
        if s.fdir_path and os.path.exists(s.fdir_path):
            rasters.append((s.fdir_path,       "Flow Direction",    "tab10",   ""))

        if not rasters:
            return   # canvas shows "No raster loaded" placeholder

        # Add in reverse so the first item is rendered last → stays as active view
        for path, name, cmap, unit in reversed(rasters):
            canvas.show_file(path, title=name, cmap=cmap, unit=unit)

    def _dem_centre(self) -> tuple:
        """Derive a sensible map centre from state."""
        s = self._state
        if s.bbox:
            b = s.bbox
            return (
                (b["south"] + b["north"]) / 2,
                (b["west"] + b["east"]) / 2,
            )
        return (-29.71, 31.06)   # default: Umhlanga / KZN

    def _rebuild_map(self) -> None:
        """Rebuild the Folium map with current overlays + subcatchments."""
        if self._map_widget is None:
            return
        s = self._state

        _OVERLAY_COLORS = ["#FF6B35", "#004E89", "#1A936F", "#C6AD8F", "#8B1E3F"]
        overlays = [
            {
                "name":    n,
                "geojson": g,
                "color":   _OVERLAY_COLORS[i % len(_OVERLAY_COLORS)],
            }
            for i, (n, g) in enumerate(
                zip(s.overlay_names or [], s.overlay_geojsons or [])
            )
        ]

        _SUB_COLORS = ["#00AA44", "#AA4400", "#0044AA", "#AA0044", "#44AA00"]
        subcatchments = [
            {
                "geojson": g,
                "color":   _SUB_COLORS[i % len(_SUB_COLORS)],
                "label":   f"Sub-{i+1}  ({(s.subcatchment_n_cells or [])[i]:,} cells)"
                           if i < len(s.subcatchment_n_cells or []) else f"Sub-{i+1}",
            }
            for i, g in enumerate(s.subcatchment_geojsons or [])
        ]

        centre = self._dem_centre()
        zoom   = 12 if s.bbox else 10
        html   = MapWidget.build_dem_map(
            centre=centre,
            zoom=zoom,
            bbox=s.bbox,
            overlays=overlays,
            subcatchments=subcatchments,
            allow_outlet_draw=self._waiting_for_outlet,
        )
        self._map_widget.load_map(html)

    # ──────────────────────────────────────────────────────────────────────────
    # Section A — Load existing rasters
    # ──────────────────────────────────────────────────────────────────────────

    def _load_dem(self):
        path = self._browse_and_set("filled_dem_path", "Filled / Projected DEM")
        if path:
            self._state.proj_dem_path = path
            self._state.save()

    def _load_fdir(self):
        self._browse_and_set("fdir_path", "Flow Direction (GRASS 1-8)")

    def _load_accum(self):
        self._browse_and_set("accum_path", "Flow Accumulation")

    # ──────────────────────────────────────────────────────────────────────────
    # Section B — Reproject
    # ──────────────────────────────────────────────────────────────────────────

    def _reproject(self):
        if not self._state.dem_path:
            self.log("Download a DEM in Step 1 first.", "warn")
            return
        worker = DemWorker(self._state, task="reproject")
        worker.finished.connect(lambda _: (
            self._reproj_btn.setEnabled(True),
            self._grass_btn.setEnabled(True),
        ))
        worker.error.connect(lambda _: self._reproj_btn.setEnabled(True))
        self._reproj_btn.setEnabled(False)
        self.set_status("Reprojecting DEM…")
        self.start_worker(worker)

    # ──────────────────────────────────────────────────────────────────────────
    # Section C — GRASS + Hillshade
    # ──────────────────────────────────────────────────────────────────────────

    def _generate_hillshade(self):
        """Run gdaldem hillshade on the filled (or projected) DEM."""
        s = self._state
        if not s.filled_dem_path and not s.proj_dem_path:
            self.log("Load or reproject a DEM first.", "warn")
            return
        worker = DemWorker(self._state, task="hillshade")
        worker.finished.connect(lambda _: self._hillshade_btn.setEnabled(True))
        worker.error.connect(lambda _: self._hillshade_btn.setEnabled(True))
        self._hillshade_btn.setEnabled(False)
        self.set_status("Generating hillshade…")
        self.start_worker(worker)

    def _run_grass(self):
        s = self._state
        if not s.proj_dem_path and not s.filled_dem_path:
            self.log(
                "Reproject the DEM first (section B), or load an existing "
                "filled DEM in section A.",
                "warn",
            )
            return
        worker = FillWorker(self._state, task="grass_all")
        worker.finished.connect(lambda _: self._grass_btn.setEnabled(True))
        worker.error.connect(lambda _: self._grass_btn.setEnabled(True))
        self._grass_btn.setEnabled(False)
        self.set_status("Running GRASS r.fill.dir + r.watershed…")
        self.start_worker(worker)

    # ──────────────────────────────────────────────────────────────────────────
    # Section D — Map overlays
    # ──────────────────────────────────────────────────────────────────────────

    def _load_shapefile(self):
        if not self._state.project_dir:
            self.log("Create a project first (Step 1).", "warn")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Vector Layer",
            os.path.expanduser("~"),
            "Vector files (*.shp *.geojson *.json *.gpkg *.kml);;All files (*)",
        )
        if not path:
            return

        worker = ShapefileWorker(self._state, path)
        self._load_shp_btn.setEnabled(False)
        worker.finished.connect(lambda _: self._load_shp_btn.setEnabled(True))
        worker.error.connect(lambda _: self._load_shp_btn.setEnabled(True))
        self.set_status(f"Loading {os.path.basename(path)}…")
        self.start_worker(worker)

    def _clear_layers(self):
        """Remove all overlay layers from state and rebuild the map."""
        self._state.overlay_paths    = []
        self._state.overlay_names    = []
        self._state.overlay_geojsons = []
        self._state.save()
        self._refresh_overlay_list()
        self._rebuild_map()
        self.log("All overlay layers cleared.")

    def _remove_overlay(self, index: int):
        """Remove a single overlay layer by index."""
        s = self._state
        for attr in ("overlay_paths", "overlay_names", "overlay_geojsons"):
            lst = list(getattr(s, attr) or [])
            if 0 <= index < len(lst):
                lst.pop(index)
            setattr(s, attr, lst)
        s.save()
        self._refresh_overlay_list()
        self._rebuild_map()

    def _refresh_overlay_list(self):
        """Rebuild the overlay QListWidget from state."""
        self._overlay_list.clear()
        for i, name in enumerate(self._state.overlay_names or []):
            item = QListWidgetItem()
            # Widget row: label + remove button
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)
            row_layout.setSpacing(4)

            lbl = QLabel(name)
            lbl.setStyleSheet("font-size:11px;")
            row_layout.addWidget(lbl, stretch=1)

            rm_btn = QToolButton()
            rm_btn.setText("✕")
            rm_btn.setStyleSheet("font-size:10px; border:none; color:#e74c3c;")
            rm_btn.setToolTip(f"Remove '{name}'")
            # capture i in the lambda with default arg
            rm_btn.clicked.connect(lambda _, idx=i: self._remove_overlay(idx))
            row_layout.addWidget(rm_btn)

            item.setSizeHint(row_widget.sizeHint())
            self._overlay_list.addItem(item)
            self._overlay_list.setItemWidget(item, row_widget)

    # ──────────────────────────────────────────────────────────────────────────
    # Section E — Subcatchments
    # ──────────────────────────────────────────────────────────────────────────

    def _toggle_outlet_capture(self):
        """Toggle between 'waiting for outlet click' and idle."""
        if self._waiting_for_outlet:
            # Cancel
            self._waiting_for_outlet = False
            self._add_outlet_btn.setText("📍  Add Outlet on Map")
            self.log("Outlet capture cancelled.")
            self._rebuild_map()
        else:
            # Start waiting
            self._waiting_for_outlet = True
            self._add_outlet_btn.setText("⏳  Click a point on the map…  (Cancel)")
            self.log(
                "Click a point on the river in the map. "
                "GRASS will delineate the upstream subcatchment.",
                "info",
            )
            self._rebuild_map()   # enables marker draw on the map

    def _on_outlet_placed(self, lat: float, lon: float):
        """Called when the user clicks a point on the map."""
        if not self._waiting_for_outlet:
            return   # marker placed in a different context (not subcatchment mode)

        self._waiting_for_outlet = False
        self._add_outlet_btn.setText("📍  Add Outlet on Map")
        self.log(f"Subcatchment outlet placed: ({lat:.5f}°, {lon:.5f}°)")

        worker = SubcatchmentWorker(self._state, outlet_lonlat=(lon, lat))
        self._add_outlet_btn.setEnabled(False)
        worker.finished.connect(lambda _: self._add_outlet_btn.setEnabled(True))
        worker.error.connect(lambda _: self._add_outlet_btn.setEnabled(True))
        sub_n = len(self._state.subcatchment_outlets or []) + 1
        self.set_status(f"Delineating sub-basin {sub_n}…")
        self.start_worker(worker)

    def _on_subcatch_selection(self):
        """Enable or disable the clip button based on list selection."""
        has_selection = bool(self._subcatch_list.selectedItems())
        grass_done    = bool(self._state.filled_dem_path and self._state.drain_ws_path)
        self._clip_btn.setEnabled(has_selection and grass_done)

    def _clip_dem(self):
        """Clip the DEM + create mask for the selected sub-basin."""
        row = self._subcatch_list.currentRow()
        geojsons = self._state.subcatchment_geojsons or []
        if row < 0 or row >= len(geojsons):
            self.log("Select a sub-basin from the list first.", "warn")
            return

        geojson_str = geojsons[row]
        label       = f"sub{row + 1}"
        worker      = ClipWorker(self._state, geojson_str=geojson_str, label=label)
        self._clip_btn.setEnabled(False)
        worker.finished.connect(lambda _: self._clip_btn.setEnabled(True))
        worker.error.connect(lambda _: self._clip_btn.setEnabled(True))
        self.set_status(f"Clipping DEM to sub-basin {row + 1}…")
        self.start_worker(worker)

    def _refresh_subcatch_list(self):
        """Rebuild the subcatchment QListWidget from state."""
        self._subcatch_list.clear()
        n_cells_list = self._state.subcatchment_n_cells or []
        outlets      = self._state.subcatchment_outlets  or []
        for i, n in enumerate(n_cells_list):
            lon, lat = outlets[i] if i < len(outlets) else (0, 0)
            item = QListWidgetItem(
                f"Sub-{i+1}  —  {n:,} cells  "
                f"(outlet: {lat:.4f}°, {lon:.4f}°)"
            )
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsSelectable)
            self._subcatch_list.addItem(item)
