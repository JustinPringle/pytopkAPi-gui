"""
gui/panels/p10_results.py
==========================
Step 10 — Results
  • Load simulation_output.h5 from state.results_path
  • Display hydrograph (Q vs time + rainfall) in HydrographCanvas
  • Display Flow Duration Curve
  • Display mean catchment soil moisture
  • Optionally show spatial maps using RasterCanvas
"""

import os

import numpy as np

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.hydrograph_canvas import HydrographCanvas
from gui.widgets.raster_canvas import RasterCanvas


class ResultsPanel(BasePanel):
    """Panel for Step 10: results visualisation."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._hydro_canvas: HydrographCanvas | None = None
        self._raster_canvas: RasterCanvas | None = None

    def build_form(self) -> QWidget:
        if self._form is not None:
            return self._form

        self._form = QWidget()
        layout = QVBoxLayout(self._form)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        title = QLabel("Step 10 — Results")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Results file ──────────────────────────────────────────────────
        res_box = QGroupBox("Results File")
        res_form = QFormLayout(res_box)
        res_form.setSpacing(8)

        self._res_status = QLabel("No results file.")
        self._res_status.setStyleSheet("color:#aaa; font-size:11px;")
        self._res_status.setWordWrap(True)
        res_form.addRow("File:", self._res_status)

        self._load_btn = QPushButton("Load Results")
        self._load_btn.setProperty("primary", "true")
        self._load_btn.clicked.connect(self._load_results)
        res_form.addRow("", self._load_btn)

        layout.addWidget(res_box)

        # ── Chart selector ────────────────────────────────────────────────
        chart_box = QGroupBox("Charts")
        chart_form = QFormLayout(chart_box)
        chart_form.setSpacing(8)

        self._hydro_btn = QPushButton("Show Hydrograph")
        self._hydro_btn.clicked.connect(self._show_hydrograph)
        chart_form.addRow("", self._hydro_btn)

        self._fdc_btn = QPushButton("Show Flow Duration Curve")
        self._fdc_btn.clicked.connect(self._show_fdc)
        chart_form.addRow("", self._fdc_btn)

        self._vs_btn = QPushButton("Show Soil Moisture")
        self._vs_btn.clicked.connect(self._show_soil_moisture)
        chart_form.addRow("", self._vs_btn)

        layout.addWidget(chart_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        self._ensure_hydro_canvas()
        self._mw.set_chart_widget(self._hydro_canvas)
        self._mw.show_chart_tab()
        if self._state.results_path and os.path.exists(self._state.results_path):
            self._load_results()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state
        if s.results_path and os.path.exists(s.results_path):
            self._res_status.setText(f"✅ {os.path.basename(s.results_path)}")
            self._res_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._res_status.setText("No results file. Run the model (Step 9) first.")
            self._res_status.setStyleSheet("color:#aaa; font-size:11px;")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _ensure_hydro_canvas(self):
        if self._hydro_canvas is None:
            self._hydro_canvas = HydrographCanvas()

    def _load_results(self):
        """Load results HDF5 and prepare data arrays."""
        path = self._state.results_path
        if not path or not os.path.exists(path):
            self.log("No results file found. Run the model first.", "warn")
            return

        try:
            import h5py
            with h5py.File(path, "r") as f:
                # PyTOPKAPI typically stores:
                #   /Channel_flow   (T, n_cells) m³/s
                #   /Overland_flow  (T, n_cells)
                #   /Vs             (T, n_cells)  soil vol storage
                self._Q_arr  = self._read_dataset(f, ["Channel_flow", "Qc", "Q"])
                self._Vs_arr = self._read_dataset(f, ["Vs", "soil_storage"])

            self.log(
                f"Loaded results: {self._Q_arr.shape if self._Q_arr is not None else 'n/a'} "
                f"(T, cells)", "ok"
            )
            self._show_hydrograph()
        except Exception as exc:
            self.log(f"Error loading results: {exc}", "error")

    @staticmethod
    def _read_dataset(f, names: list):
        for name in names:
            if name in f:
                return f[name][:]
        return None

    def _show_hydrograph(self):
        self._ensure_hydro_canvas()
        self._mw.set_chart_widget(self._hydro_canvas)
        self._mw.show_chart_tab()
        if self._Q_arr is not None:
            # Sum across cells to get outlet discharge
            Q_outlet = self._Q_arr.sum(axis=1) if self._Q_arr.ndim > 1 else self._Q_arr
            times    = np.arange(len(Q_outlet))
            self._hydro_canvas.plot_hydrograph(times, Q_outlet)
        else:
            self._hydro_canvas.clear()

    def _show_fdc(self):
        self._ensure_hydro_canvas()
        self._mw.set_chart_widget(self._hydro_canvas)
        self._mw.show_chart_tab()
        if self._Q_arr is not None:
            Q_outlet = self._Q_arr.sum(axis=1) if self._Q_arr.ndim > 1 else self._Q_arr
            self._hydro_canvas.plot_fdc(Q_outlet)
        else:
            self._hydro_canvas.clear()

    def _show_soil_moisture(self):
        self._ensure_hydro_canvas()
        self._mw.set_chart_widget(self._hydro_canvas)
        self._mw.show_chart_tab()
        if self._Vs_arr is not None:
            mean_vs = self._Vs_arr.mean(axis=1) if self._Vs_arr.ndim > 1 else self._Vs_arr
            times   = np.arange(len(mean_vs))
            self._hydro_canvas.plot_soil_moisture(times, mean_vs)
        else:
            self._hydro_canvas.clear()

    # Handle AttributeError if _Q_arr / _Vs_arr not loaded yet
    def __getattr__(self, name):
        if name in ("_Q_arr", "_Vs_arr"):
            return None
        raise AttributeError(name)
