"""
gui/panels/p08_forcing_data.py
================================
Step 8 — Forcing Data
  Rainfall:
    • Single CSV/Excel → rainfields.h5  (datetime index, numeric cols, mm/day)
    • Obscape folder  → average gauges  → rainfields.h5
    • Load existing   → rainfields.h5 already on disk
  ET:
    • Single CSV/Excel → ET.h5  (ETr + ETo, mm/day)
    • Generate synthetic ET from KZN monthly means → ET.h5
    • Load existing   → ET.h5 already on disk
"""

import os

from PyQt6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.workers.forcing_worker import ForcingWorker


class ForcingDataPanel(BasePanel):
    """Panel for Step 8: rainfall + ET forcing file preparation."""

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 8 — Forcing Data")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ══════════════════════════════════════════════════════════════════
        # RAINFALL
        # ══════════════════════════════════════════════════════════════════
        rain_box = QGroupBox("Rainfall → rainfields.h5")
        rain_v   = QVBoxLayout(rain_box)

        # -- Obscape folder mode ------------------------------------------
        obsc_group = QGroupBox("Obscape gauge folder  (recommended)")
        obsc_form  = QFormLayout(obsc_group)
        obsc_form.setSpacing(6)

        obsc_hint = QLabel("Select the folder containing all Obscape gauge CSV files.\n"
                           "Broken gauges (all-zero rain) are skipped automatically.")
        obsc_hint.setStyleSheet("color:#aaa; font-size:11px;")
        obsc_hint.setWordWrap(True)
        obsc_form.addRow("", obsc_hint)

        self._obsc_edit, self._obsc_browse_btn = self._make_path_row(
            "Browse to Obscape CSV folder…"
        )
        self._obsc_browse_btn.clicked.connect(self._browse_obscape_dir)
        obsc_form.addRow("Folder:", self._make_browse_row(self._obsc_edit, self._obsc_browse_btn))

        self._obsc_btn = QPushButton("Average gauges → rainfields.h5")
        self._obsc_btn.setProperty("primary", "true")
        self._obsc_btn.clicked.connect(self._convert_obscape)
        obsc_form.addRow("", self._obsc_btn)
        rain_v.addWidget(obsc_group)

        # -- Single CSV / Excel mode --------------------------------------
        csv_group = QGroupBox("Single CSV / Excel  (datetime index, mm/day)")
        csv_form  = QFormLayout(csv_group)
        csv_form.setSpacing(6)

        self._rain_path_edit, self._rain_browse_btn = self._make_path_row(
            "Browse to CSV / Excel file…"
        )
        self._rain_browse_btn.clicked.connect(self._browse_rain)
        csv_form.addRow("File:", self._make_browse_row(
            self._rain_path_edit, self._rain_browse_btn
        ))

        self._rain_btn = QPushButton("Convert → rainfields.h5")
        self._rain_btn.setProperty("primary", "true")
        self._rain_btn.clicked.connect(self._convert_rain)
        csv_form.addRow("", self._rain_btn)
        rain_v.addWidget(csv_group)

        # -- Load existing HDF5 ------------------------------------------
        rain_load_row = QWidget()
        hl = QHBoxLayout(rain_load_row)
        hl.setContentsMargins(0, 0, 0, 0)
        load_rain_btn = QPushButton("Load existing rainfields.h5…")
        load_rain_btn.clicked.connect(self._load_rain_h5)
        hl.addWidget(load_rain_btn)
        rain_v.addWidget(rain_load_row)

        # -- Status -------------------------------------------------------
        self._rain_status = QLabel("Not yet converted.")
        self._rain_status.setStyleSheet("color:#aaa; font-size:11px;")
        rain_v.addWidget(self._rain_status)

        layout.addWidget(rain_box)

        # ══════════════════════════════════════════════════════════════════
        # ET
        # ══════════════════════════════════════════════════════════════════
        et_box = QGroupBox("Evapotranspiration → ET.h5  (ETr + ETo)")
        et_v   = QVBoxLayout(et_box)

        # -- Synthetic ET -------------------------------------------------
        syn_group = QGroupBox("Synthetic ET — KZN monthly means  (recommended)")
        syn_form  = QFormLayout(syn_group)
        syn_form.setSpacing(6)

        syn_hint = QLabel("Generates daily ETr / ETo from Schulze (2007) coastal KZN means.\n"
                          "Timesteps match existing rainfields.h5 if already converted.")
        syn_hint.setStyleSheet("color:#aaa; font-size:11px;")
        syn_hint.setWordWrap(True)
        syn_form.addRow("", syn_hint)

        self._syn_et_btn = QPushButton("Generate Synthetic ET  (KZN)")
        self._syn_et_btn.setProperty("primary", "true")
        self._syn_et_btn.clicked.connect(self._generate_synthetic_et)
        syn_form.addRow("", self._syn_et_btn)
        et_v.addWidget(syn_group)

        # -- CSV / Excel mode ---------------------------------------------
        et_csv_group = QGroupBox("From CSV / Excel  (datetime index, mm/day)")
        et_csv_form  = QFormLayout(et_csv_group)
        et_csv_form.setSpacing(6)

        self._et_path_edit, self._et_browse_btn = self._make_path_row(
            "Browse to CSV / Excel file…"
        )
        self._et_browse_btn.clicked.connect(self._browse_et)
        et_csv_form.addRow("File:", self._make_browse_row(
            self._et_path_edit, self._et_browse_btn
        ))

        self._et_btn = QPushButton("Convert → ET.h5")
        self._et_btn.setProperty("primary", "true")
        self._et_btn.clicked.connect(self._convert_et)
        et_csv_form.addRow("", self._et_btn)
        et_v.addWidget(et_csv_group)

        # -- Load existing HDF5 ------------------------------------------
        et_load_row = QWidget()
        hl2 = QHBoxLayout(et_load_row)
        hl2.setContentsMargins(0, 0, 0, 0)
        load_et_btn = QPushButton("Load existing ET.h5…")
        load_et_btn.clicked.connect(self._load_et_h5)
        hl2.addWidget(load_et_btn)
        et_v.addWidget(et_load_row)

        # -- Status -------------------------------------------------------
        self._et_status = QLabel("Not yet generated.")
        self._et_status.setStyleSheet("color:#aaa; font-size:11px;")
        et_v.addWidget(self._et_status)

        layout.addWidget(et_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        pass

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state
        if s.rainfields_path and os.path.exists(s.rainfields_path):
            self._rain_status.setText(f"✅ {os.path.basename(s.rainfields_path)}")
            self._rain_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._rain_status.setText("Not yet converted.")
            self._rain_status.setStyleSheet("color:#aaa; font-size:11px;")

        if s.et_path and os.path.exists(s.et_path):
            self._et_status.setText(f"✅ {os.path.basename(s.et_path)}")
            self._et_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._et_status.setText("Not yet generated.")
            self._et_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ── UI helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_path_row(placeholder: str = ""):
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        btn  = QPushButton("…")
        btn.setFixedWidth(32)
        return edit, btn

    @staticmethod
    def _make_browse_row(edit, btn):
        row = QWidget()
        hl  = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.addWidget(edit)
        hl.addWidget(btn)
        return row

    # ── Rainfall actions ───────────────────────────────────────────────────

    def _browse_obscape_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Obscape CSV Folder",
            self._state.project_dir or os.path.expanduser("~"),
        )
        if path:
            self._obsc_edit.setText(path)

    def _browse_rain(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Rainfall File", os.path.expanduser("~"),
            "CSV / Excel (*.csv *.xlsx *.xls);;All files (*)"
        )
        if path:
            self._rain_path_edit.setText(path)

    def _convert_obscape(self):
        src = self._obsc_edit.text().strip()
        if not src:
            self.log("Select the Obscape CSV folder first.", "warn")
            return
        worker = ForcingWorker(self._state, task="obscape", source_path=src)
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._obsc_btn.setEnabled(True))
        worker.error.connect(lambda _: self._obsc_btn.setEnabled(True))
        self._obsc_btn.setEnabled(False)
        self.set_status("Converting Obscape rainfall…")
        self.start_worker(worker)

    def _convert_rain(self):
        src = self._rain_path_edit.text().strip()
        if not src:
            self.log("Select a rainfall file first.", "warn")
            return
        worker = ForcingWorker(self._state, task="rainfall", source_path=src)
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._rain_btn.setEnabled(True))
        worker.error.connect(lambda _: self._rain_btn.setEnabled(True))
        self._rain_btn.setEnabled(False)
        self.set_status("Converting rainfall…")
        self.start_worker(worker)

    def _load_rain_h5(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select rainfields.h5",
            self._state.project_dir or os.path.expanduser("~"),
            "HDF5 (*.h5 *.hdf5);;All files (*)"
        )
        if path:
            self._state.rainfields_path = path
            self._state.save()
            self.refresh_from_state()
            self._mw.refresh_workflow_list()
            self.log(f"Loaded rainfields.h5: {os.path.basename(path)}", "ok")

    # ── ET actions ─────────────────────────────────────────────────────────

    def _generate_synthetic_et(self):
        worker = ForcingWorker(self._state, task="synthetic_et")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._syn_et_btn.setEnabled(True))
        worker.error.connect(lambda _: self._syn_et_btn.setEnabled(True))
        self._syn_et_btn.setEnabled(False)
        self.set_status("Generating synthetic ET…")
        self.start_worker(worker)

    def _browse_et(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ET File", os.path.expanduser("~"),
            "CSV / Excel (*.csv *.xlsx *.xls);;All files (*)"
        )
        if path:
            self._et_path_edit.setText(path)

    def _convert_et(self):
        src = self._et_path_edit.text().strip()
        if not src:
            self.log("Select an ET file first.", "warn")
            return
        worker = ForcingWorker(self._state, task="et", source_path=src)
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._et_btn.setEnabled(True))
        worker.error.connect(lambda _: self._et_btn.setEnabled(True))
        self._et_btn.setEnabled(False)
        self.set_status("Converting ET…")
        self.start_worker(worker)

    def _load_et_h5(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ET.h5",
            self._state.project_dir or os.path.expanduser("~"),
            "HDF5 (*.h5 *.hdf5);;All files (*)"
        )
        if path:
            self._state.et_path = path
            self._state.save()
            self.refresh_from_state()
            self._mw.refresh_workflow_list()
            self.log(f"Loaded ET.h5: {os.path.basename(path)}", "ok")
