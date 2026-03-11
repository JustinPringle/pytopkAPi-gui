"""
gui/panels/p02_dem_processing.py
=================================
Step 2 — DEM Processing
  1. Reproject DEM      — gdalwarp via DemWorker
  2. Terrain Analysis   — single GRASS session:
       r.fill.dir + r.watershed + r.relief (user-controlled zscale) + r.shade
       Result: shaded relief shown on map automatically
  2b. Terrain Rendering — re-run r.relief + r.shade only (fast, no recompute)
  3. Reference Overlays — load shapefiles/GeoJSON for reference
"""

import os

from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.workers.clip_worker import ClipWorker
from gui.workers.dem_worker import DemWorker
from gui.workers.fill_worker import FillWorker
from gui.workers.relief_worker import ReliefWorker
from gui.workers.shapefile_worker import ShapefileWorker


class DEMProcessingPanel(BasePanel):
    """Panel for Step 2: reproject + GRASS terrain analysis + overlays + sub-basins."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._selected_basins: list = []   # list of (feature_id, geojson_str)

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

        layout.addWidget(self._build_section_reproject())
        layout.addWidget(self._build_section_terrain())
        layout.addWidget(self._build_section_rendering())
        layout.addWidget(self._build_section_overlays())
        layout.addWidget(self._build_section_subbasins())
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        """Show shaded relief on the shared map when Step 2 is activated."""
        mv = self._mw._map_view
        s  = self._state

        mv.clear_all_overlays()
        mv.set_draw_mode('none')

        # Centre on AOI
        if s.bbox:
            b = s.bbox
            centre = ((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
            mv.set_view(centre[0], centre[1], 12)
            mv.add_rectangle(b['south'], b['west'], b['north'], b['east'])
        else:
            mv.set_view(-29.71, 31.06, 10)

        # Terrain background: prefer the GRASS r.shade composite (hypsometric
        # tint + shading) displayed opaquely. Fall back to the raw greyscale
        # hillshade via CSS multiply blend if only relief_path is available.
        clip = (s.bbox["south"], s.bbox["west"], s.bbox["north"], s.bbox["east"]) if s.bbox else None
        if s.shaded_relief_path and os.path.exists(s.shaded_relief_path):
            mv.add_raster_overlay("Shaded Relief", s.shaded_relief_path,
                                  alpha=0.9, clip_bounds=clip,
                                  state_attr="shaded_relief_path")
        elif s.relief_path and os.path.exists(s.relief_path):
            mv.add_raster_overlay("Hillshade", s.relief_path,
                                  blend_mode="multiply", hillshade=True,
                                  clip_bounds=clip,
                                  state_attr="relief_path")

        # Reference overlays (user-loaded shapefiles)
        _OVL_COLORS = ["#FF6B35", "#004E89", "#1A936F", "#C6AD8F", "#8B1E3F"]
        for i, (name, geojson_str) in enumerate(
            zip(s.overlay_names or [], s.overlay_geojsons or [])
        ):
            color = _OVL_COLORS[i % len(_OVL_COLORS)]
            mv.add_vector_overlay(
                name=name, geojson_str=geojson_str,
                color=color, weight=2, fill_opacity=0.15,
            )

        # Basins vector — shown as selectable polygons
        if s.basins_gpkg_path and os.path.exists(s.basins_gpkg_path):
            self._add_vector_gpkg_selectable(mv, s.basins_gpkg_path)

        # Context-aware map hint
        if s.shaded_relief_path and os.path.exists(s.shaded_relief_path):
            self._mw.set_map_hint(
                "Terrain ready — select basins to clip, or proceed to Catchment & Streams"
            )
        elif s.proj_dem_path and os.path.exists(s.proj_dem_path):
            self._mw.set_map_hint(
                "DEM reprojected — click 'Run Terrain Analysis' in the form panel"
            )
        elif s.dem_path and os.path.exists(s.dem_path):
            self._mw.set_map_hint(
                "Raw DEM available — click 'Reproject DEM' to convert to project CRS"
            )
        else:
            self._mw.set_map_hint(
                "No DEM found — download one in 'Create Project' first"
            )

        self._mw.show_map_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # 1. Reproject status
        if s.proj_dem_path and os.path.exists(s.proj_dem_path):
            self._reproj_status.setText(f"✅ {os.path.basename(s.proj_dem_path)}")
            self._reproj_status.setStyleSheet("color:#2ecc71; font-size:11px;")
            self._grass_btn.setEnabled(True)
        elif s.dem_path and os.path.exists(s.dem_path):
            self._reproj_status.setText("Raw DEM ready — click Reproject to convert to project CRS.")
            self._reproj_status.setStyleSheet("color:#dcdcaa; font-size:11px;")
            self._grass_btn.setEnabled(bool(s.filled_dem_path))
        else:
            self._reproj_status.setText("No DEM found — download one in Step 1.")
            self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
            self._grass_btn.setEnabled(bool(s.filled_dem_path))

        # 2. GRASS output status
        def _lbl(path, name, widget):
            if path and os.path.exists(path):
                widget.setText(f"✅ {name}: {os.path.basename(path)}")
                widget.setStyleSheet("font-size:11px; color:#2ecc71;")
            else:
                widget.setText(f"— {name}")
                widget.setStyleSheet("font-size:11px; color:#555;")

        _lbl(s.filled_dem_path,    "Filled DEM",    self._out_filled_lbl)
        _lbl(s.accum_path,         "Accumulation",  self._out_accum_lbl)
        _lbl(s.shaded_relief_path, "Shaded relief", self._out_relief_lbl)
        _lbl(s.basins_gpkg_path,   "Basins vector", self._out_basins_lbl)

        # Clip status
        if hasattr(self, "_clip_status_lbl"):
            if s.clipped_dem_path and os.path.exists(s.clipped_dem_path):
                self._clip_status_lbl.setText(
                    f"✅ Clipped DEM: {os.path.basename(s.clipped_dem_path)}"
                )
                self._clip_status_lbl.setStyleSheet("font-size:11px; color:#2ecc71;")
            else:
                self._clip_status_lbl.setText("No clipped DEM yet.")
                self._clip_status_lbl.setStyleSheet("font-size:11px; color:#aaa;")

        # Sync spinboxes from state
        self._zscale_spin.setValue(s.relief_zscale)
        self._ws_thresh_spin.setValue(s.stream_threshold)

        # 3. Overlay list
        self._refresh_overlay_list()

    # ──────────────────────────────────────────────────────────────────────────
    # Section builders
    # ──────────────────────────────────────────────────────────────────────────

    def _build_section_reproject(self) -> QGroupBox:
        box = QGroupBox("1 — Reproject DEM")
        form = QFormLayout(box)
        form.setSpacing(8)

        hint = QLabel(
            "Converts the downloaded WGS84 DEM to the project CRS (set in Step 1)."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self._reproj_status = QLabel("Not yet reprojected.")
        self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._reproj_status.setWordWrap(True)
        form.addRow("Status:", self._reproj_status)

        self._reproj_btn = QPushButton("Reproject DEM")
        self._reproj_btn.setProperty("primary", "true")
        self._reproj_btn.clicked.connect(self._reproject)
        form.addRow("", self._reproj_btn)

        return box

    def _build_section_terrain(self) -> QGroupBox:
        box = QGroupBox("2 — Terrain Analysis  (GRASS GIS)")
        form = QFormLayout(box)
        form.setSpacing(8)

        hint = QLabel(
            "Runs a GRASS session to fill sinks, compute flow routing, "
            "and create shaded terrain relief.\n"
            "The shaded relief is shown on the map when complete."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        # Relief vertical exaggeration
        zscale_row = QWidget()
        zscale_hl  = QHBoxLayout(zscale_row)
        zscale_hl.setContentsMargins(0, 0, 0, 0)
        zscale_hl.setSpacing(8)

        self._zscale_spin = QDoubleSpinBox()
        self._zscale_spin.setRange(0.5, 20.0)
        self._zscale_spin.setSingleStep(0.5)
        self._zscale_spin.setDecimals(1)
        self._zscale_spin.setValue(self._state.relief_zscale)
        self._zscale_spin.valueChanged.connect(self._on_zscale_changed)
        zscale_hl.addWidget(self._zscale_spin)

        zscale_hint = QLabel("Higher = more dramatic terrain; re-run to update.")
        zscale_hint.setStyleSheet("color:#777; font-size:11px;")
        zscale_hl.addWidget(zscale_hint, stretch=1)
        form.addRow("Relief zscale:", zscale_row)

        # Basin delineation threshold
        thresh_row = QWidget()
        thresh_hl  = QHBoxLayout(thresh_row)
        thresh_hl.setContentsMargins(0, 0, 0, 0)
        thresh_hl.setSpacing(8)

        self._ws_thresh_spin = QSpinBox()
        self._ws_thresh_spin.setRange(10, 1_000_000)
        self._ws_thresh_spin.setSingleStep(100)
        self._ws_thresh_spin.setValue(self._state.stream_threshold)
        self._ws_thresh_spin.valueChanged.connect(self._on_ws_threshold_changed)
        thresh_hl.addWidget(self._ws_thresh_spin)

        thresh_hint = QLabel("cells — larger = fewer, bigger basins")
        thresh_hint.setStyleSheet("color:#777; font-size:11px;")
        thresh_hl.addWidget(thresh_hint, stretch=1)
        form.addRow("Basin threshold:", thresh_row)

        # Output status labels
        self._out_filled_lbl = QLabel("— Filled DEM")
        self._out_accum_lbl  = QLabel("— Accumulation")
        self._out_relief_lbl = QLabel("— Shaded relief")
        self._out_basins_lbl = QLabel("— Basins")
        for lbl in (self._out_filled_lbl, self._out_accum_lbl,
                    self._out_relief_lbl, self._out_basins_lbl):
            lbl.setStyleSheet("font-size:11px; color:#555;")
            form.addRow("", lbl)

        self._grass_btn = QPushButton("Run Terrain Analysis  (GRASS)")
        self._grass_btn.setProperty("primary", "true")
        self._grass_btn.setEnabled(False)
        self._grass_btn.clicked.connect(self._run_grass)
        form.addRow("", self._grass_btn)

        return box

    def _build_section_rendering(self) -> QGroupBox:
        from PyQt6.QtWidgets import QComboBox
        box = QGroupBox("2b — Terrain Rendering  (re-render without full re-run)")
        form = QFormLayout(box)
        form.setSpacing(8)

        hint = QLabel(
            "Adjust how the terrain looks on the map. "
            "Changes here only re-run r.relief + r.shade — much faster than "
            "a full Terrain Analysis."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        # Azimuth
        self._azimuth_spin = QDoubleSpinBox()
        self._azimuth_spin.setRange(0.0, 360.0)
        self._azimuth_spin.setSingleStep(15.0)
        self._azimuth_spin.setDecimals(0)
        self._azimuth_spin.setSuffix("°")
        self._azimuth_spin.setValue(getattr(self._state, "relief_azimuth", 315.0))
        self._azimuth_spin.valueChanged.connect(
            lambda v: setattr(self._state, "relief_azimuth", v)
        )
        form.addRow("Sun azimuth:", self._azimuth_spin)

        # Altitude
        self._altitude_spin = QDoubleSpinBox()
        self._altitude_spin.setRange(5.0, 85.0)
        self._altitude_spin.setSingleStep(5.0)
        self._altitude_spin.setDecimals(0)
        self._altitude_spin.setSuffix("°")
        self._altitude_spin.setValue(getattr(self._state, "relief_altitude", 45.0))
        self._altitude_spin.valueChanged.connect(
            lambda v: setattr(self._state, "relief_altitude", v)
        )
        form.addRow("Sun altitude:", self._altitude_spin)

        # Brighten
        self._brighten_spin = QSpinBox()
        self._brighten_spin.setRange(-50, 80)
        self._brighten_spin.setSingleStep(5)
        self._brighten_spin.setValue(getattr(self._state, "relief_brighten", 30))
        self._brighten_spin.valueChanged.connect(
            lambda v: setattr(self._state, "relief_brighten", v)
        )
        form.addRow("Brighten:", self._brighten_spin)

        # Colour scheme
        self._colors_combo = QComboBox()
        _SCHEMES = [
            ("elevation (hypsometric tint)", "elevation"),
            ("srtm",                          "srtm"),
            ("dem (warm earth)",              "dem"),
            ("terrain (matplotlib)",          "terrain"),
            ("viridis (perceptual)",          "viridis"),
            ("grey (equalised)",              "grey.eq"),
        ]
        for label, value in _SCHEMES:
            self._colors_combo.addItem(label, userData=value)
        current = getattr(self._state, "elevation_colors", "elevation")
        idx = next((i for i, (_, v) in enumerate(_SCHEMES) if v == current), 0)
        self._colors_combo.setCurrentIndex(idx)
        self._colors_combo.currentIndexChanged.connect(
            lambda i: setattr(self._state, "elevation_colors",
                               self._colors_combo.itemData(i))
        )
        form.addRow("Colour scheme:", self._colors_combo)

        self._relief_btn = QPushButton("Re-render Terrain  (GRASS)")
        self._relief_btn.setProperty("primary", "true")
        self._relief_btn.setToolTip(
            "Re-runs r.relief + r.shade only. Does not re-compute flow routing or basins."
        )
        self._relief_btn.clicked.connect(self._run_relief)
        form.addRow("", self._relief_btn)

        return box

    def _build_section_overlays(self) -> QGroupBox:
        box = QGroupBox("3 — Reference Overlays  (optional)")
        layout = QVBoxLayout(box)
        layout.setSpacing(6)

        hint = QLabel(
            "Load shapefiles or GeoJSON files to overlay on the map — "
            "stream gauges, catchment boundaries, river centrelines, etc."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        row = QHBoxLayout()
        self._load_shp_btn = QPushButton("Load Vector Layer…")
        self._load_shp_btn.setToolTip("Supported: .shp, .geojson, .json, .gpkg, .kml")
        self._load_shp_btn.clicked.connect(self._load_shapefile)
        row.addWidget(self._load_shp_btn)

        self._clear_layers_btn = QPushButton("Clear All")
        self._clear_layers_btn.clicked.connect(self._clear_layers)
        row.addWidget(self._clear_layers_btn)
        row.addStretch()
        layout.addLayout(row)

        self._overlay_list = QListWidget()
        self._overlay_list.setMaximumHeight(80)
        layout.addWidget(self._overlay_list)

        return box

    # ──────────────────────────────────────────────────────────────────────────
    # Slots — section 1
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

    # ── Section 2 ────────────────────────────────────────────────────────────

    def _on_zscale_changed(self, val: float):
        self._state.relief_zscale = val

    def _on_ws_threshold_changed(self, val: int):
        self._state.stream_threshold = val

    def _run_grass(self):
        s = self._state
        if not s.proj_dem_path and not s.filled_dem_path:
            self.log("Reproject the DEM first (section 1).", "warn")
            return
        worker = FillWorker(self._state, task="grass_all")
        worker.finished.connect(lambda _: (
            self._grass_btn.setEnabled(True),
            self._reload_map_after_grass(),
        ))
        worker.error.connect(lambda _: self._grass_btn.setEnabled(True))
        self._grass_btn.setEnabled(False)
        self.set_status("Running GRASS terrain analysis…")
        self.start_worker(worker)

    def _reload_map_after_grass(self):
        """After GRASS finishes, refresh the map with the new shaded relief."""
        self.on_activated()

    # ── Section 2b ───────────────────────────────────────────────────────────

    def _run_relief(self):
        s = self._state
        if not s.filled_dem_path and not s.clipped_dem_path:
            self.log("Run Terrain Analysis first to generate the filled DEM.", "warn")
            return
        worker = ReliefWorker(self._state)
        worker.finished.connect(lambda _: (
            self._relief_btn.setEnabled(True),
            self._reload_map_after_grass(),
        ))
        worker.error.connect(lambda _: self._relief_btn.setEnabled(True))
        self._relief_btn.setEnabled(False)
        self.set_status("Re-rendering terrain (r.relief + r.shade)…")
        self.start_worker(worker)

    # ── Section 3 ────────────────────────────────────────────────────────────

    def _load_shapefile(self):
        if not self._state.project_dir:
            self.log("Create a project first (Step 1).", "warn")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Vector Layer", os.path.expanduser("~"),
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
        self._state.overlay_paths    = []
        self._state.overlay_names    = []
        self._state.overlay_geojsons = []
        self._state.save()
        self._refresh_overlay_list()
        self.on_activated()
        self.log("All overlay layers cleared.")

    def _remove_overlay(self, index: int):
        s = self._state
        for attr in ("overlay_paths", "overlay_names", "overlay_geojsons"):
            lst = list(getattr(s, attr) or [])
            if 0 <= index < len(lst):
                lst.pop(index)
            setattr(s, attr, lst)
        s.save()
        self._refresh_overlay_list()
        self.on_activated()

    def _refresh_overlay_list(self):
        self._overlay_list.clear()
        for i, name in enumerate(self._state.overlay_names or []):
            item = QListWidgetItem()
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
            rm_btn.clicked.connect(lambda _, idx=i: self._remove_overlay(idx))
            row_layout.addWidget(rm_btn)
            item.setSizeHint(row_widget.sizeHint())
            self._overlay_list.addItem(item)
            self._overlay_list.setItemWidget(item, row_widget)

    # ──────────────────────────────────────────────────────────────────────────
    # Section 4 — Select & Clip Catchment
    # ──────────────────────────────────────────────────────────────────────────

    def _build_section_subbasins(self) -> QGroupBox:
        box = QGroupBox("4 — Select & Clip Catchment")
        form = QFormLayout(box)
        form.setSpacing(8)

        hint = QLabel(
            "After terrain analysis the basins are shown on the map.\n"
            "Click one or more basins to select them, then clip the DEM\n"
            "to the selected area. The clipped DEM is used for all subsequent steps."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self._sel_basins_lbl = QLabel("No basins selected.")
        self._sel_basins_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("Selected:", self._sel_basins_lbl)

        btn_row = QWidget()
        btn_hl = QHBoxLayout(btn_row)
        btn_hl.setContentsMargins(0, 0, 0, 0)
        btn_hl.setSpacing(6)

        self._clip_btn = QPushButton("Clip DEM to Selection")
        self._clip_btn.setProperty("primary", "true")
        self._clip_btn.setEnabled(False)
        self._clip_btn.clicked.connect(self._clip_to_selected_basin)
        btn_hl.addWidget(self._clip_btn)

        self._clear_sel_btn = QPushButton("Clear Selection")
        self._clear_sel_btn.clicked.connect(self._clear_basin_selection)
        btn_hl.addWidget(self._clear_sel_btn)
        btn_hl.addStretch()
        form.addRow("", btn_row)

        self._clip_status_lbl = QLabel("No clipped DEM yet.")
        self._clip_status_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("Clip status:", self._clip_status_lbl)

        return box

    def _add_vector_gpkg_selectable(self, mv, gpkg_path: str) -> None:
        """Load basins GeoPackage and add as a selectable vector overlay."""
        try:
            import geopandas as gpd

            gdf = gpd.read_file(gpkg_path).to_crs("EPSG:4326")
            geojson_str = gdf.to_json()
            mv.add_vector_overlay(
                name="Basins (vector)",
                geojson_str=geojson_str,
                color="#4FC3F7",
                weight=1,
                fill_opacity=0.15,
                selectable=True,
            )
            # Wire click events from map to panel
            # Disconnect first to avoid duplicates if panel is re-activated
            try:
                mv.feature_clicked.disconnect(self._on_feature_clicked)
            except Exception:
                pass
            mv.feature_clicked.connect(self._on_feature_clicked)
        except Exception as exc:
            self.log(f"Could not load basins for display: {exc}", "warn")

    def _on_feature_clicked(self, overlay_name: str, geojson_str: str) -> None:
        """Toggle basin selection when a feature is clicked on the map."""
        if overlay_name != "Basins (vector)":
            return
        # Use a hash of the geometry as a stable feature ID
        import hashlib
        feature_id = hashlib.md5(geojson_str.encode()).hexdigest()[:8]
        existing_ids = [fid for fid, _ in self._selected_basins]
        if feature_id in existing_ids:
            self._selected_basins = [
                (fid, gj) for fid, gj in self._selected_basins if fid != feature_id
            ]
        else:
            self._selected_basins.append((feature_id, geojson_str))

        n = len(self._selected_basins)
        if n == 0:
            self._sel_basins_lbl.setText("No basins selected.")
            self._sel_basins_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        else:
            self._sel_basins_lbl.setText(f"{n} basin(s) selected.")
            self._sel_basins_lbl.setStyleSheet("font-size:11px; color:#dcdcaa;")
        self._clip_btn.setEnabled(n > 0)

    def _clear_basin_selection(self) -> None:
        self._selected_basins = []
        self._sel_basins_lbl.setText("No basins selected.")
        self._sel_basins_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        self._clip_btn.setEnabled(False)

    def _clip_to_selected_basin(self) -> None:
        if not self._selected_basins:
            self.log("No basins selected.", "warn")
            return

        import json as _json
        from shapely.geometry import shape, mapping
        from shapely.ops import unary_union

        # Merge selected basin polygons
        polys = []
        for fid, gj in self._selected_basins:
            try:
                feat = _json.loads(gj)
                polys.append(shape(feat["geometry"]))
            except Exception as exc:
                self.log(f"Skipping basin {fid}: {exc}", "warn")

        if not polys:
            self.log("No valid geometries to clip with.", "warn")
            return

        merged = unary_union(polys)

        # Buffer by ~1.5 cells to close inter-polygon gaps
        try:
            import rasterio as _rio
            _dem = self._state.clipped_dem_path or self._state.proj_dem_path
            if _dem:
                with _rio.open(_dem) as _src:
                    _cell_m = abs(_src.transform.a)
                # geom is in WGS84 — buffer in degrees (~0.5" per 30m cell)
                # Use a tiny fraction to close raster boundary gaps
                merged = merged.buffer(1e-5)
        except Exception:
            pass

        geojson_str = _json.dumps({
            "type": "Feature",
            "geometry": mapping(merged),
            "properties": {},
        })

        label = f"sel{len(self._selected_basins)}"
        worker = ClipWorker(self._state, geojson_str=geojson_str, label=label)
        worker.finished.connect(self._on_clip_done)
        worker.error.connect(lambda _: self._clip_btn.setEnabled(True))
        self._clip_btn.setEnabled(False)
        self.set_status("Clipping DEM to selected basins…")
        self.start_worker(worker)

    def _on_clip_done(self, outputs: dict) -> None:
        self._clip_btn.setEnabled(True)
        clipped = outputs.get("clipped_dem_path", "")
        if clipped:
            self.log(f"DEM clipped → {os.path.basename(clipped)}", "info")
        self.refresh_from_state()

