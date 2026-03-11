"""
gui/panels/p03_watershed.py
============================
Step 3 — Watershed
  • Confirm the catchment mask derived from basin clipping in Step 2
    (clip_mask_path → mask_path)  OR load an existing mask
  • Stream threshold preview on the map (flow accumulation overlay)
  • Compute slope raster using GRASS r.slope.aspect (WatershedWorker task='slope')
  • OR load already-processed slope raster directly
"""

import json
import os

from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.workers.watershed_worker import WatershedWorker


class WatershedPanel(BasePanel):
    """Panel for Step 3: confirm catchment mask + slope computation."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._cached_stream_b64: str | None = None
        self._cached_stream_bounds: list | None = None
        self._cached_n_stream_cells: int = 0
        self._stream_worker = None   # StreamPreviewWorker (background)

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

        layout.addWidget(self._build_section_mask())
        layout.addWidget(self._build_section_threshold())
        layout.addWidget(self._build_section_slope())
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        """Show terrain background + catchment boundary on the shared map."""
        mv = self._mw._map_view
        s  = self._state

        mv.clear_all_overlays()
        mv.set_draw_mode('none')
        self._mw.clear_map_hint()

        # Centre on AOI
        if s.bbox:
            b = s.bbox
            centre = ((b["south"] + b["north"]) / 2, (b["west"] + b["east"]) / 2)
            mv.set_view(centre[0], centre[1], 12)
        else:
            mv.set_view(-29.71, 31.06, 11)

        clip = (s.bbox["south"], s.bbox["west"], s.bbox["north"], s.bbox["east"]) if s.bbox else None

        # Terrain background
        if s.shaded_relief_path and os.path.exists(s.shaded_relief_path):
            mv.add_raster_overlay("Shaded Relief", s.shaded_relief_path,
                                  alpha=0.9, clip_bounds=clip,
                                  state_attr="shaded_relief_path")
        elif s.relief_path and os.path.exists(s.relief_path):
            mv.add_raster_overlay("Hillshade", s.relief_path,
                                  blend_mode="multiply", hillshade=True,
                                  clip_bounds=clip,
                                  state_attr="relief_path")

        # Catchment boundary (green polygon)
        if s.mask_path and os.path.exists(s.mask_path):
            catchment_geojson = self._mask_to_geojson(s.mask_path)
            if catchment_geojson:
                mv.add_vector_overlay(
                    name="Catchment boundary",
                    geojson_str=json.dumps(catchment_geojson),
                    color="#2ecc71", weight=2, fill_opacity=0.15,
                )

        # Cached stream preview
        if self._cached_stream_b64 and self._cached_stream_bounds:
            self._add_stream_raster_overlay(
                self._cached_stream_b64, self._cached_stream_bounds
            )

        self._mw.show_map_tab()

        # Auto-compute stream preview if not already cached
        if self._cached_stream_b64 is None and s.accum_path:
            self._start_stream_preview_async()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # Catchment mask section
        if s.clip_mask_path and os.path.exists(s.clip_mask_path):
            self._clip_mask_lbl.setText(
                f"✅ Available: {os.path.basename(s.clip_mask_path)}"
            )
            self._clip_mask_lbl.setStyleSheet("font-size:11px; color:#2ecc71;")
            self._use_clip_btn.setEnabled(True)
        else:
            self._clip_mask_lbl.setText(
                "No clipped catchment mask — select basins in Step 2 Section 4."
            )
            self._clip_mask_lbl.setStyleSheet("font-size:11px; color:#aaa;")
            self._use_clip_btn.setEnabled(False)

        if s.mask_path and os.path.exists(s.mask_path):
            self._mask_status_lbl.setText(
                f"✅ Active mask: {os.path.basename(s.mask_path)}"
            )
            self._mask_status_lbl.setStyleSheet("font-size:11px; color:#2ecc71;")
            self._slope_btn.setEnabled(True)
        else:
            self._mask_status_lbl.setText("No active catchment mask yet.")
            self._mask_status_lbl.setStyleSheet("font-size:11px; color:#aaa;")
            self._slope_btn.setEnabled(False)

        # Stream threshold
        self._thresh_spin.setValue(s.stream_threshold)
        if s.accum_path and os.path.exists(s.accum_path):
            self._stream_preview_lbl.setText(
                "Flow accumulation ready — click '▶ Preview Streams' to update the map."
            )
            self._stream_preview_lbl.setStyleSheet("color:#dcdcaa; font-size:11px;")
            self._apply_thresh_btn.setEnabled(True)
        else:
            self._stream_preview_lbl.setText(
                "No flow accumulation raster — complete GRASS processing in Step 2 first."
            )
            self._stream_preview_lbl.setStyleSheet("color:#aaa; font-size:11px;")
            self._apply_thresh_btn.setEnabled(False)

        # Slope status
        if s.slope_path and os.path.exists(s.slope_path):
            self._slope_status.setText(f"✅ {os.path.basename(s.slope_path)}")
            self._slope_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._slope_status.setText("Not yet computed.")
            self._slope_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ──────────────────────────────────────────────────────────────────────────
    # Section builders
    # ──────────────────────────────────────────────────────────────────────────

    def _build_section_mask(self) -> QGroupBox:
        box = QGroupBox("Catchment Mask")
        form = QFormLayout(box)
        form.setSpacing(8)

        hint = QLabel(
            "The catchment mask defines the active model domain.\n"
            "After clipping the DEM in Step 2 Section 4, use the clip mask here.\n"
            "Or browse to load an existing mask raster."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self._clip_mask_lbl = QLabel("No clipped catchment mask.")
        self._clip_mask_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("From Step 2:", self._clip_mask_lbl)

        self._use_clip_btn = QPushButton("Use Clip Mask as Catchment Mask")
        self._use_clip_btn.setProperty("primary", "true")
        self._use_clip_btn.setEnabled(False)
        self._use_clip_btn.clicked.connect(self._use_clip_mask)
        form.addRow("", self._use_clip_btn)

        sep_lbl = QLabel("─────  or browse for an existing file  ─────")
        sep_lbl.setStyleSheet("color:#555; font-size:10px;")
        form.addRow("", sep_lbl)

        self._load_mask_btn = QPushButton("Browse…  Catchment Mask (binary)")
        self._load_mask_btn.clicked.connect(self._load_mask)
        form.addRow("Load mask:", self._load_mask_btn)

        self._mask_status_lbl = QLabel("No active catchment mask yet.")
        self._mask_status_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        form.addRow("Status:", self._mask_status_lbl)

        return box

    def _build_section_threshold(self) -> QGroupBox:
        box = QGroupBox("Stream Threshold  (flow accumulation cells)")
        form = QFormLayout(box)
        form.setSpacing(8)

        hint = QLabel(
            "Preview the stream network at different thresholds.\n"
            "Lower = denser network.  Higher = only major channels."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        thresh_row = QHBoxLayout()
        self._thresh_spin = QSpinBox()
        self._thresh_spin.setRange(10, 1_000_000)
        self._thresh_spin.setSingleStep(100)
        self._thresh_spin.setValue(self._state.stream_threshold)
        thresh_row.addWidget(self._thresh_spin)

        self._apply_thresh_btn = QPushButton("▶  Preview Streams on Map")
        self._apply_thresh_btn.clicked.connect(self._apply_threshold)
        thresh_row.addWidget(self._apply_thresh_btn)
        thresh_row.addStretch()
        form.addRow("Threshold:", thresh_row)

        self._stream_preview_lbl = QLabel("No flow accumulation raster — run Step 2 first.")
        self._stream_preview_lbl.setStyleSheet("color:#aaa; font-size:11px;")
        self._stream_preview_lbl.setWordWrap(True)
        form.addRow("Status:", self._stream_preview_lbl)

        return box

    def _build_section_slope(self) -> QGroupBox:
        box = QGroupBox("Slope Raster  (GRASS r.slope.aspect)")
        form = QFormLayout(box)
        form.setSpacing(8)

        hint = QLabel(
            "Computes slope (degrees) from the filled or clipped DEM.\n"
            "Requires an active catchment mask."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        form.addRow("", hint)

        self._slope_status = QLabel("Not yet computed.")
        self._slope_status.setStyleSheet("color:#aaa; font-size:11px;")
        form.addRow("Status:", self._slope_status)

        self._slope_btn = QPushButton("Compute Slope  (GRASS)")
        self._slope_btn.setProperty("primary", "true")
        self._slope_btn.setEnabled(False)
        self._slope_btn.clicked.connect(self._slope)
        form.addRow("", self._slope_btn)

        sep_lbl = QLabel("─────  or browse for an existing file  ─────")
        sep_lbl.setStyleSheet("color:#555; font-size:10px;")
        form.addRow("", sep_lbl)

        self._load_slope_btn = QPushButton("Browse…  Slope Raster (degrees)")
        self._load_slope_btn.clicked.connect(self._load_slope)
        form.addRow("Load slope:", self._load_slope_btn)

        return box

    # ──────────────────────────────────────────────────────────────────────────
    # Slots — mask
    # ──────────────────────────────────────────────────────────────────────────

    def _use_clip_mask(self) -> None:
        """Copy clip_mask_path → mask_path and save state."""
        s = self._state
        if not s.clip_mask_path or not os.path.exists(s.clip_mask_path):
            self.log("Clip mask not found — complete Step 2 Section 4 first.", "warn")
            return
        s.mask_path = s.clip_mask_path
        # Count active cells
        n = self._read_n_cells_from_mask(s.mask_path)
        if n is not None:
            s.n_cells = n
            self.log(f"Catchment mask set ({n:,} active cells).", "ok")
        else:
            self.log("Catchment mask set.", "ok")
        s.save()
        self.refresh_from_state()
        # Update map to show boundary
        if self._mw._map_view:
            self.on_activated()

    def _load_mask(self) -> None:
        def _after_mask(path):
            n = self._read_n_cells_from_mask(path)
            if n is not None:
                self._state.n_cells = n
                self.log(f"  n_cells = {n:,}", "ok")
        self._browse_and_set("mask_path", "Catchment Mask", post_fn=_after_mask)

    def _load_slope(self) -> None:
        self._browse_and_set("slope_path", "Slope Raster (degrees)")

    # ──────────────────────────────────────────────────────────────────────────
    # Stream threshold preview
    # ──────────────────────────────────────────────────────────────────────────

    def _apply_threshold(self) -> None:
        thresh = self._thresh_spin.value()
        self._state.stream_threshold = thresh
        self._state.save()
        self.log(f"Stream threshold → {thresh:,} cells — recomputing…")
        self._cached_stream_b64 = None
        self._start_stream_preview_async()

    def _start_stream_preview_async(self) -> None:
        from gui.workers.stream_preview_worker import StreamPreviewWorker
        s = self._state
        if not s.accum_path or not os.path.exists(s.accum_path):
            return
        if self._stream_worker is not None and self._stream_worker.isRunning():
            return

        worker = StreamPreviewWorker(
            accum_path=s.accum_path,
            threshold=s.stream_threshold,
        )
        worker.finished.connect(self._on_stream_preview_done)
        worker.error.connect(self._on_stream_preview_error)
        self._stream_worker = worker
        self._stream_preview_lbl.setText(
            f"Computing stream preview at threshold = {s.stream_threshold:,} cells…"
        )
        self._stream_preview_lbl.setStyleSheet("color:#dcdcaa; font-size:11px;")
        worker.start()

    def _on_stream_preview_error(self, msg: str) -> None:
        self.log(f"Stream preview failed: {msg}", "error")
        if self._form is not None:
            self._stream_preview_lbl.setText(f"Stream preview failed: {msg}")
            self._stream_preview_lbl.setStyleSheet("color:#e74c3c; font-size:11px;")

    def _on_stream_preview_done(self, result: dict) -> None:
        b64    = result.get("stream_base64")
        bounds = result.get("stream_bounds")
        n      = result.get("n_stream_cells", 0)
        self._cached_stream_b64    = b64
        self._cached_stream_bounds = bounds
        self._cached_n_stream_cells = n

        if self._form is not None:
            if b64:
                self._stream_preview_lbl.setText(
                    f"Stream preview: {n:,} cells at threshold = "
                    f"{self._state.stream_threshold:,}"
                )
                self._stream_preview_lbl.setStyleSheet("color:#2ecc71; font-size:11px;")
            else:
                self._stream_preview_lbl.setText(
                    f"No stream cells at threshold = {self._state.stream_threshold:,}. "
                    "Try a lower value."
                )
                self._stream_preview_lbl.setStyleSheet("color:#e67e22; font-size:11px;")

        if b64 and bounds:
            self._add_stream_raster_overlay(b64, bounds)

    # ──────────────────────────────────────────────────────────────────────────
    # Map helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _add_stream_raster_overlay(self, b64: str, bounds: list) -> None:
        mv = self._mw._map_view
        import json as _json
        js = (
            f"if(window._addRasterOverlay)"
            f"  window._addRasterOverlay("
            f"    'Stream Preview',"
            f"    '{b64}',"
            f"    {_json.dumps(bounds)},"
            f"    0.85"
            f"  );"
        )
        mv._run_js(js)

    # ──────────────────────────────────────────────────────────────────────────
    # Slope slot
    # ──────────────────────────────────────────────────────────────────────────

    def _slope(self) -> None:
        s = self._state
        dem = s.clipped_dem_path or s.filled_dem_path
        if not dem or not os.path.exists(dem):
            self.log("No DEM available — complete Step 2 first.", "warn")
            return
        if not s.mask_path:
            self.log("Set an active catchment mask first.", "warn")
            return
        worker = WatershedWorker(self._state, task="slope")
        worker.finished.connect(lambda _: self._slope_btn.setEnabled(True))
        worker.error.connect(lambda _: self._slope_btn.setEnabled(True))
        self._slope_btn.setEnabled(False)
        self.set_status("Computing slope…")
        self.start_worker(worker)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _mask_to_geojson(mask_path: str) -> dict | None:
        try:
            import rasterio
            from rasterio.features import shapes
            from shapely.geometry import shape, mapping
            from shapely.ops import unary_union, transform as shapely_transform
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
            wgs = shapely_transform(transformer.transform, union)

            return {
                "type": "Feature",
                "geometry": mapping(wgs),
                "properties": {},
            }
        except Exception:
            return None
