"""
gui/panels/p08_forcing_data.py
================================
Step 8 — Forcing Data
  • Browse to rainfall CSV/Excel → convert to rainfields.h5
  • Browse to ET CSV/Excel     → convert to ET.h5
  • Preview first few rows of each file

Expected table format:
  - Index column: datetime
  - Data columns: mm/s values (one per cell, or single column broadcast)
"""

import os

from PyQt6.QtCore import Qt
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

        format_hint = QLabel(
            "Input format: CSV or Excel with a datetime index and numeric data columns.\n"
            "Units: mm/s (rainfall) or mm/day (ET). Single column → broadcast to all cells."
        )
        format_hint.setStyleSheet("color:#aaa; font-size:11px;")
        format_hint.setWordWrap(True)
        layout.addWidget(format_hint)

        # ── Rainfall group ────────────────────────────────────────────────
        rain_box = QGroupBox("Rainfall")
        rain_form = QFormLayout(rain_box)
        rain_form.setSpacing(8)

        self._rain_path_edit, self._rain_browse_btn = self._make_path_row()
        self._rain_browse_btn.clicked.connect(self._browse_rain)
        rain_form.addRow("File:", self._make_browse_row(
            self._rain_path_edit, self._rain_browse_btn
        ))

        self._rain_btn = QPushButton("Convert → rainfields.h5")
        self._rain_btn.setProperty("primary", "true")
        self._rain_btn.clicked.connect(self._convert_rain)
        rain_form.addRow("", self._rain_btn)

        self._rain_status = QLabel("Not yet converted.")
        self._rain_status.setStyleSheet("color:#aaa; font-size:11px;")
        rain_form.addRow("Status:", self._rain_status)

        layout.addWidget(rain_box)

        # ── ET group ──────────────────────────────────────────────────────
        et_box = QGroupBox("Evapotranspiration (ET)")
        et_form = QFormLayout(et_box)
        et_form.setSpacing(8)

        self._et_path_edit, self._et_browse_btn = self._make_path_row()
        self._et_browse_btn.clicked.connect(self._browse_et)
        et_form.addRow("File:", self._make_browse_row(
            self._et_path_edit, self._et_browse_btn
        ))

        self._et_btn = QPushButton("Convert → ET.h5")
        self._et_btn.setProperty("primary", "true")
        self._et_btn.clicked.connect(self._convert_et)
        et_form.addRow("", self._et_btn)

        self._et_status = QLabel("Not yet converted.")
        self._et_status.setStyleSheet("color:#aaa; font-size:11px;")
        et_form.addRow("Status:", self._et_status)

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
            self._et_status.setText("Not yet converted.")
            self._et_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ── File browser helpers ──────────────────────────────────────────────

    @staticmethod
    def _make_path_row():
        edit = QLineEdit()
        edit.setPlaceholderText("Browse to CSV / Excel file…")
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

    def _browse_rain(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Rainfall File", os.path.expanduser("~"),
            "CSV / Excel (*.csv *.xlsx *.xls);;All files (*)"
        )
        if path:
            self._rain_path_edit.setText(path)

    def _browse_et(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ET File", os.path.expanduser("~"),
            "CSV / Excel (*.csv *.xlsx *.xls);;All files (*)"
        )
        if path:
            self._et_path_edit.setText(path)

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
