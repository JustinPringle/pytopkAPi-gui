"""
gui/panels/p02_dem_processing.py
=================================
Step 2 — DEM Processing
  • Reproject the raw SRTM DEM to the project CRS  (gdalwarp via DemWorker)
  • OR load an already-projected DEM directly
  • Fill depressions + compute flow direction + accumulation using GRASS GIS
      r.fill.dir  → depression-free DEM + flow direction (GRASS 1-8 natively)
      r.watershed → flow accumulation + drainage direction (for watershed step)
  • OR load already-processed rasters (skip GRASS if you have them)
"""

import os

from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.raster_canvas import RasterCanvas
from gui.workers.dem_worker import DemWorker
from gui.workers.fill_worker import FillWorker


class DEMProcessingPanel(BasePanel):
    """Panel for Step 2: reproject + GRASS fill + flow routing."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
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

        title = QLabel("Step 2 — DEM Processing")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── A. Load existing rasters (skip processing) ─────────────────────
        load_box = QGroupBox("A — Load Existing Rasters  (skip processing)")
        load_form = QFormLayout(load_box)
        load_form.setSpacing(6)

        hint = QLabel(
            "Already have GRASS-processed rasters?  Load them here and skip "
            "sections B and C."
        )
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        load_form.addRow("", hint)

        self._load_dem_btn = QPushButton("Browse…  Filled / Projected DEM")
        self._load_dem_btn.clicked.connect(self._load_dem)
        load_form.addRow("DEM:", self._load_dem_btn)

        self._load_fdir_btn = QPushButton("Browse…  Flow Direction  (GRASS 1-8)")
        self._load_fdir_btn.clicked.connect(self._load_fdir)
        load_form.addRow("Flow dir:", self._load_fdir_btn)

        self._load_accum_btn = QPushButton("Browse…  Flow Accumulation")
        self._load_accum_btn.clicked.connect(self._load_accum)
        load_form.addRow("Accum:", self._load_accum_btn)

        layout.addWidget(load_box)

        # ── B. Reproject ───────────────────────────────────────────────────
        reproj_box = QGroupBox("B — Reproject DEM  (gdalwarp, from Step 1 download)")
        reproj_form = QFormLayout(reproj_box)
        reproj_form.setSpacing(8)

        self._reproj_status = QLabel("Not yet reprojected.")
        self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._reproj_status.setWordWrap(True)
        reproj_form.addRow("Status:", self._reproj_status)

        self._reproj_btn = QPushButton("Reproject DEM →  project CRS")
        self._reproj_btn.setProperty("primary", "true")
        self._reproj_btn.clicked.connect(self._reproject)
        reproj_form.addRow("", self._reproj_btn)

        layout.addWidget(reproj_box)

        # ── C. GRASS hydrological processing ──────────────────────────────
        grass_box = QGroupBox("C — GRASS Hydrological Processing  (r.fill.dir + r.watershed)")
        grass_form = QFormLayout(grass_box)
        grass_form.setSpacing(8)

        grass_hint = QLabel(
            "Runs a single GRASS GIS session:\n"
            "  • r.fill.dir  — fills depressions, writes flow direction in native "
            "GRASS 1-8 coding (no recoding needed)\n"
            "  • r.watershed — D8 flow accumulation + drainage direction "
            "(saved for watershed delineation in Step 3)"
        )
        grass_hint.setStyleSheet("color:#aaa; font-size:11px;")
        grass_hint.setWordWrap(True)
        grass_form.addRow("", grass_hint)

        # Individual output status labels
        self._grass_filled_lbl = QLabel("Filled DEM:        —")
        self._grass_filled_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        grass_form.addRow("", self._grass_filled_lbl)

        self._grass_fdir_lbl = QLabel("Flow direction:    —")
        self._grass_fdir_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        grass_form.addRow("", self._grass_fdir_lbl)

        self._grass_accum_lbl = QLabel("Accumulation:      —")
        self._grass_accum_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        grass_form.addRow("", self._grass_accum_lbl)

        self._grass_drain_lbl = QLabel("Drainage (ws):     —")
        self._grass_drain_lbl.setStyleSheet("font-size:11px; color:#aaa;")
        grass_form.addRow("", self._grass_drain_lbl)

        self._grass_btn = QPushButton(
            "Fill + Flow Direction + Accumulation  (GRASS)"
        )
        self._grass_btn.setProperty("primary", "true")
        self._grass_btn.setEnabled(False)
        self._grass_btn.clicked.connect(self._run_grass)
        grass_form.addRow("", self._grass_btn)

        layout.addWidget(grass_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        """Show the raster canvas with the best available raster."""
        self._ensure_raster_canvas()
        self._mw.set_raster_widget(self._raster_canvas)
        self._load_available_rasters()
        self._mw.show_raster_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # ── Reproject status ───────────────────────────────────────────────
        if s.proj_dem_path and os.path.exists(s.proj_dem_path):
            self._reproj_status.setText(f"✅ {os.path.basename(s.proj_dem_path)}")
            self._reproj_status.setStyleSheet("color:#2ecc71; font-size:11px;")
            self._grass_btn.setEnabled(True)
        else:
            self._reproj_status.setText(
                "Not yet reprojected (or load a DEM in section A above)."
            )
            self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
            # Still allow GRASS if a filled DEM was loaded directly
            self._grass_btn.setEnabled(bool(s.filled_dem_path))

        # ── GRASS output status labels ─────────────────────────────────────
        def _lbl(path, name, lbl_widget):
            if path and os.path.exists(path):
                lbl_widget.setText(f"{name}  ✅ {os.path.basename(path)}")
                lbl_widget.setStyleSheet("font-size:11px; color:#2ecc71;")
            else:
                lbl_widget.setText(f"{name}  —")
                lbl_widget.setStyleSheet("font-size:11px; color:#aaa;")

        _lbl(s.filled_dem_path, "Filled DEM:       ", self._grass_filled_lbl)
        _lbl(s.fdir_path,       "Flow direction:   ", self._grass_fdir_lbl)
        _lbl(s.accum_path,      "Accumulation:     ", self._grass_accum_lbl)
        _lbl(s.drain_ws_path,   "Drainage (ws):    ", self._grass_drain_lbl)

        if self._raster_canvas is not None:
            self._load_available_rasters()

    # ──────────────────────────────────────────────────────────────────────────
    # Load existing rasters (section A)
    # ──────────────────────────────────────────────────────────────────────────

    def _load_dem(self):
        path = self._browse_and_set("filled_dem_path", "Filled / Projected DEM")
        if path:
            # Also set proj_dem_path so the GRASS button enables
            self._state.proj_dem_path = path
            self._state.save()

    def _load_fdir(self):
        self._browse_and_set("fdir_path", "Flow Direction (GRASS 1-8)")

    def _load_accum(self):
        self._browse_and_set("accum_path", "Flow Accumulation")

    # ──────────────────────────────────────────────────────────────────────────
    # Raster canvas
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_raster_canvas(self):
        if self._raster_canvas is None:
            self._raster_canvas = RasterCanvas()

    def _load_available_rasters(self):
        if self._raster_canvas is None:
            return
        s = self._state
        for path, name, cmap, unit in [
            (s.accum_path,      "Flow Accumulation", "Blues",   "cells"),
            (s.fdir_path,       "Flow Direction",    "tab10",   "GRASS code"),
            (s.filled_dem_path, "Filled DEM",        "terrain", "m"),
            (s.proj_dem_path,   "Projected DEM",     "terrain", "m"),
        ]:
            if path and os.path.exists(path):
                self._raster_canvas.show_file(path, title=name, cmap=cmap, unit=unit)
                break

    # ──────────────────────────────────────────────────────────────────────────
    # Process buttons
    # ──────────────────────────────────────────────────────────────────────────

    def _reproject(self):
        if not self._state.dem_path:
            self.log("Download a DEM in Step 1 first.", "warn")
            return
        worker = DemWorker(self._state, task="reproject")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: (
            self._reproj_btn.setEnabled(True),
            self._grass_btn.setEnabled(True),
        ))
        worker.error.connect(lambda _: self._reproj_btn.setEnabled(True))
        self._reproj_btn.setEnabled(False)
        self.set_status("Reprojecting DEM…")
        self.start_worker(worker)

    def _run_grass(self):
        s = self._state
        if not s.proj_dem_path and not s.filled_dem_path:
            self.log(
                "Reproject the DEM first (section B), or load an existing DEM "
                "in section A.",
                "warn",
            )
            return

        worker = FillWorker(self._state, task="grass_all")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._grass_btn.setEnabled(True))
        worker.error.connect(lambda _: self._grass_btn.setEnabled(True))
        self._grass_btn.setEnabled(False)
        self.set_status("Running GRASS r.fill.dir + r.watershed…")
        self.start_worker(worker)
