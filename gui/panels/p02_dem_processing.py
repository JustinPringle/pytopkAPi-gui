"""
gui/panels/p02_dem_processing.py
=================================
Step 2 — DEM Processing
  • Reproject the raw SRTM DEM to the project CRS (calls DemWorker)
  • Fill sinks / depressions / flats (calls FillWorker task='fill')
  • Compute flow direction with GRASS recoding (FillWorker task='flowdir')
  • Compute flow accumulation (FillWorker task='accum')
  • Display rasters in the shared RasterCanvas
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.raster_canvas import RasterCanvas
from gui.workers.dem_worker import DemWorker
from gui.workers.fill_worker import FillWorker


class DEMProcessingPanel(BasePanel):
    """Panel for Step 2: reproject + fill + flow routing."""

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

        # ── Reproject group ────────────────────────────────────────────────
        reproj_box = QGroupBox("Reproject DEM")
        reproj_form = QFormLayout(reproj_box)
        reproj_form.setSpacing(8)

        self._reproj_status = QLabel("Not yet reprojected.")
        self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._reproj_status.setWordWrap(True)
        reproj_form.addRow("Status:", self._reproj_status)

        self._reproj_btn = QPushButton("Reproject DEM →")
        self._reproj_btn.setProperty("primary", "true")
        self._reproj_btn.clicked.connect(self._reproject)
        reproj_form.addRow("", self._reproj_btn)

        layout.addWidget(reproj_box)

        # ── Fill group ────────────────────────────────────────────────────
        fill_box = QGroupBox("Fill DEM (pit / depression / flat)")
        fill_form = QFormLayout(fill_box)
        fill_form.setSpacing(8)

        self._fill_status = QLabel("Not yet filled.")
        self._fill_status.setStyleSheet("color:#aaa; font-size:11px;")
        fill_form.addRow("Status:", self._fill_status)

        self._fill_btn = QPushButton("Fill DEM")
        self._fill_btn.setProperty("primary", "true")
        self._fill_btn.setEnabled(False)
        self._fill_btn.clicked.connect(self._fill)
        fill_form.addRow("", self._fill_btn)

        layout.addWidget(fill_box)

        # ── Flow direction group ──────────────────────────────────────────
        fdir_box = QGroupBox("Flow Direction")
        fdir_form = QFormLayout(fdir_box)
        fdir_form.setSpacing(8)

        self._fdir_status = QLabel("Not yet computed.")
        self._fdir_status.setStyleSheet("color:#aaa; font-size:11px;")
        fdir_form.addRow("Status:", self._fdir_status)

        self._fdir_btn = QPushButton("Compute Flow Direction")
        self._fdir_btn.setProperty("primary", "true")
        self._fdir_btn.setEnabled(False)
        self._fdir_btn.clicked.connect(self._flowdir)
        fdir_form.addRow("", self._fdir_btn)

        layout.addWidget(fdir_box)

        # ── Flow accumulation group ───────────────────────────────────────
        accum_box = QGroupBox("Flow Accumulation")
        accum_form = QFormLayout(accum_box)
        accum_form.setSpacing(8)

        self._accum_status = QLabel("Not yet computed.")
        self._accum_status.setStyleSheet("color:#aaa; font-size:11px;")
        accum_form.addRow("Status:", self._accum_status)

        self._accum_btn = QPushButton("Compute Flow Accumulation")
        self._accum_btn.setProperty("primary", "true")
        self._accum_btn.setEnabled(False)
        self._accum_btn.clicked.connect(self._accum)
        accum_form.addRow("", self._accum_btn)

        layout.addWidget(accum_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        """Show the raster canvas; load the best available raster."""
        self._ensure_raster_canvas()
        self._mw.set_raster_widget(self._raster_canvas)
        self._load_available_rasters()
        self._mw.show_raster_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # Reproject status
        if s.proj_dem_path and os.path.exists(s.proj_dem_path):
            self._reproj_status.setText(f"✅ {os.path.basename(s.proj_dem_path)}")
            self._reproj_status.setStyleSheet("color:#2ecc71; font-size:11px;")
            self._fill_btn.setEnabled(True)
        else:
            self._reproj_status.setText("Not yet reprojected.")
            self._reproj_status.setStyleSheet("color:#aaa; font-size:11px;")
            self._fill_btn.setEnabled(False)

        # Fill status
        if s.filled_dem_path and os.path.exists(s.filled_dem_path):
            self._fill_status.setText(f"✅ {os.path.basename(s.filled_dem_path)}")
            self._fill_status.setStyleSheet("color:#2ecc71; font-size:11px;")
            self._fdir_btn.setEnabled(True)
            self._accum_btn.setEnabled(True)
        else:
            self._fill_status.setText("Not yet filled.")
            self._fill_status.setStyleSheet("color:#aaa; font-size:11px;")
            self._fdir_btn.setEnabled(False)
            self._accum_btn.setEnabled(False)

        # Flow direction status
        if s.fdir_path and os.path.exists(s.fdir_path):
            self._fdir_status.setText(f"✅ {os.path.basename(s.fdir_path)}")
            self._fdir_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._fdir_status.setText("Not yet computed.")
            self._fdir_status.setStyleSheet("color:#aaa; font-size:11px;")

        # Accumulation status
        if s.accum_path and os.path.exists(s.accum_path):
            self._accum_status.setText(f"✅ {os.path.basename(s.accum_path)}")
            self._accum_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._accum_status.setText("Not yet computed.")
            self._accum_status.setStyleSheet("color:#aaa; font-size:11px;")

        # Reload rasters if the canvas is already showing
        if self._raster_canvas is not None:
            self._load_available_rasters()

    # ──────────────────────────────────────────────────────────────────────────
    # Raster canvas management
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_raster_canvas(self):
        if self._raster_canvas is None:
            self._raster_canvas = RasterCanvas()

    def _load_available_rasters(self):
        if self._raster_canvas is None:
            return
        s = self._state
        added = False

        for path, name, cmap, unit in [
            (s.accum_path,      "Flow Accumulation", "Blues",   "cells"),
            (s.fdir_path,       "Flow Direction",    "tab10",   "GRASS code"),
            (s.filled_dem_path, "Filled DEM",        "terrain", "m"),
            (s.proj_dem_path,   "Projected DEM",     "terrain", "m"),
        ]:
            if path and os.path.exists(path):
                self._raster_canvas.show_file(path, title=name, cmap=cmap, unit=unit)
                added = True
                break   # show the most-processed one by default

        if not added:
            self._raster_canvas.clear()

    # ──────────────────────────────────────────────────────────────────────────
    # Button slots
    # ──────────────────────────────────────────────────────────────────────────

    def _reproject(self):
        if not self._state.dem_path:
            self.log("Download a DEM in Step 1 first.", "warn")
            return
        if not self._state.crs:
            self.log("Set the project CRS in Step 1 first.", "warn")
            return

        worker = DemWorker(self._state, task="reproject")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._reproj_btn.setEnabled(True))
        worker.error.connect(lambda _: self._reproj_btn.setEnabled(True))
        self._reproj_btn.setEnabled(False)
        self.set_status("Reprojecting DEM…")
        self.start_worker(worker)

    def _fill(self):
        if not self._state.proj_dem_path:
            self.log("Reproject the DEM first.", "warn")
            return

        worker = FillWorker(self._state, task="fill")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._fill_btn.setEnabled(True))
        worker.error.connect(lambda _: self._fill_btn.setEnabled(True))
        self._fill_btn.setEnabled(False)
        self.set_status("Filling DEM…")
        self.start_worker(worker)

    def _flowdir(self):
        if not self._state.filled_dem_path:
            self.log("Fill the DEM first.", "warn")
            return

        worker = FillWorker(self._state, task="flowdir")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._fdir_btn.setEnabled(True))
        worker.error.connect(lambda _: self._fdir_btn.setEnabled(True))
        self._fdir_btn.setEnabled(False)
        self.set_status("Computing flow direction…")
        self.start_worker(worker)

    def _accum(self):
        if not self._state.filled_dem_path:
            self.log("Fill the DEM first.", "warn")
            return

        worker = FillWorker(self._state, task="accum")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._accum_btn.setEnabled(True))
        worker.error.connect(lambda _: self._accum_btn.setEnabled(True))
        self._accum_btn.setEnabled(False)
        self.set_status("Computing flow accumulation…")
        self.start_worker(worker)
