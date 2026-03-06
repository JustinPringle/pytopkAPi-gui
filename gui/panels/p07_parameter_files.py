"""
gui/panels/p07_parameter_files.py
===================================
Step 7 — Parameter Files
  • Display status of required raster inputs
  • Configure initial conditions and calibration multipliers
  • Generate param_setup.ini + cell_param.dat + TOPKAPI.ini
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGroupBox, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.workers.param_worker import ParamWorker


_RASTER_CHECKS = [
    ("Filled DEM",      "filled_dem_path"),
    ("Catchment mask",  "mask_path"),
    ("Slope",           "slope_path"),
    ("Flow direction",  "fdir_path"),
    ("Stream orders",   "strahler_path"),
    ("Soil depth",      "soil_depth_path"),
    ("Ks",              "hwsd_ks_path"),
    ("θs",              "hwsd_theta_path"),
    ("θr",              "hwsd_theta_r_path"),
    ("ψb",              "hwsd_psi_b_path"),
    ("Manning n_o",     "mannings_path"),
]


class ParameterFilesPanel(BasePanel):
    """Panel for Step 7: parameter file generation."""

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 7 — Parameter Files")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Required inputs checklist ────────────────────────────────────
        check_box = QGroupBox("Required Inputs")
        check_form = QFormLayout(check_box)
        check_form.setSpacing(4)
        self._check_labels: dict[str, QLabel] = {}
        for name, _ in _RASTER_CHECKS:
            lbl = QLabel("⬜ " + name)
            lbl.setStyleSheet("font-size:11px;")
            self._check_labels[name] = lbl
            check_form.addRow("", lbl)
        layout.addWidget(check_box)

        # ── Initial conditions ───────────────────────────────────────────
        ic_box = QGroupBox("Initial Conditions")
        ic_form = QFormLayout(ic_box)
        ic_form.setSpacing(8)

        self._pvs_spin = self._make_dspin(0.0, 100.0, 2, 1.0, self._state.pVs_t0)
        ic_form.addRow("pVs_t0 (% sat.):", self._pvs_spin)

        self._vo_spin = self._make_dspin(0.0, 1e6, 2, 0.1, self._state.Vo_t0)
        ic_form.addRow("Vo_t0 (m³):", self._vo_spin)

        self._qc_spin = self._make_dspin(0.0, 1e6, 4, 0.01, self._state.Qc_t0)
        ic_form.addRow("Qc_t0 (m³/s):", self._qc_spin)

        self._kc_spin = self._make_dspin(0.0, 10.0, 3, 0.1, self._state.Kc)
        ic_form.addRow("Kc (crop factor):", self._kc_spin)

        layout.addWidget(ic_box)

        # ── Calibration multipliers ──────────────────────────────────────
        cal_box = QGroupBox("Calibration Multipliers")
        cal_form = QFormLayout(cal_box)
        cal_form.setSpacing(8)

        self._fac_ks_spin  = self._make_dspin(0.0, 100.0, 3, 0.01, self._state.fac_Ks)
        cal_form.addRow("fac_Ks:", self._fac_ks_spin)

        self._fac_no_spin  = self._make_dspin(0.0, 10.0, 3, 0.1, self._state.fac_n_o)
        cal_form.addRow("fac_n_o:", self._fac_no_spin)

        self._fac_nc_spin  = self._make_dspin(0.0, 10.0, 3, 0.1, self._state.fac_n_c)
        cal_form.addRow("fac_n_c:", self._fac_nc_spin)

        self._fac_l_spin   = self._make_dspin(0.0, 10.0, 3, 0.1, self._state.fac_L)
        cal_form.addRow("fac_L:", self._fac_l_spin)

        layout.addWidget(cal_box)

        # ── Generate button ──────────────────────────────────────────────
        gen_box = QGroupBox("Generate")
        gen_form = QFormLayout(gen_box)
        gen_form.setSpacing(8)

        self._gen_btn = QPushButton("Generate Parameter Files")
        self._gen_btn.setProperty("primary", "true")
        self._gen_btn.clicked.connect(self._generate)
        gen_form.addRow("", self._gen_btn)

        self._gen_status = QLabel("Not yet generated.")
        self._gen_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._gen_status.setWordWrap(True)
        gen_form.addRow("Status:", self._gen_status)

        layout.addWidget(gen_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        pass  # no dedicated map/raster view for this step

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        # Update checklist
        for name, attr in _RASTER_CHECKS:
            path = getattr(s, attr, None)
            ok   = bool(path and os.path.exists(path))
            lbl  = self._check_labels.get(name)
            if lbl:
                lbl.setText(("✅ " if ok else "⬜ ") + name)
                lbl.setStyleSheet(
                    "font-size:11px; color:#2ecc71;" if ok else "font-size:11px; color:#aaa;"
                )

        # Status
        if s.cell_param_path and os.path.exists(s.cell_param_path):
            self._gen_status.setText(f"✅ {os.path.basename(s.cell_param_path)}")
            self._gen_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._gen_status.setText("Not yet generated.")
            self._gen_status.setStyleSheet("color:#aaa; font-size:11px;")

    def _generate(self):
        # Save editable fields to state
        s = self._state
        s.pVs_t0 = self._pvs_spin.value()
        s.Vo_t0  = self._vo_spin.value()
        s.Qc_t0  = self._qc_spin.value()
        s.Kc     = self._kc_spin.value()
        s.fac_Ks = self._fac_ks_spin.value()
        s.fac_n_o = self._fac_no_spin.value()
        s.fac_n_c = self._fac_nc_spin.value()
        s.fac_L  = self._fac_l_spin.value()

        worker = ParamWorker(self._state)
        worker.finished.connect(lambda _: self._gen_btn.setEnabled(True))
        worker.error.connect(lambda _: self._gen_btn.setEnabled(True))
        self._gen_btn.setEnabled(False)
        self.set_status("Generating parameter files…")
        self.start_worker(worker)

    @staticmethod
    def _make_dspin(lo, hi, dec, step, val) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(dec)
        sp.setSingleStep(step)
        sp.setValue(val)
        return sp
