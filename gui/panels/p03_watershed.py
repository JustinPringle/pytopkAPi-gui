"""
gui/panels/p03_watershed.py
============================
Step 3 — Watershed
  • Show interactive Folium map with:
      - Stream network preview (blue) derived from flow accumulation raster
        using the stream_threshold → helps engineer snap outlet to a real stream
      - Existing catchment boundary (green) once delineated
      - Marker draw control for placing the outlet
  • Place outlet marker → coordinates saved to state
  • Delineate catchment using GRASS r.water.outlet (WatershedWorker task='delineate')
  • Compute slope raster using GRASS r.slope.aspect (WatershedWorker task='slope')
  • OR load already-processed mask + slope rasters directly

Stream preview approach:
    Read accum_path raster → threshold at state.stream_threshold →
    vectorise with rasterio.features.shapes() → reproject to WGS84 →
    return as GeoJSON FeatureCollection of polygons (displayed as light-blue overlay)
"""

import json
import os

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.map_widget import MapWidget
from gui.workers.watershed_worker import WatershedWorker


class WatershedPanel(BasePanel):
    """Panel for Step 3: outlet placement + catchment delineation + slope."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._map_widget: MapWidget | None = None
        self._raster_canvas = None                          # created lazily
        self._cached_stream_geojson: dict | None = None     # cached from last bg computation
        self._stream_worker = None                          # StreamPreviewWorker (background)

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

        # ── Stream threshold ───────────────────────────────────────────────
        thresh_box = QGroupBox("Stream Threshold  (flow accumulation cells)")
        thresh_form = QFormLayout(thresh_box)
        thresh_form.setSpacing(8)

        thresh_hint = QLabel(
            "The minimum number of upstream cells needed to initiate a stream.\n"
            "Lower = more streams shown (denser network).\n"
            "Higher = only major channels shown.\n"
            "Adjust until the stream network matches what you see in the field, "
            "then place the outlet ON a blue stream line."
        )
        thresh_hint.setStyleSheet("color:#aaa; font-size:11px;")
        thresh_hint.setWordWrap(True)
        thresh_form.addRow("", thresh_hint)

        thresh_row = QHBoxLayout()
        self._thresh_spin = QSpinBox()
        self._thresh_spin.setRange(10, 1_000_000)
        self._thresh_spin.setSingleStep(100)
        self._thresh_spin.setValue(self._state.stream_threshold)
        self._thresh_spin.setToolTip(
            "Stream initiation threshold in accumulation cells.\n"
            "For 30m cells, 500 cells ≈ 0.45 km² contributing area."
        )
        thresh_row.addWidget(self._thresh_spin)

        self._apply_thresh_btn = QPushButton("▶  Preview Streams on Map")
        self._apply_thresh_btn.setToolTip(
            "Rebuild the map showing streams at the current threshold.\n"
            "This can take a few seconds for large rasters."
        )
        self._apply_thresh_btn.clicked.connect(self._apply_threshold)
        thresh_row.addWidget(self._apply_thresh_btn)
        thresh_row.addStretch()
        thresh_form.addRow("Threshold:", thresh_row)

        self._stream_preview_lbl = QLabel("No flow accumulation raster — run Step 2 C first.")
        self._stream_preview_lbl.setStyleSheet("color:#aaa; font-size:11px;")
        self._stream_preview_lbl.setWordWrap(True)
        thresh_form.addRow("Status:", self._stream_preview_lbl)

        layout.addWidget(thresh_box)

        # ── Outlet group ──────────────────────────────────────────────────
        outlet_box = QGroupBox("Outlet Point  (for GRASS r.water.outlet)")
        outlet_form = QFormLayout(outlet_box)
        outlet_form.setSpacing(8)

        hint2 = QLabel(
            "Click the marker tool on the map, then click the stream outlet location.\n"
            "Tip: zoom in and click ON a blue stream line for accurate delineation."
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
        """Rebuild the map and populate the Raster tab when Step 3 is activated.

        The map loads instantly (cached stream GeoJSON used if available).
        If no cache exists yet and a flow-accumulation raster is ready, a
        background computation starts automatically so streams appear after a
        few seconds without blocking the UI.
        """
        self._rebuild_map(recompute_streams=False)   # instant — uses cache or no streams
        self._ensure_raster_canvas()
        self._mw.set_raster_widget(self._raster_canvas)
        self._mw.show_map_tab()

        # Auto-compute stream preview if not already cached (non-blocking)
        if self._cached_stream_geojson is None:
            self._start_stream_preview_async()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # Sync threshold spinbox
        self._thresh_spin.setValue(s.stream_threshold)

        # Stream preview status
        if s.accum_path and os.path.exists(s.accum_path):
            self._stream_preview_lbl.setText(
                f"Flow accumulation ready.  Click '▶ Preview Streams' to update the map."
            )
            self._stream_preview_lbl.setStyleSheet("color:#dcdcaa; font-size:11px;")
            self._apply_thresh_btn.setEnabled(True)
        else:
            self._stream_preview_lbl.setText(
                "No flow accumulation raster — complete GRASS processing in Step 2 first."
            )
            self._stream_preview_lbl.setStyleSheet("color:#aaa; font-size:11px;")
            self._apply_thresh_btn.setEnabled(False)

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

        # Reload raster canvas whenever a new raster becomes available
        if self._raster_canvas is not None:
            self._load_rasters_into_canvas()

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
    # Stream threshold preview
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_threshold(self):
        """Save the threshold and recompute the stream preview in the background."""
        thresh = self._thresh_spin.value()
        self._state.stream_threshold = thresh
        self._state.save()
        self.log(f"Stream threshold changed to {thresh:,} cells — recomputing…")
        self._cached_stream_geojson = None   # invalidate so map rebuilds when done
        self._start_stream_preview_async()

    # ──────────────────────────────────────────────────────────────────────────
    # Background stream-preview computation
    # ──────────────────────────────────────────────────────────────────────────

    def _start_stream_preview_async(self) -> None:
        """Launch a background QThread to vectorise flow accumulation → streams.

        Does nothing if:
          • No flow-accumulation raster is available in state.
          • A stream-preview computation is already running.
        The panel connects directly to the worker's signals — the result is NOT
        written to ProjectState and the global progress bar is not consumed.
        """
        from gui.workers.stream_preview_worker import StreamPreviewWorker

        s = self._state
        if not s.accum_path or not os.path.exists(s.accum_path):
            return
        if self._stream_worker is not None and self._stream_worker.isRunning():
            return   # already running; result will appear when it finishes

        worker = StreamPreviewWorker(
            accum_path=s.accum_path,
            threshold=s.stream_threshold,
        )
        worker.finished.connect(self._on_stream_preview_done)
        worker.error.connect(
            lambda msg: self._stream_preview_lbl.setText(f"Stream preview failed: {msg}")
        )
        self._stream_worker = worker   # keep reference so thread stays alive

        self._stream_preview_lbl.setText(
            f"⏳  Computing stream preview at threshold = {s.stream_threshold:,} cells…"
        )
        self._stream_preview_lbl.setStyleSheet("color:#dcdcaa; font-size:11px;")
        worker.start()

    def _on_stream_preview_done(self, result: dict) -> None:
        """Called (on the main thread) when the background stream computation finishes."""
        gc = result.get("stream_geojson")
        self._cached_stream_geojson = gc

        # Update status label (form may be hidden but labels still exist)
        if self._form is not None:
            if gc:
                n_feat = len(gc.get("features", []))
                self._stream_preview_lbl.setText(
                    f"✅ Stream preview: {n_feat:,} features at "
                    f"threshold = {self._state.stream_threshold:,} cells"
                )
                self._stream_preview_lbl.setStyleSheet("color:#2ecc71; font-size:11px;")
            else:
                self._stream_preview_lbl.setText(
                    f"No stream cells found at threshold = "
                    f"{self._state.stream_threshold:,}. Try a lower value."
                )
                self._stream_preview_lbl.setStyleSheet("color:#e67e22; font-size:11px;")

        # Rebuild the map to show the newly computed stream overlay
        # (harmless even if this panel is not currently active)
        self._rebuild_map(recompute_streams=False)

    # ──────────────────────────────────────────────────────────────────────────
    # Map widget
    # ──────────────────────────────────────────────────────────────────────────

    def _rebuild_map(self, recompute_streams: bool = False) -> None:
        """(Re)build the outlet Folium map.

        Always uses ``self._cached_stream_geojson`` for the stream overlay.
        Stream computation happens asynchronously via _start_stream_preview_async()
        and updates the cache; this method just renders whatever is cached.
        The ``recompute_streams`` parameter is kept for API compatibility but is
        no longer used.
        """
        s = self._state

        # ── Centre ────────────────────────────────────────────────────────────
        if s.bbox:
            b = s.bbox
            centre = ((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
        else:
            centre = (-29.71, 31.06)

        # ── Existing outlet marker ────────────────────────────────────────────
        existing_outlet = None
        if s.outlet_xy:
            lon, lat = s.outlet_xy
            existing_outlet = (lat, lon)

        # ── Catchment boundary (green polygon) ───────────────────────────────
        catchment_geojson = None
        if s.mask_path and os.path.exists(s.mask_path):
            catchment_geojson = self._mask_to_geojson(s.mask_path)

        html = MapWidget.build_outlet_map(
            centre=centre,
            zoom=12,
            existing_outlet=existing_outlet,
            catchment_geojson=catchment_geojson,
            stream_geojson=self._cached_stream_geojson,   # use cache (may be None)
        )

        if self._map_widget is None:
            self._map_widget = MapWidget()
            self._map_widget.outlet_placed.connect(self._on_outlet_placed)

        self._map_widget.load_map(html)
        self._mw.set_map_widget(self._map_widget)

    # ──────────────────────────────────────────────────────────────────────────
    # Raster canvas helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_raster_canvas(self) -> None:
        """Create the RasterCanvas lazily and populate it."""
        from gui.widgets.raster_canvas import RasterCanvas
        if self._raster_canvas is None:
            self._raster_canvas = RasterCanvas()
        self._load_rasters_into_canvas()

    def _load_rasters_into_canvas(self) -> None:
        """Populate the RasterCanvas with all available Step-3 rasters.

        Rasters are added in reverse display-preference order so that the
        most-useful layer (slope) ends up selected by default.
        """
        if self._raster_canvas is None:
            return
        s      = self._state
        canvas = self._raster_canvas
        canvas.clear()

        # Ordered list: first = preferred default display layer
        rasters = []
        if s.slope_path and os.path.exists(s.slope_path):
            rasters.append((s.slope_path, "Slope",            "YlOrRd",  "°"))
        if s.mask_path and os.path.exists(s.mask_path):
            rasters.append((s.mask_path,  "Catchment Mask",   "Greens",  ""))
        if s.accum_path and os.path.exists(s.accum_path):
            rasters.append((s.accum_path, "Flow Accumulation","Blues",   "cells"))

        if not rasters:
            return   # canvas shows "No raster loaded" placeholder

        # Add in reverse so the first item is selected last (becomes active view)
        for path, name, cmap, unit in reversed(rasters):
            canvas.show_file(path, title=name, cmap=cmap, unit=unit)

    @staticmethod
    def _accum_to_stream_geojson(accum_path: str, threshold: int) -> dict | None:
        """
        Derive a preview stream network from a flow accumulation raster.

        Pixels with accumulation >= threshold are classified as stream cells.
        These are vectorised using rasterio.features.shapes(), simplified,
        and reprojected to WGS84 as a GeoJSON FeatureCollection.

        Returns None if rasterio/shapely is unavailable or the raster has no
        stream pixels at the given threshold.
        """
        try:
            import numpy as np
            import rasterio
            from rasterio.features import shapes as rio_shapes
            from shapely.geometry import shape
            from shapely.ops import unary_union, transform as shapely_transform
            from pyproj import Transformer

            with rasterio.open(accum_path) as src:
                accum     = src.read(1).astype("float64")
                transform = src.transform
                crs       = src.crs
                nodata    = src.nodata

            # Mask nodata cells before thresholding
            if nodata is not None:
                accum[accum == nodata] = 0

            # Binary stream mask
            stream_mask = (np.abs(accum) >= threshold).astype("uint8")
            if stream_mask.sum() == 0:
                return None

            # Vectorise connected regions of stream cells
            # shapes() yields (geometry_dict, value) pairs
            geoms = [
                shape(geom)
                for geom, val in rio_shapes(stream_mask, transform=transform)
                if val == 1
            ]
            if not geoms:
                return None

            # Limit to max 5000 polygons for map performance; simplify geometry
            # Simplify tolerance ≈ 1 cell width in map units
            cell_size = abs(transform.a)
            geoms = [g.simplify(cell_size * 0.5, preserve_topology=False) for g in geoms]
            geoms = [g for g in geoms if not g.is_empty][:5000]

            # Reproject to WGS84
            trans = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

            def _reproject(geom):
                return shapely_transform(trans.transform, geom)

            features = []
            for g in geoms:
                g_wgs = _reproject(g)
                if not g_wgs.is_empty:
                    features.append({
                        "type": "Feature",
                        "geometry": g_wgs.__geo_interface__,
                        "properties": {},
                    })

            if not features:
                return None

            return {"type": "FeatureCollection", "features": features}

        except ImportError:
            return None
        except Exception:
            return None

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
    # Outlet slot
    # ──────────────────────────────────────────────────────────────────────────

    @pyqtSlot(float, float)
    def _on_outlet_placed(self, lat: float, lon: float):
        self._state.outlet_xy = (lon, lat)
        self._state.save()
        self._outlet_label.setText(f"Lat {lat:.5f}°  Lon {lon:.5f}°")
        self._outlet_label.setStyleSheet("color:#2ecc71;")
        self._delin_btn.setEnabled(True)
        self.log(f"Outlet set: lat={lat:.5f}, lon={lon:.5f}", "ok")
        self._mw.refresh_workflow_list()

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
        worker.finished.connect(lambda _: (
            self._delin_btn.setEnabled(True),
            self._rebuild_map(),      # show the delineated boundary on map
        ))
        worker.error.connect(lambda _: self._delin_btn.setEnabled(True))
        self._delin_btn.setEnabled(False)
        self.set_status("Delineating catchment…")
        self.start_worker(worker)

    def _slope(self):
        if not self._state.filled_dem_path:
            self.log("Load a DEM in Step 2 first.", "warn")
            return
        worker = WatershedWorker(self._state, task="slope")
        worker.finished.connect(lambda _: self._slope_btn.setEnabled(True))
        worker.error.connect(lambda _: self._slope_btn.setEnabled(True))
        self._slope_btn.setEnabled(False)
        self.set_status("Computing slope…")
        self.start_worker(worker)
