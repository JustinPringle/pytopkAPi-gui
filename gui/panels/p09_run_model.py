"""
gui/panels/p09_run_model.py
============================
Step 9 — Run Model
  • Display global model parameters (cell_size_m, dt_s, α values, W limits)
  • Show prerequisite status (TOPKAPI.ini, rainfields.h5, ET.h5)
  • Run PyTOPKAPI model via ModelWorker
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGroupBox, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.workers.model_worker import ModelWorker


class RunModelPanel(BasePanel):
    """Panel for Step 9: model run configuration + execution."""

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 9 — Run Model")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Prerequisites ─────────────────────────────────────────────────
        pre_box = QGroupBox("Prerequisites")
        pre_form = QFormLayout(pre_box)
        pre_form.setSpacing(4)
        self._pre_ini   = QLabel("⬜ TOPKAPI.ini")
        self._pre_rain  = QLabel("⬜ rainfields.h5")
        self._pre_et    = QLabel("⬜ ET.h5")
        for lbl in (self._pre_ini, self._pre_rain, self._pre_et):
            lbl.setStyleSheet("font-size:11px;")
            pre_form.addRow("", lbl)
        layout.addWidget(pre_box)

        # ── Model parameters ──────────────────────────────────────────────
        mp_box = QGroupBox("Global Model Parameters")
        mp_form = QFormLayout(mp_box)
        mp_form.setSpacing(8)

        self._dt_spin = QSpinBox()
        self._dt_spin.setRange(60, 86400 * 7)
        self._dt_spin.setValue(self._state.dt_s)
        self._dt_spin.setSingleStep(3600)
        mp_form.addRow("dt (s):", self._dt_spin)

        self._alpha_s_spin = self._dsp(0.1, 10.0, 3, 0.1, self._state.alpha_s)
        mp_form.addRow("α_s:", self._alpha_s_spin)

        self._alpha_oc_spin = self._dsp(0.1, 10.0, 4, 0.01, self._state.alpha_oc)
        mp_form.addRow("α_oc (= α_c):", self._alpha_oc_spin)

        self._a_thres_spin = self._dsp(0.0, 1e9, 0, 1000.0, self._state.A_thres)
        mp_form.addRow("A_thres (m²):", self._a_thres_spin)

        self._wmin_spin = self._dsp(0.1, 1000.0, 2, 0.5, self._state.W_min)
        mp_form.addRow("W_min (m):", self._wmin_spin)

        self._wmax_spin = self._dsp(1.0, 10000.0, 1, 1.0, self._state.W_max)
        mp_form.addRow("W_max (m):", self._wmax_spin)

        layout.addWidget(mp_box)

        # ── Run button ────────────────────────────────────────────────────
        run_box = QGroupBox("Run")
        run_form = QFormLayout(run_box)
        run_form.setSpacing(8)

        self._run_btn = QPushButton("▶  Run PyTOPKAPI")
        self._run_btn.setProperty("primary", "true")
        self._run_btn.clicked.connect(self._run_model)
        run_form.addRow("", self._run_btn)

        self._run_status = QLabel("Model not yet run.")
        self._run_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._run_status.setWordWrap(True)
        run_form.addRow("Status:", self._run_status)

        layout.addWidget(run_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        pass

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        def _mark(lbl, path, name):
            ok = bool(path and os.path.exists(path))
            lbl.setText(("✅ " if ok else "⬜ ") + name)
            lbl.setStyleSheet(
                "font-size:11px; color:#2ecc71;" if ok else "font-size:11px; color:#aaa;"
            )

        _mark(self._pre_ini,  s.ini_path,         "TOPKAPI.ini")
        _mark(self._pre_rain, s.rainfields_path,   "rainfields.h5")
        _mark(self._pre_et,   s.et_path,           "ET.h5")

        if s.results_path and os.path.exists(s.results_path):
            self._run_status.setText(f"✅ {os.path.basename(s.results_path)}")
            self._run_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._run_status.setText("Model not yet run.")
            self._run_status.setStyleSheet("color:#aaa; font-size:11px;")

    def _run_model(self):
        s = self._state
        # Save editable params to state first
        s.dt_s     = self._dt_spin.value()
        s.alpha_s  = self._alpha_s_spin.value()
        s.alpha_oc = self._alpha_oc_spin.value()
        s.A_thres  = self._a_thres_spin.value()
        s.W_min    = self._wmin_spin.value()
        s.W_max    = self._wmax_spin.value()

        if not s.ini_path or not os.path.exists(s.ini_path):
            self.log("Generate parameter files (Step 7) first.", "warn")
            return
        if not s.rainfields_path or not os.path.exists(s.rainfields_path):
            self.log("Prepare rainfall forcing (Step 8) first.", "warn")
            return
        if not s.et_path or not os.path.exists(s.et_path):
            self.log("Prepare ET forcing (Step 8) first.", "warn")
            return

        # Update TOPKAPI.ini with latest params before running
        from gui.workers.param_worker import ParamWorker
        ParamWorker._write_topkapi_ini(s.ini_path, s.cell_param_path, s)

        worker = ModelWorker(self._state)
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._run_btn.setEnabled(True))
        worker.error.connect(lambda _: self._run_btn.setEnabled(True))
        self._run_btn.setEnabled(False)
        self.set_status("Running PyTOPKAPI…")
        self.start_worker(worker)

    @staticmethod
    def _dsp(lo, hi, dec, step, val) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(dec)
        sp.setSingleStep(step)
        sp.setValue(val)
        return sp
