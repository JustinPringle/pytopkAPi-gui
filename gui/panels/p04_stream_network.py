"""
gui/panels/p04_stream_network.py
=================================
Step 4 — Stream Network
  • Set accumulation threshold for stream extraction
  • Extract stream network + Strahler ordering via GRASS GIS
    (r.stream.extract + r.stream.order)
  • OR load already-processed stream / Strahler rasters directly
"""

import os

from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGroupBox, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.workers.stream_worker import StreamWorker


class StreamNetworkPanel(BasePanel):
    """Panel for Step 4: stream extraction + Strahler ordering."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 4 — Stream Network")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Load existing rasters ──────────────────────────────────────────
        load_box = QGroupBox("Load Existing Rasters")
        load_form = QFormLayout(load_box)
        load_form.setSpacing(6)

        hint = QLabel("Already have GRASS stream network and Strahler rasters?  Load them here.")
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        load_form.addRow("", hint)

        self._load_stream_btn = QPushButton("Browse…  Stream Network (binary)")
        self._load_stream_btn.clicked.connect(self._load_streamnet)
        load_form.addRow("Stream net:", self._load_stream_btn)

        self._load_strahler_btn = QPushButton("Browse…  Strahler Orders")
        self._load_strahler_btn.clicked.connect(self._load_strahler)
        load_form.addRow("Strahler:", self._load_strahler_btn)

        layout.addWidget(load_box)

        # ── GRASS stream extraction ──────────────────────────────────────
        grass_box = QGroupBox("GRASS Stream Extraction")
        grass_form = QFormLayout(grass_box)
        grass_form.setSpacing(8)

        hint2 = QLabel(
            "Uses GRASS r.stream.extract + r.stream.order.\n"
            "Minimum flow accumulation (cells) to define a stream.\n"
            "Smaller values → denser network."
        )
        hint2.setStyleSheet("color:#aaa; font-size:11px;")
        hint2.setWordWrap(True)
        grass_form.addRow("", hint2)

        self._thresh_spin = QSpinBox()
        self._thresh_spin.setRange(10, 100000)
        self._thresh_spin.setValue(self._state.stream_threshold or 500)
        self._thresh_spin.setSingleStep(50)
        self._thresh_spin.valueChanged.connect(self._on_threshold_changed)
        grass_form.addRow("Threshold (cells):", self._thresh_spin)

        self._run_btn = QPushButton("Extract Streams + Strahler Orders")
        self._run_btn.setProperty("primary", "true")
        self._run_btn.clicked.connect(self._run_grass)
        grass_form.addRow("", self._run_btn)

        self._stream_status = QLabel("Not yet extracted.")
        self._stream_status.setStyleSheet("color:#aaa; font-size:11px;")
        grass_form.addRow("Stream net:", self._stream_status)

        self._order_status = QLabel("Not yet computed.")
        self._order_status.setStyleSheet("color:#aaa; font-size:11px;")
        grass_form.addRow("Strahler:", self._order_status)

        layout.addWidget(grass_box)

        # ── Display settings ─────────────────────────────────────────────
        disp_box = QGroupBox("Display Settings")
        disp_form = QFormLayout(disp_box)
        disp_form.setSpacing(8)

        self._width_spin = QDoubleSpinBox()
        self._width_spin.setRange(0.2, 5.0)
        self._width_spin.setSingleStep(0.1)
        self._width_spin.setDecimals(1)
        self._width_spin.setSuffix(" px / order")
        self._width_spin.setValue(getattr(self._state, "stream_width_scale", 0.8))
        self._width_spin.setToolTip(
            "Leaflet line width per Strahler order.\n"
            "Order 1 → 1×scale px,  Order 5 → 5×scale px.\n"
            "Changes take effect when the panel is re-activated."
        )
        self._width_spin.valueChanged.connect(self._on_width_scale_changed)
        disp_form.addRow("Stream width scale:", self._width_spin)

        layout.addWidget(disp_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
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

        # Terrain background: prefer the GRASS r.shade composite (hypsometric
        # tint + shading) opaquely. Fall back to greyscale hillshade multiply
        # blend if the composite is not yet available.
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

        # Strahler stream network — Strahler order drives line width
        if s.streams_gpkg_path and os.path.exists(s.streams_gpkg_path):
            try:
                import geopandas as gpd
                gdf = gpd.read_file(s.streams_gpkg_path).to_crs("EPSG:4326")
                self.log(f"Stream vector columns: {list(gdf.columns)}", "info")
                # Case-insensitive search — GRASS version may name it
                # 'strahler', 'ord_strahler', 'strahler_order', etc.
                strahler_col = next(
                    (c for c in gdf.columns if "strahler" in c.lower()), None
                )
                if not strahler_col:
                    self.log(
                        "No Strahler column found in stream vector — "
                        "streams will display with uniform line width. "
                        "Check log: stream vector columns listed above.",
                        "warn",
                    )
                if strahler_col:
                    gdf = gdf.sort_values(strahler_col, ascending=True)
                geojson_str = gdf.to_json()
                mv.add_vector_overlay(
                    name="Streams (vector)",
                    geojson_str=geojson_str,
                    color="#1565C0",
                    weight=getattr(s, "stream_width_scale", 0.8),
                    fill_opacity=0.0,
                    weight_column=strahler_col or "",
                )
            except Exception as exc:
                self.log(f"Could not display stream network: {exc}", "warn")
        elif s.mask_path and os.path.exists(s.mask_path):
            # Show catchment boundary if no streams yet
            from gui.panels.p03_watershed import WatershedPanel
            geojson = WatershedPanel._mask_to_geojson(s.mask_path)
            if geojson:
                import json as _json
                mv.add_vector_overlay(
                    name="Catchment boundary",
                    geojson_str=_json.dumps(geojson),
                    color="#2ecc71", weight=2, fill_opacity=0.10,
                )

        self._mw.show_map_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        if s.streamnet_path and os.path.exists(s.streamnet_path):
            self._stream_status.setText(f"OK  {os.path.basename(s.streamnet_path)}")
            self._stream_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._stream_status.setText("Not yet extracted.")
            self._stream_status.setStyleSheet("color:#aaa; font-size:11px;")

        if s.strahler_path and os.path.exists(s.strahler_path):
            self._order_status.setText(f"OK  {os.path.basename(s.strahler_path)}")
            self._order_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._order_status.setText("Not yet computed.")
            self._order_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ──────────────────────────────────────────────────────────────────────────
    # Load existing rasters
    # ──────────────────────────────────────────────────────────────────────────

    def _load_streamnet(self):
        self._browse_and_set("streamnet_path", "Stream Network (binary)")

    def _load_strahler(self):
        self._browse_and_set("strahler_path", "Strahler Orders")

    # ──────────────────────────────────────────────────────────────────────────

    def _on_threshold_changed(self, val: int):
        self._state.stream_threshold = val

    def _on_width_scale_changed(self, val: float):
        self._state.stream_width_scale = val
        # Re-render map immediately so the user sees the change
        if self._state.streams_gpkg_path:
            self.on_activated()

    def _run_grass(self):
        if not self._state.filled_dem_path:
            self.log("Filled DEM not found. Complete Step 2 first.", "warn")
            return
        if not self._state.accum_path:
            self.log("Flow accumulation not found. Complete Step 2 first.", "warn")
            return
        worker = StreamWorker(self._state)
        worker.finished.connect(lambda _: self._run_btn.setEnabled(True))
        worker.error.connect(lambda _: self._run_btn.setEnabled(True))
        self._run_btn.setEnabled(False)
        self.set_status("GRASS: extracting streams + Strahler orders…")
        self.start_worker(worker)
