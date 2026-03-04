"""
gui/panels/p05_soil_params.py
==============================
Step 5 — Soil Parameters
  • Browse to HWSD GeoTIFF → identify soil codes → edit table → generate rasters
  • OR load already-generated soil rasters directly
"""

import os

from PyQt6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.raster_canvas import RasterCanvas
from gui.widgets.soil_table import SoilTableWidget
from gui.workers.soil_worker import SoilWorker


class SoilParametersPanel(BasePanel):
    """Panel for Step 5: HWSD identification + soil raster generation."""

    _SOIL_FIELDS = [
        ("Soil Depth (m)",            "soil_depth_path"),
        ("Ks — sat. cond. (m/s)",     "hwsd_ks_path"),
        ("θs — sat. moisture",         "hwsd_theta_path"),
        ("θr — resid. moisture",       "hwsd_theta_r_path"),
        ("ψb — bubbling press. (cm)", "hwsd_psi_b_path"),
    ]

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._raster_canvas: RasterCanvas | None = None
        self._soil_load_labels: dict[str, QLabel] = {}

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 5 — Soil Parameters")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Load existing soil rasters ─────────────────────────────────────
        load_box = QGroupBox("Load Existing Soil Rasters")
        load_form = QFormLayout(load_box)
        load_form.setSpacing(5)

        hint = QLabel("Already have soil rasters?  Browse for each file, "
                      "then click 'Mark as Complete'.")
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        load_form.addRow("", hint)

        for label, attr in self._SOIL_FIELDS:
            btn = QPushButton(f"Browse…  {label}")
            btn.clicked.connect(lambda _chk, a=attr, l=label: self._browse_and_set(a, l))
            load_form.addRow("", btn)
            lbl = QLabel("")
            lbl.setStyleSheet("font-size:10px; color:#2ecc71; margin-left:8px;")
            self._soil_load_labels[attr] = lbl
            load_form.addRow("", lbl)

        self._mark_complete_btn = QPushButton("Mark Soil Step as Complete  ✅")
        self._mark_complete_btn.clicked.connect(self._mark_complete)
        load_form.addRow("", self._mark_complete_btn)

        layout.addWidget(load_box)

        # ── HWSD path group ───────────────────────────────────────────────
        hwsd_box = QGroupBox("HWSD Raster  (identify + generate from scratch)")
        hwsd_form = QFormLayout(hwsd_box)
        hwsd_form.setSpacing(8)

        path_row = QWidget()
        path_hl  = QHBoxLayout(path_row)
        path_hl.setContentsMargins(0, 0, 0, 0)
        self._hwsd_edit = QLineEdit()
        self._hwsd_edit.setPlaceholderText("Path to HWSD GeoTIFF…")
        if self._state.hwsd_path:
            self._hwsd_edit.setText(self._state.hwsd_path)
        path_hl.addWidget(self._hwsd_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse_hwsd)
        path_hl.addWidget(browse_btn)
        hwsd_form.addRow("HWSD file:", path_row)

        self._identify_btn = QPushButton("Identify Soils")
        self._identify_btn.setProperty("primary", "true")
        self._identify_btn.clicked.connect(self._identify)
        hwsd_form.addRow("", self._identify_btn)

        layout.addWidget(hwsd_box)

        # ── Parameters table ──────────────────────────────────────────────
        table_box = QGroupBox("Soil Parameters (editable)")
        table_layout = QVBoxLayout(table_box)
        self._soil_table = SoilTableWidget()
        table_layout.addWidget(self._soil_table)

        if self._state.hwsd_codes:
            self._soil_table.load_codes(
                self._state.hwsd_codes,
                overrides=self._state.hwsd_param_overrides,
            )

        layout.addWidget(table_box)

        # ── Generate group ────────────────────────────────────────────────
        gen_box = QGroupBox("Generate Soil Rasters")
        gen_form = QFormLayout(gen_box)
        gen_form.setSpacing(8)

        self._gen_btn = QPushButton("Generate Soil Rasters")
        self._gen_btn.setProperty("primary", "true")
        self._gen_btn.setEnabled(bool(self._state.hwsd_codes))
        self._gen_btn.clicked.connect(self._generate)
        gen_form.addRow("", self._gen_btn)

        self._gen_status = QLabel("No soil rasters generated yet.")
        self._gen_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._gen_status.setWordWrap(True)
        gen_form.addRow("Status:", self._gen_status)

        layout.addWidget(gen_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        if self._raster_canvas is None:
            self._raster_canvas = RasterCanvas()
        self._mw.set_raster_widget(self._raster_canvas)
        self._load_available_raster()
        self._mw.show_raster_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        if s.hwsd_path:
            self._hwsd_edit.setText(s.hwsd_path)

        if s.hwsd_codes:
            self._soil_table.load_codes(s.hwsd_codes, overrides=s.hwsd_param_overrides)
            self._gen_btn.setEnabled(True)

        # Update per-raster status labels in the "Load existing" section
        for label, attr in self._SOIL_FIELDS:
            lbl  = self._soil_load_labels.get(attr)
            path = getattr(s, attr, None)
            if lbl:
                if path and os.path.exists(path):
                    lbl.setText(f"  ✅ {os.path.basename(path)}")
                else:
                    lbl.setText("")

        if s.soil_ready:
            self._gen_status.setText("✅ Soil step complete.")
            self._gen_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        elif s.soil_depth_path and os.path.exists(s.soil_depth_path):
            self._gen_status.setText("✅ Soil rasters generated.")
            self._gen_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._gen_status.setText("No soil rasters generated yet.")
            self._gen_status.setStyleSheet("color:#aaa; font-size:11px;")

        if self._raster_canvas is not None:
            self._load_available_raster()

    def _load_available_raster(self):
        if self._raster_canvas is None:
            return
        s = self._state
        for path, name, cmap, unit in [
            (s.hwsd_ks_path,      "Ks (m/s)",    "YlOrBr", "m/s"),
            (s.soil_depth_path,   "Soil Depth",  "terrain", "m"),
            (s.hwsd_clipped_path, "HWSD Codes",  "tab20",   "code"),
        ]:
            if path and os.path.exists(path):
                self._raster_canvas.show_file(path, title=name, cmap=cmap, unit=unit)
                break

    def _mark_complete(self):
        """Mark soil step as ready (for when all rasters were loaded externally)."""
        self._state.soil_ready = True
        self._state.save()
        self.refresh_from_state()
        self._mw.refresh_workflow_list()
        self.log("Soil step marked as complete.", "ok")

    def _browse_hwsd(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select HWSD GeoTIFF", os.path.expanduser("~"),
            "GeoTIFF (*.tif *.tiff);;All files (*)"
        )
        if path:
            self._hwsd_edit.setText(path)
            self._state.hwsd_path = path

    def _identify(self):
        path = self._hwsd_edit.text().strip()
        if not path or not os.path.exists(path):
            self.log("Select a valid HWSD GeoTIFF path first.", "warn")
            return
        self._state.hwsd_path = path

        worker = SoilWorker(self._state, task="identify")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(self._on_identify_finished)
        worker.error.connect(lambda _: self._identify_btn.setEnabled(True))
        self._identify_btn.setEnabled(False)
        self.set_status("Identifying soils…")
        self.start_worker(worker)

    def _on_identify_finished(self, updates: dict):
        self._identify_btn.setEnabled(True)
        codes = updates.get("hwsd_codes", [])
        if codes:
            self._state.hwsd_codes = codes
            self._state.hwsd_clipped_path = updates.get("hwsd_clipped_path")
            self._soil_table.load_codes(codes)
            self._gen_btn.setEnabled(True)
            self.log(f"Identified {len(codes)} soil code(s): {codes}", "ok")

    def _generate(self):
        params = self._soil_table.get_params()
        if not params:
            self.log("No soil parameters in table.", "warn")
            return
        self._state.hwsd_param_overrides = {str(k): v for k, v in params.items()}

        worker = SoilWorker(self._state, task="generate", hwsd_params=params)
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(self._on_generate_finished)
        worker.error.connect(lambda _: self._gen_btn.setEnabled(True))
        self._gen_btn.setEnabled(False)
        self.set_status("Generating soil rasters…")
        self.start_worker(worker)

    def _on_generate_finished(self, updates: dict):
        self._gen_btn.setEnabled(True)
        if updates.get("soil_depth_path") and os.path.exists(updates["soil_depth_path"]):
            self._state.soil_ready = True
