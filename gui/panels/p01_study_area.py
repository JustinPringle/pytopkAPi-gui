"""
gui/panels/p01_study_area.py
============================
Step 1 — Study Area
  • Create/open a project directory
  • Select CRS
  • Draw AOI rectangle on interactive Folium map
  • Download SRTM DEM from OpenTopography
"""

import os

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.widgets.map_widget import MapWidget
from gui.workers.dem_worker import DemWorker


CRS_OPTIONS = {
    "UTM Zone 36S  (EPSG:32736) — KwaZulu-Natal": "EPSG:32736",
    "UTM Zone 35S  (EPSG:32735)": "EPSG:32735",
    "Lo31 / Cape  (EPSG:22235)": "EPSG:22235",
    "WGS 84  (EPSG:4326) — geographic": "EPSG:4326",
    "Custom…": "custom",
}

DEM_OPTIONS = {
    "SRTMGL1 (1 arc-sec ~30 m)": "SRTMGL1",
    "SRTMGL3 (3 arc-sec ~90 m)": "SRTMGL3",
    "COP-DEM GLO-30 (30 m, Copernicus)": "COP30",
    "NASADEM (30 m)": "NASADEM",
}


class StudyAreaPanel(BasePanel):
    """Panel for Step 1: project setup + AOI + DEM download."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)
        self._map_widget: MapWidget | None = None

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

        # Title
        title = QLabel("Step 1 — Study Area")
        title.setProperty("role", "title")
        layout.addWidget(title)

        # ── Project group ─────────────────────────────────────────────────
        proj_box = QGroupBox("Project")
        proj_form = QFormLayout(proj_box)
        proj_form.setSpacing(8)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. umhlanga")
        proj_form.addRow("Project name:", self._name_edit)

        dir_row = QWidget()
        dir_hl = QHBoxLayout(dir_row)
        dir_hl.setContentsMargins(0, 0, 0, 0)
        self._dir_edit = QLineEdit()
        self._dir_edit.setPlaceholderText(os.path.expanduser("~/Documents/projects"))
        dir_hl.addWidget(self._dir_edit)
        browse_btn = QPushButton("…")
        browse_btn.setFixedWidth(32)
        browse_btn.clicked.connect(self._browse_dir)
        dir_hl.addWidget(browse_btn)
        proj_form.addRow("Base directory:", dir_row)

        create_btn = QPushButton("Create / Open Project")
        create_btn.setProperty("primary", "true")
        create_btn.clicked.connect(self._create_project)
        proj_form.addRow("", create_btn)

        layout.addWidget(proj_box)

        # ── CRS group ─────────────────────────────────────────────────────
        crs_box = QGroupBox("Coordinate Reference System")
        crs_form = QFormLayout(crs_box)
        crs_form.setSpacing(8)

        self._crs_combo = QComboBox()
        for label in CRS_OPTIONS:
            self._crs_combo.addItem(label)
        self._crs_combo.currentTextChanged.connect(self._on_crs_changed)
        crs_form.addRow("CRS:", self._crs_combo)

        self._custom_crs_edit = QLineEdit()
        self._custom_crs_edit.setPlaceholderText("EPSG:XXXXX")
        self._custom_crs_edit.setVisible(False)
        crs_form.addRow("Custom EPSG:", self._custom_crs_edit)

        layout.addWidget(crs_box)

        # ── AOI group ─────────────────────────────────────────────────────
        aoi_box = QGroupBox("Area of Interest (AOI)")
        aoi_form = QFormLayout(aoi_box)
        aoi_form.setSpacing(8)

        self._aoi_label = QLabel("Draw a rectangle on the map →")
        self._aoi_label.setStyleSheet("color:#aaa;")
        aoi_form.addRow("", self._aoi_label)

        layout.addWidget(aoi_box)

        # ── DEM group ─────────────────────────────────────────────────────
        dem_box = QGroupBox("DEM Download (OpenTopography)")
        dem_form = QFormLayout(dem_box)
        dem_form.setSpacing(8)

        self._dem_type_combo = QComboBox()
        for label in DEM_OPTIONS:
            self._dem_type_combo.addItem(label)
        dem_form.addRow("DEM type:", self._dem_type_combo)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("Get a free key at portal.opentopography.org")
        dem_form.addRow("API key:", self._api_key_edit)

        self._download_btn = QPushButton("Download DEM")
        self._download_btn.setProperty("primary", "true")
        self._download_btn.setEnabled(False)
        self._download_btn.clicked.connect(self._download_dem)
        dem_form.addRow("", self._download_btn)

        self._dem_status_label = QLabel("No DEM downloaded yet.")
        self._dem_status_label.setStyleSheet("color:#aaa; font-size:11px;")
        self._dem_status_label.setWordWrap(True)
        dem_form.addRow("", self._dem_status_label)

        layout.addWidget(dem_box)
        layout.addStretch()

        # Restore state into controls
        self.refresh_from_state()
        return self._form

    def on_activated(self) -> None:
        """Load the AOI map into the centre Map tab."""
        self._ensure_map_widget()
        self._mw.set_map_widget(self._map_widget)
        self._mw.show_map_tab()

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state
        if s.project_name:
            self._name_edit.setText(s.project_name)
        if s.project_dir:
            parent = os.path.dirname(s.project_dir)
            self._dir_edit.setText(parent)
        if s.dem_path:
            self._dem_status_label.setText(f"✅ {os.path.basename(s.dem_path)}")
            self._dem_status_label.setStyleSheet("color:#2ecc71; font-size:11px;")
        if s.bbox:
            b = s.bbox
            self._aoi_label.setText(
                f"N {b['north']:.4f}°  S {b['south']:.4f}°\n"
                f"W {b['west']:.4f}°  E {b['east']:.4f}°"
            )
            self._aoi_label.setStyleSheet("color:#2ecc71;")
            self._download_btn.setEnabled(True)
        # Restore CRS combo
        for label, code in CRS_OPTIONS.items():
            if code == s.crs:
                self._crs_combo.setCurrentText(label)
                break

    # ──────────────────────────────────────────────────────────────────────────
    # Map widget setup
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_map_widget(self):
        if self._map_widget is not None:
            return
        self._map_widget = MapWidget()
        self._map_widget.bbox_drawn.connect(self._on_bbox_drawn)
        # Load a default view centred on Umhlanga
        centre = (-29.71, 31.06)
        bbox = self._state.bbox
        html = MapWidget.build_aoi_map(centre=centre, existing_bbox=bbox)
        self._map_widget.load_map(html)

    @pyqtSlot(dict)
    def _on_bbox_drawn(self, bbox: dict):
        self._state.bbox = bbox
        self._state.save()
        b = bbox
        self._aoi_label.setText(
            f"N {b['north']:.4f}°  S {b['south']:.4f}°\n"
            f"W {b['west']:.4f}°  E {b['east']:.4f}°"
        )
        self._aoi_label.setStyleSheet("color:#2ecc71;")
        self._download_btn.setEnabled(True)
        self.log(
            f"AOI set: N={b['north']:.4f} S={b['south']:.4f} "
            f"W={b['west']:.4f} E={b['east']:.4f}", "ok"
        )
        self._mw.refresh_workflow_list()

    # ──────────────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────────────

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Base Directory", os.path.expanduser("~")
        )
        if path:
            self._dir_edit.setText(path)

    def _create_project(self):
        name = self._name_edit.text().strip()
        base = self._dir_edit.text().strip() or os.path.expanduser("~/Documents/projects")
        if not name:
            self.log("Enter a project name first.", "warn")
            return

        project_dir = os.path.join(base, name)
        for sub in ["rasters", "parameter_files", "forcing_variables", "results"]:
            os.makedirs(os.path.join(project_dir, sub), exist_ok=True)

        self._state.project_name = name
        self._state.project_dir  = project_dir
        self._state.save()
        self._mw.refresh_workflow_list()
        self.log(f"Project created at: {project_dir}", "ok")

    def _on_crs_changed(self, label: str):
        code = CRS_OPTIONS.get(label, "EPSG:32736")
        if code == "custom":
            self._custom_crs_edit.setVisible(True)
        else:
            self._custom_crs_edit.setVisible(False)
            self._state.crs = code

    def _download_dem(self):
        if not self._state.project_dir:
            self.log("Create a project first.", "warn")
            return
        if not self._state.bbox:
            self.log("Draw an AOI rectangle on the map first.", "warn")
            return
        key = self._api_key_edit.text().strip()
        if not key:
            self.log("Enter an OpenTopography API key.", "warn")
            return

        dem_label = self._dem_type_combo.currentText()
        dem_type  = DEM_OPTIONS.get(dem_label, "SRTMGL1")
        self._state.ot_api_key = key
        self._state.dem_type   = dem_type

        worker = DemWorker(self._state, task="download")
        worker.log_message.connect(lambda m: self.log(m))
        self.start_worker(worker)
        self._download_btn.setEnabled(False)
        self._dem_status_label.setText("Downloading…")
        self.set_status("Downloading DEM from OpenTopography…")

        # Re-enable button after worker finishes (connected via main_window)
        worker.finished.connect(lambda _: self._download_btn.setEnabled(True))
        worker.error.connect(lambda _: self._download_btn.setEnabled(True))
