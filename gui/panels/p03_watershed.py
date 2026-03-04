"""
gui/panels/p03_watershed.py
============================
Step 3 — Watershed
  • Place outlet marker on interactive Folium map
  • Delineate catchment using GRASS r.water.outlet (WatershedWorker task='delineate')
  • Compute slope raster using GRASS r.slope.aspect (WatershedWorker task='slope')
  • OR load already-processed mask + slope rasters directly
"""

import os

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.map_widget import MapWidget
from gui.widgets.raster_canvas import RasterCanvas
from gui.workers.watershed_worker import WatershedWorker


class WatershedPanel(BasePanel):
    """Panel for Step 3: outlet placement + catchment delineation + slope."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._map_widget: MapWidget | None = None
        self._raster_canvas: RasterCanvas | None = None

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

        title = QLabel("Step 3 — Watershed")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Load existing rasters ──────────────────────────────────────────
        load_box = QGroupBox("Load Existing Rasters")
        load_form = QFormLayout(load_box)
        load_form.setSpacing(6)

        hint = QLabel("Already have a GRASS catchment mask and slope?  Load them here.")
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        load_form.addRow("", hint)

        self._load_mask_btn = QPushButton("Browse…  Catchment Mask (binary)")
        self._load_mask_btn.clicked.connect(self._load_mask)
        load_form.addRow("Mask:", self._load_mask_btn)

        self._mask_load_status = QLabel("")
        self._mask_load_status.setStyleSheet("color:#aaa; font-size:11px;")
        load_form.addRow("", self._mask_load_status)

        self._load_slope_btn = QPushButton("Browse…  Slope Raster (degrees)")
        self._load_slope_btn.clicked.connect(self._load_slope)
        load_form.addRow("Slope:", self._load_slope_btn)

        layout.addWidget(load_box)

        # ── Outlet group ──────────────────────────────────────────────────
        outlet_box = QGroupBox("Outlet Point  (for GRASS r.water.outlet)")
        outlet_form = QFormLayout(outlet_box)
        outlet_form.setSpacing(8)

        hint2 = QLabel(
            "Click the outlet marker tool on the map →\n"
            "then click the stream outlet location on the map.\n"
            "The coordinate is converted to the project CRS and passed to "
            "GRASS r.water.outlet."
        )
        hint2.setStyleSheet("color:#aaa; font-size:11px;")
        hint2.setWordWrap(True)
        outlet_form.addRow("", hint2)

        self._outlet_label = QLabel("No outlet set.")
        self._outlet_label.setStyleSheet("color:#aaa;")
        outlet_form.addRow("Outlet:", self._outlet_label)

        layout.addWidget(outlet_box)

        # ── Delineation group ─────────────────────────────────────────────
        delin_box = QGroupBox("Catchment Delineation  (GRASS r.water.outlet)")
        delin_form = QFormLayout(delin_box)
        delin_form.setSpacing(8)

        self._delin_status = QLabel("Not yet delineated.")
        self._delin_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._delin_status.setWordWrap(True)
        delin_form.addRow("Status:", self._delin_status)

        self._delin_btn = QPushButton("Delineate Catchment  (GRASS)")
        self._delin_btn.setProperty("primary", "true")
        self._delin_btn.setEnabled(False)
        self._delin_btn.clicked.connect(self._delineate)
        delin_form.addRow("", self._delin_btn)

        layout.addWidget(delin_box)

        # ── Slope group ───────────────────────────────────────────────────
        slope_box = QGroupBox("Slope Raster  (GRASS r.slope.aspect)")
        slope_form = QFormLayout(slope_box)
        slope_form.setSpacing(8)

        self._slope_status = QLabel("Not yet computed.")
        self._slope_status.setStyleSheet("color:#aaa; font-size:11px;")
        slope_form.addRow("Status:", self._slope_status)

        self._slope_btn = QPushButton("Compute Slope  (GRASS)")
        self._slope_btn.setProperty("primary", "true")
        self._slope_btn.setEnabled(False)
        self._slope_btn.clicked.connect(self._slope)
        slope_form.addRow("", self._slope_btn)

        layout.addWidget(slope_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        self._ensure_map_widget()
        self._mw.set_map_widget(self._map_widget)
        self._mw.show_map_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # Outlet label
        if s.outlet_xy:
            lon, lat = s.outlet_xy
            self._outlet_label.setText(f"Lat {lat:.5f}°  Lon {lon:.5f}°")
            self._outlet_label.setStyleSheet("color:#2ecc71;")
            self._delin_btn.setEnabled(True)
        else:
            self._outlet_label.setText("No outlet set.")
            self._outlet_label.setStyleSheet("color:#aaa;")
            self._delin_btn.setEnabled(False)

        # Delineation status
        if s.mask_path and os.path.exists(s.mask_path):
            n = f"  ({s.n_cells:,} cells)" if s.n_cells else ""
            self._delin_status.setText(f"✅ {os.path.basename(s.mask_path)}{n}")
            self._delin_status.setStyleSheet("color:#2ecc71; font-size:11px;")
            self._slope_btn.setEnabled(True)
            self._mask_load_status.setText(
                f"✅ Mask loaded — {s.n_cells:,} cells" if s.n_cells else "✅ Mask loaded"
            )
            self._mask_load_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._delin_status.setText("Not yet delineated.")
            self._delin_status.setStyleSheet("color:#aaa; font-size:11px;")
            self._slope_btn.setEnabled(False)
            self._mask_load_status.setText("")

        # Slope status
        if s.slope_path and os.path.exists(s.slope_path):
            self._slope_status.setText(f"✅ {os.path.basename(s.slope_path)}")
            self._slope_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._slope_status.setText("Not yet computed.")
            self._slope_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ──────────────────────────────────────────────────────────────────────────
    # Load existing rasters
    # ──────────────────────────────────────────────────────────────────────────

    def _load_mask(self):
        def _after_mask(path):
            n = self._read_n_cells_from_mask(path)
            if n is not None:
                self._state.n_cells = n
                self.log(f"  n_cells = {n:,}", "ok")
            else:
                self.log("  Could not read n_cells from mask (rasterio missing?)", "warn")

        self._browse_and_set("mask_path", "Catchment Mask", post_fn=_after_mask)

    def _load_slope(self):
        self._browse_and_set("slope_path", "Slope Raster (degrees)")

    # ──────────────────────────────────────────────────────────────────────────
    # Map widget
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_map_widget(self):
        if self._map_widget is not None:
            return

        state = self._state
        if state.bbox:
            b = state.bbox
            centre = ((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
        else:
            centre = (-29.71, 31.06)

        existing_outlet = None
        if state.outlet_xy:
            lon, lat = state.outlet_xy
            existing_outlet = (lat, lon)

        catchment_geojson = None
        if state.mask_path and os.path.exists(state.mask_path):
            catchment_geojson = self._mask_to_geojson(state.mask_path)

        html = MapWidget.build_outlet_map(
            centre=centre,
            zoom=12,
            existing_outlet=existing_outlet,
            catchment_geojson=catchment_geojson,
        )
        self._map_widget = MapWidget()
        self._map_widget.outlet_placed.connect(self._on_outlet_placed)
        self._map_widget.load_map(html)

    @pyqtSlot(float, float)
    def _on_outlet_placed(self, lat: float, lon: float):
        self._state.outlet_xy = (lon, lat)
        self._state.save()
        self._outlet_label.setText(f"Lat {lat:.5f}°  Lon {lon:.5f}°")
        self._outlet_label.setStyleSheet("color:#2ecc71;")
        self._delin_btn.setEnabled(True)
        self.log(f"Outlet set: lat={lat:.5f}, lon={lon:.5f}", "ok")
        self._mw.refresh_workflow_list()

    @staticmethod
    def _mask_to_geojson(mask_path: str) -> dict | None:
        try:
            import rasterio
            from rasterio.features import shapes
            from shapely.geometry import shape
            from shapely.ops import unary_union
            from pyproj import Transformer

            with rasterio.open(mask_path) as src:
                arr       = src.read(1)
                crs       = src.crs
                transform = src.transform

            polys = [
                shape(geom)
                for geom, val in shapes(arr.astype("uint8"), transform=transform)
                if val == 1
            ]
            if not polys:
                return None

            union = unary_union(polys)
            transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
            coords = list(transformer.itransform(union.exterior.coords))
            wgs_coords = [[lon, lat] for lon, lat in coords]

            return {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [wgs_coords],
                },
                "properties": {},
            }
        except Exception:
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Process buttons
    # ──────────────────────────────────────────────────────────────────────────

    def _delineate(self):
        if not self._state.outlet_xy:
            self.log("Place the outlet marker on the map first.", "warn")
            return
        if not self._state.filled_dem_path or not self._state.drain_ws_path:
            self.log(
                "Run GRASS processing in Step 2 first "
                "(needs filled DEM + drainage direction).",
                "warn",
            )
            return
        worker = WatershedWorker(self._state, task="delineate")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._delin_btn.setEnabled(True))
        worker.error.connect(lambda _: self._delin_btn.setEnabled(True))
        self._delin_btn.setEnabled(False)
        self.set_status("Delineating catchment…")
        self.start_worker(worker)

    def _slope(self):
        if not self._state.filled_dem_path:
            self.log("Load a DEM in Step 2 first.", "warn")
            return
        worker = WatershedWorker(self._state, task="slope")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._slope_btn.setEnabled(True))
        worker.error.connect(lambda _: self._slope_btn.setEnabled(True))
        self._slope_btn.setEnabled(False)
        self.set_status("Computing slope…")
        self.start_worker(worker)
