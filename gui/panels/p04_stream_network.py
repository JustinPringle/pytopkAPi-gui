"""
gui/panels/p04_stream_network.py
=================================
Step 4 — Stream Network
  • Set accumulation threshold for stream extraction
  • Extract binary stream raster (StreamWorker task='extract')
  • Compute Strahler ordering (StreamWorker task='strahler')
  • Display in shared RasterCanvas
"""

import os

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFormLayout, QGroupBox, QLabel,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.raster_canvas import RasterCanvas
from gui.workers.stream_worker import StreamWorker


class StreamNetworkPanel(BasePanel):
    """Panel for Step 4: stream extraction + Strahler ordering."""

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

        title = QLabel("Step 4 — Stream Network")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Threshold group ───────────────────────────────────────────────
        thresh_box = QGroupBox("Stream Extraction Threshold")
        thresh_form = QFormLayout(thresh_box)
        thresh_form.setSpacing(8)

        hint = QLabel("Minimum flow accumulation (cells) to define a stream.\n"
                      "Smaller values → denser network.")
        hint.setStyleSheet("color:#aaa; font-size:11px;")
        hint.setWordWrap(True)
        thresh_form.addRow("", hint)

        self._thresh_spin = QSpinBox()
        self._thresh_spin.setRange(10, 100000)
        self._thresh_spin.setValue(self._state.stream_threshold or 500)
        self._thresh_spin.setSingleStep(50)
        self._thresh_spin.valueChanged.connect(self._on_threshold_changed)
        thresh_form.addRow("Threshold (cells):", self._thresh_spin)

        self._extract_btn = QPushButton("Extract Stream Network")
        self._extract_btn.setProperty("primary", "true")
        self._extract_btn.clicked.connect(self._extract)
        thresh_form.addRow("", self._extract_btn)

        self._stream_status = QLabel("Not yet extracted.")
        self._stream_status.setStyleSheet("color:#aaa; font-size:11px;")
        thresh_form.addRow("Status:", self._stream_status)

        layout.addWidget(thresh_box)

        # ── Strahler group ────────────────────────────────────────────────
        order_box = QGroupBox("Strahler Stream Ordering")
        order_form = QFormLayout(order_box)
        order_form.setSpacing(8)

        self._order_btn = QPushButton("Compute Strahler Orders")
        self._order_btn.setProperty("primary", "true")
        self._order_btn.setEnabled(False)
        self._order_btn.clicked.connect(self._strahler)
        order_form.addRow("", self._order_btn)

        self._order_status = QLabel("Not yet computed.")
        self._order_status.setStyleSheet("color:#aaa; font-size:11px;")
        order_form.addRow("Status:", self._order_status)

        layout.addWidget(order_box)
        layout.addStretch()

        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        if self._raster_canvas is None:
            self._raster_canvas = RasterCanvas()
        self._mw.set_raster_widget(self._raster_canvas)
        self._load_available_rasters()
        self._mw.show_raster_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state

        if s.streamnet_path and os.path.exists(s.streamnet_path):
            self._stream_status.setText(f"✅ {os.path.basename(s.streamnet_path)}")
            self._stream_status.setStyleSheet("color:#2ecc71; font-size:11px;")
            self._order_btn.setEnabled(True)
        else:
            self._stream_status.setText("Not yet extracted.")
            self._stream_status.setStyleSheet("color:#aaa; font-size:11px;")
            self._order_btn.setEnabled(False)

        if s.strahler_path and os.path.exists(s.strahler_path):
            self._order_status.setText(f"✅ {os.path.basename(s.strahler_path)}")
            self._order_status.setStyleSheet("color:#2ecc71; font-size:11px;")
        else:
            self._order_status.setText("Not yet computed.")
            self._order_status.setStyleSheet("color:#aaa; font-size:11px;")

        if self._raster_canvas is not None:
            self._load_available_rasters()

    def _load_available_rasters(self):
        if self._raster_canvas is None:
            return
        s = self._state
        for path, name, cmap, unit in [
            (s.strahler_path,  "Strahler Order", "tab10",  "order"),
            (s.streamnet_path, "Stream Network", "Blues",  "binary"),
        ]:
            if path and os.path.exists(path):
                self._raster_canvas.show_file(path, title=name, cmap=cmap, unit=unit)
                break

    def _on_threshold_changed(self, val: int):
        self._state.stream_threshold = val

    def _extract(self):
        if not self._state.accum_path:
            self.log("Flow accumulation not found. Complete Step 2 first.", "warn")
            return
        worker = StreamWorker(self._state, task="extract")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._extract_btn.setEnabled(True))
        worker.error.connect(lambda _: self._extract_btn.setEnabled(True))
        self._extract_btn.setEnabled(False)
        self.set_status("Extracting stream network…")
        self.start_worker(worker)

    def _strahler(self):
        if not self._state.streamnet_path:
            self.log("Extract the stream network first.", "warn")
            return
        worker = StreamWorker(self._state, task="strahler")
        worker.log_message.connect(lambda m: self.log(m))
        worker.finished.connect(lambda _: self._order_btn.setEnabled(True))
        worker.error.connect(lambda _: self._order_btn.setEnabled(True))
        self._order_btn.setEnabled(False)
        self.set_status("Computing Strahler orders…")
        self.start_worker(worker)
