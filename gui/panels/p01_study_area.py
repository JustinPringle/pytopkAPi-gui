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

from PyQt6.QtCore import QUrl, pyqtSlot
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from gui.panels import BasePanel
from gui.workers.dem_worker import DemWorker


CRS_OPTIONS = {
    "UTM Zone 36S  (EPSG:32736) — KwaZulu-Natal": "EPSG:32736",
    "UTM Zone 35S  (EPSG:32735)": "EPSG:32735",
    "Lo31 / Cape  (EPSG:22235)": "EPSG:22235",
    "WGS 84  (EPSG:4326) — geographic": "EPSG:4326",
    "Custom…": "custom",
}

DEM_OPTIONS = {
    # value prefix "tiles:" → use free AWS tile download (no key needed)
    # value prefix "ot:"    → use OpenTopography API (API key required)
    "SRTM 1-arc-sec 30m  (Free tiles — no key)  ★ recommended": "tiles:SRTMGL1",
    "SRTMGL1 via OpenTopography  (API key required)":            "ot:SRTMGL1",
    "SRTMGL3 90m via OpenTopography  (API key required)":        "ot:SRTMGL3",
    "COP-DEM GLO-30 via OpenTopography  (API key required)":     "ot:COP30",
    "NASADEM via OpenTopography  (API key required)":            "ot:NASADEM",
}


class StudyAreaPanel(BasePanel):
    """Panel for Step 1: project setup + AOI + DEM download."""

    def __init__(self, state, main_window, parent=None):
        super().__init__(state, main_window, parent)

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

        self._clear_aoi_btn = QPushButton("Clear AOI")
        self._clear_aoi_btn.setToolTip("Remove the drawn AOI rectangle and start over")
        self._clear_aoi_btn.setVisible(False)
        self._clear_aoi_btn.clicked.connect(self._clear_aoi)
        aoi_form.addRow("", self._clear_aoi_btn)

        layout.addWidget(aoi_box)

        # ── DEM group ─────────────────────────────────────────────────────
        dem_box = QGroupBox("DEM Download (OpenTopography)")
        dem_form = QFormLayout(dem_box)
        dem_form.setSpacing(8)

        self._dem_type_combo = QComboBox()
        for label in DEM_OPTIONS:
            self._dem_type_combo.addItem(label)
        dem_form.addRow("DEM type:", self._dem_type_combo)

        # API key row: [text field] [Show/Hide] [Get free key →]
        key_row = QWidget()
        key_hl  = QHBoxLayout(key_row)
        key_hl.setContentsMargins(0, 0, 0, 0)
        key_hl.setSpacing(4)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("Optional — leave blank to download anonymously")
        # Auto-save key whenever the user finishes editing
        self._api_key_edit.editingFinished.connect(self._save_api_key)
        key_hl.addWidget(self._api_key_edit, stretch=1)

        self._show_key_btn = QPushButton("Show")
        self._show_key_btn.setFixedWidth(46)
        self._show_key_btn.setCheckable(True)
        self._show_key_btn.toggled.connect(self._toggle_key_visibility)
        key_hl.addWidget(self._show_key_btn)

        get_key_btn = QPushButton("Get free key →")
        get_key_btn.setToolTip("Opens portal.opentopography.org/requestApiKey in your browser")
        get_key_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(
                QUrl("https://portal.opentopography.org/requestApiKey")
            )
        )
        key_hl.addWidget(get_key_btn)

        dem_form.addRow("API key:", key_row)

        key_hint = QLabel(
            "API key is optional.  Anonymous downloads work but are rate-limited.\n"
            "A free key removes the limit — click 'Get free key →' above."
        )
        key_hint.setStyleSheet("color:#aaa; font-size:11px;")
        key_hint.setWordWrap(True)
        dem_form.addRow("", key_hint)

        self._download_btn = QPushButton("Download DEM")
        self._download_btn.setProperty("primary", "true")
        self._download_btn.setToolTip(
            "Draw a rectangle on the map to set the AOI, then click here to download."
        )
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
        """Set up the shared map for AOI rectangle drawing."""
        mv = self._mw._map_view
        mv.clear_all_overlays()
        mv.set_draw_mode('rectangle')
        self._mw.set_map_hint("Draw a rectangle on the map to define the Area of Interest")
        self._mw.show_map_tab()

        if self._state.bbox:
            b = self._state.bbox
            mv.add_rectangle(b['south'], b['west'], b['north'], b['east'])
            mv.fit_bounds(b['south'], b['west'], b['north'], b['east'])

    def refresh_from_state(self) -> None:
        if self._form is None:
            return
        s = self._state
        if s.project_name:
            self._name_edit.setText(s.project_name)
        if s.project_dir:
            parent = os.path.dirname(s.project_dir)
            self._dir_edit.setText(parent)
        # Restore saved API key so user doesn't have to re-enter it each session
        if s.ot_api_key and not self._api_key_edit.text():
            self._api_key_edit.setText(s.ot_api_key)
        if s.dem_path:
            self._dem_status_label.setText(
                f"✅ {os.path.basename(s.dem_path)}\n"
                "Click 'Process DEM' in the ribbon to continue."
            )
            self._dem_status_label.setStyleSheet("color:#2ecc71; font-size:11px;")
        if s.bbox:
            b = s.bbox
            self._aoi_label.setText(
                f"N {b['north']:.4f}°  S {b['south']:.4f}°\n"
                f"W {b['west']:.4f}°  E {b['east']:.4f}°"
            )
            self._aoi_label.setStyleSheet("color:#2ecc71;")
        # Restore CRS combo
        for label, code in CRS_OPTIONS.items():
            if code == s.crs:
                self._crs_combo.setCurrentText(label)
                break

    # ──────────────────────────────────────────────────────────────────────────
    # Draw signal handler (routed from MainWindow)
    # ──────────────────────────────────────────────────────────────────────────

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
        self.log(
            f"AOI set: N={b['north']:.4f} S={b['south']:.4f} "
            f"W={b['west']:.4f} E={b['east']:.4f}", "ok"
        )
        self._mw.set_map_hint("AOI set — scroll down to download the DEM")
        self._mw.refresh_workflow_list()

    # ──────────────────────────────────────────────────────────────────────────
    # Slots
    # ──────────────────────────────────────────────────────────────────────────

    def _toggle_key_visibility(self, checked: bool):
        """Toggle API key between hidden (password) and visible (normal) text."""
        if checked:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._show_key_btn.setText("Hide")
        else:
            self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._show_key_btn.setText("Show")

    def _save_api_key(self):
        """Persist API key to state whenever the user finishes editing."""
        key = self._api_key_edit.text().strip()
        if key:
            self._state.ot_api_key = key
            self._state.save()

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Base Directory", os.path.expanduser("~")
        )
        if path:
            self._dir_edit.setText(path)

    def _create_project(self):
        from gui.state import ProjectState

        name = self._name_edit.text().strip()
        base = self._dir_edit.text().strip() or os.path.expanduser("~/Documents/projects")
        if not name:
            self.log("Enter a project name first.", "warn")
            return

        project_dir = os.path.join(base, name)
        is_new = (project_dir != self._state.project_dir)

        for sub in ["rasters", "parameter_files", "forcing_variables", "results"]:
            os.makedirs(os.path.join(project_dir, sub), exist_ok=True)

        if is_new:
            # Preserve cross-project user preferences
            saved_api_key = self._state.ot_api_key
            saved_crs     = self._state.crs

            state_file = os.path.join(project_dir, "project_state.json")
            if os.path.exists(state_file):
                fresh = ProjectState.load(project_dir)
                self.log(f"Opened existing project: {project_dir}", "ok")
            else:
                fresh = ProjectState(
                    project_name=name,
                    project_dir=project_dir,
                    crs=saved_crs,
                    ot_api_key=saved_api_key,
                )
                self.log(f"New project created at: {project_dir}", "ok")

            # Reset the shared state object in-place so all panels see the change
            self._state.__dict__.update(vars(fresh))
        else:
            self._state.project_name = name
            self._state.project_dir  = project_dir
            self.log(f"Project re-opened: {project_dir}", "ok")

        self._state.save()
        self.refresh_from_state()
        self.on_activated()
        self._mw.refresh_workflow_list()

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
        if key:
            self._state.ot_api_key = key

        dem_label = self._dem_type_combo.currentText()
        dem_value = DEM_OPTIONS.get(dem_label, "tiles:SRTMGL1")

        # Route: "tiles:*" → free AWS tile download; "ot:*" → OpenTopography API
        if dem_value.startswith("tiles:"):
            self._state.dem_type = dem_value[len("tiles:"):]
            worker_task = "download_tiles"
            status_msg  = "Downloading SRTM tiles from AWS (free)…"
        else:
            self._state.dem_type = dem_value[len("ot:"):] if dem_value.startswith("ot:") else dem_value
            worker_task = "download"
            status_msg  = "Downloading DEM from OpenTopography…"

        worker = DemWorker(self._state, task=worker_task)
        self.start_worker(worker)
        self._dem_status_label.setText("Downloading…")
        self.set_status(status_msg)
