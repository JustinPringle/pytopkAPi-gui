"""
gui/panels/p03_watershed.py
============================
Step 3 — Watershed
  • Place outlet marker on interactive Folium map
  • Delineate catchment (calls WatershedWorker task='delineate')
  • Compute slope raster (calls WatershedWorker task='slope')
  • Display mask + slope in shared RasterCanvas
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

        # ── Outlet group ──────────────────────────────────────────────────
        outlet_box = QGroupBox("Outlet Point")
        outlet_form = QFormLayout(outlet_box)
        outlet_form.setSpacing(8)

        hint = QLabel("Click the outlet marker tool on the map →\nthen click the stream outlet location.")
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        outlet_form.addRow("", hint)

        self._outlet_label = QLabel("No outlet set.")
        self._outlet_label.setStyleSheet("color:#aaa;")
        outlet_form.addRow("Outlet:", self._outlet_label)

        layout.addWidget(outlet_box)

        # ── Delineation group ─────────────────────────────────────────────
        delin_box = QGroupBox("Catchment Delineation")
        delin_form = QFormLayout(delin_box)
        delin_form.setSpacing(8)

        self._delin_status = QLabel("Not yet delineated.")
        self._delin_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._delin_status.setWordWrap(True)
        delin_form.addRow("Status:", self._delin_status)

        self._delin_btn = QPushButton("Delineate Catchment")
        self._delin_btn.setProperty("primary", "true")
        self._delin_btn.setEnabled(False)
        self._delin_btn.clicked.connect(self._delineate)
        delin_form.addRow("", self._delin_btn)

        layout.addWidget(delin_box)

        # ── Slope group ───────────────────────────────────────────────────
        slope_box = QGroupBox("Slope Raster")
        slope_form = QFormLayout(slope_box)
        slope_form.setSpacing(8)

        self._slope_status = QLabel("Not yet computed.")
        self._slope_status.setStyleSheet("color:#aaa; font-size:11px;")
        slope_form.addRow("Status:", self._slope_status)

        self._slope_btn = QPushButton("Compute Slope")
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
        else:
            self._delin_status.setText("Not yet delineated.")
            self._delin_status.setStyleSheet("color:#aaa; font-size:11px;")
            self._slope_btn.setEnabled(False)

        # Slope status
        if s.slope_path and os.path.exists(s.slope_path):
            self._slope_status.setText(f"✅ {os.path.basename(s.slope_path)}")
            self._slope_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._slope_status.setText("Not yet computed.")
            self._slope_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ──────────────────────────────────────────────────────────────────────────
    # Map widget
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_map_widget(self):
        if self._map_widget is not None:
            return

        state = self._state

        # Centre on AOI centre or Umhlanga default
        if state.bbox:
            b = state.bbox
            centre = ((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
        else:
            centre = (-29.71, 31.06)

        existing_outlet = None
        if state.outlet_xy:
            lon, lat = state.outlet_xy
            existing_outlet = (lat, lon)

        # Build catchment geojson overlay if mask exists
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
        """Convert the binary mask raster to a GeoJSON polygon for map overlay."""
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
    # Button slots
    # ──────────────────────────────────────────────────────────────────────────

    def _delineate(self):
        if not self._state.outlet_xy:
            self.log("Place the outlet marker on the map first.", "warn")
            return
        if not self._state.filled_dem_path:
            self.log("Complete DEM Processing (Step 2) first.", "warn")
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
            self.log("Complete DEM Processing (Step 2) first.", "warn")
            return

        worker = WatershedWorker(self._state, task="slope")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._slope_btn.setEnabled(True))
        worker.error.connect(lambda _: self._slope_btn.setEnabled(True))
        self._slope_btn.setEnabled(False)
        self.set_status("Computing slope…")
        self.start_worker(worker)
