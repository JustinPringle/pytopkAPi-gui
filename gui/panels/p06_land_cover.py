"""
gui/panels/p06_land_cover.py
=============================
Step 6 — Land Cover
  • Optionally browse to a land cover GeoTIFF
  • Set overland Manning n_o (uniform or per land cover class)
  • Generate n_o raster (LandCoverWorker task='generate')
  • OR load an already-generated Manning n_o raster directly
"""

import os

from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.raster_canvas import RasterCanvas
from gui.workers.land_cover_worker import LandCoverWorker


class LandCoverPanel(BasePanel):
    """Panel for Step 6: Manning n_o raster generation."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._raster_canvas: RasterCanvas | None = None

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 6 — Land Cover")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Load existing n_o raster ───────────────────────────────────────
        load_box = QGroupBox("Load Existing Manning n_o Raster")
        load_form = QFormLayout(load_box)
        load_form.setSpacing(6)

        hint_load = QLabel("Already have a Manning n_o GeoTIFF?  Load it directly.")
        hint_load.setStyleSheet("color:#aaa; font-size:11px;")
        hint_load.setWordWrap(True)
        load_form.addRow("", hint_load)

        self._load_no_btn = QPushButton("Browse…  Manning n_o Raster")
        self._load_no_btn.clicked.connect(self._load_mannings)
        load_form.addRow("n_o file:", self._load_no_btn)

        layout.addWidget(load_box)

        # ── Land cover file (optional) ─────────────────────────────────
        lc_box = QGroupBox("Land Cover Raster (optional — for per-class n_o)")
        lc_form = QFormLayout(lc_box)
        lc_form.setSpacing(8)

        hint = QLabel("If provided, Manning n_o is assigned per land cover class.\n"
                      "Leave blank to use a uniform n_o for the whole catchment.")
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        lc_form.addRow("", hint)

        path_row = QWidget()
        path_hl  = QHBoxLayout(path_row)
        path_hl.setContentsMargins(0, 0, 0, 0)
        self._lc_edit = QLineEdit()
        self._lc_edit.setPlaceholderText("Path to land cover GeoTIFF (optional)…")
        if self._state.lc_path:
            self._lc_edit.setText(self._state.lc_path)
        path_hl.addWidget(self._lc_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse_lc)
        path_hl.addWidget(browse_btn)
        lc_form.addRow("LC file:", path_row)

        layout.addWidget(lc_box)

        # ── Uniform n_o ────────────────────────────────────────────────
        no_box = QGroupBox("Generate Manning n_o Raster")
        no_form = QFormLayout(no_box)
        no_form.setSpacing(8)

        self._no_spin = QDoubleSpinBox()
        self._no_spin.setRange(0.001, 2.0)
        self._no_spin.setDecimals(3)
        self._no_spin.setSingleStep(0.01)
        self._no_spin.setValue(0.30)
        no_form.addRow("Uniform n_o:", self._no_spin)

        note = QLabel("Used when no land cover file is provided, or for un-classified cells.")
        note.setStyleSheet("color:#aaa; font-size:11px;")
        note.setWordWrap(True)
        no_form.addRow("", note)

        self._gen_btn = QPushButton("Generate n_o Raster")
        self._gen_btn.setProperty("primary", "true")
        self._gen_btn.clicked.connect(self._generate)
        no_form.addRow("", self._gen_btn)

        self._gen_status = QLabel("Not yet generated.")
        self._gen_status.setStyleSheet("color:#aaa; font-size:11px;")
        no_form.addRow("Status:", self._gen_status)

        layout.addWidget(no_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        if self._raster_canvas is None:
            self._raster_canvas = RasterCanvas()
        self._mw.set_raster_widget(self._raster_canvas)
        if self._state.mannings_path and os.path.exists(self._state.mannings_path):
            self._raster_canvas.show_file(
                self._state.mannings_path, title="Manning n_o",
                cmap="YlGn", unit="-"
            )
        self._mw.show_raster_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        if self._state.lc_path:
            self._lc_edit.setText(self._state.lc_path)
        if self._state.mannings_path and os.path.exists(self._state.mannings_path):
            self._gen_status.setText(f"✅ {os.path.basename(self._state.mannings_path)}")
            self._gen_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._gen_status.setText("Not yet generated.")
            self._gen_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ── Load existing ─────────────────────────────────────────────────────

    def _load_mannings(self):
        def _after(path):
            self._state.landcover_ready = True
        self._browse_and_set("mannings_path", "Manning n_o Raster", post_fn=_after)

    # ── Browse + generate ─────────────────────────────────────────────────

    def _browse_lc(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Land Cover GeoTIFF", os.path.expanduser("~"),
            "GeoTIFF (*.tif *.tiff);;All files (*)"
        )
        if path:
            self._lc_edit.setText(path)
            self._state.lc_path = path

    def _generate(self):
        if not self._state.mask_path:
            self.log("Load or delineate catchment mask (Step 3) first.", "warn")
            return

        lc_path = self._lc_edit.text().strip() or None
        if lc_path:
            self._state.lc_path = lc_path
        uniform_n_o = self._no_spin.value()

        worker = LandCoverWorker(
            self._state,
            task="generate",
            n_o_table=None,
            uniform_n_o=uniform_n_o,
        )
        worker.finished.connect(lambda _: self._gen_btn.setEnabled(True))
        worker.error.connect(lambda _: self._gen_btn.setEnabled(True))
        self._gen_btn.setEnabled(False)
        self.set_status("Generating n_o raster…")
        self.start_worker(worker)
