"""
gui/app.py
==========
MainWindow — the top-level QMainWindow that hosts:
  - Top:      WorkflowRibbon (5-stage tabs + tool buttons per stage)
  - Left:     LayersDock     (QGIS-style layer tree with visibility toggles)
  - Centre:   QTabWidget     (Map | Charts)
  - Right:    FormDock       (inline panel form — replaces floating dialogs)
  - Bottom:   LogDock        (timestamped processing messages)
  - Status:   QProgressBar + status label

Panel forms are shown inline in the right dock widget.
Rasters and vectors are overlaid on the Leaflet map via image/GeoJSON overlays.
"""

import json
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QLabel,
    QMainWindow, QMessageBox,
    QProgressBar, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from gui.state import ProjectState
from gui.widgets.log_dock import LogDock
from gui.widgets.map_view import MapView
from gui.widgets.layers_dock import LayersDock
from gui.widgets.ribbon import (
    WorkflowRibbon, STAGE_TITLES, STAGE_TOOLS, STAGE_FIRST_PANEL, PANEL_TITLES,
)


def _load_panel_class(idx: int):
    """Lazily import panel classes by old panel index (0-9)."""
    modules = [
        ("gui.panels.p01_study_area",     "StudyAreaPanel"),
        ("gui.panels.p02_dem_processing", "DEMProcessingPanel"),
        ("gui.panels.p03_watershed",      "WatershedPanel"),
        ("gui.panels.p04_stream_network", "StreamNetworkPanel"),
        ("gui.panels.p05_soil_params",    "SoilParametersPanel"),
        ("gui.panels.p06_land_cover",     "LandCoverPanel"),
        ("gui.panels.p07_parameter_files","ParameterFilesPanel"),
        ("gui.panels.p08_forcing_data",   "ForcingDataPanel"),
        ("gui.panels.p09_run_model",      "RunModelPanel"),
        ("gui.panels.p10_results",        "ResultsPanel"),
    ]
    mod_name, cls_name = modules[idx]
    import importlib
    mod = importlib.import_module(mod_name)
    return getattr(mod, cls_name)


_RECENT_FILE = os.path.join(os.path.expanduser("~"), ".pytopkapi_gui_recent.json")


def _save_recent(project_dir: str) -> None:
    try:
        with open(_RECENT_FILE, "w") as f:
            json.dump({"last_project_dir": project_dir}, f)
    except Exception:
        pass


def _load_recent() -> "str | None":
    try:
        with open(_RECENT_FILE) as f:
            return json.load(f).get("last_project_dir")
    except Exception:
        return None


# Dark theme stylesheet for the form dock
_FORM_DOCK_STYLE = """
    QDockWidget {
        background: #252729;
        color: #d4d4d4;
    }
    QDockWidget::title {
        background: #2b2d30;
        padding: 6px;
        font-weight: bold;
        color: #d4d4d4;
    }
"""

# Stylesheet applied to the form container inside the dock
_FORM_STYLE = """
    QWidget#formContainer {
        background: #252729;
    }
    QGroupBox {
        font-weight: bold;
        border: 1px solid #3a3d40;
        border-radius: 4px;
        margin-top: 12px;
        padding-top: 16px;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
        color: #cccccc;
    }
    QPushButton {
        background: #3c3f41;
        color: #d4d4d4;
        border: 1px solid #3a3d40;
        border-radius: 4px;
        padding: 6px 12px;
    }
    QPushButton:hover {
        background: #4e5254;
        color: #ffffff;
    }
    QPushButton[primary="true"] {
        background: #1a6fc4;
        border-color: #1a6fc4;
        color: #ffffff;
    }
    QPushButton[primary="true"]:hover {
        background: #2080d4;
    }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
        background: #1e1e1e;
        color: #d4d4d4;
        border: 1px solid #3a3d40;
        border-radius: 3px;
        padding: 4px;
    }
    QLabel { color: #d4d4d4; }
    QLabel[role="title"] {
        font-size: 16px;
        font-weight: bold;
        color: #ffffff;
        padding-bottom: 4px;
    }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._state  = ProjectState()
        self._panels: list = [None] * 10
        self._active_panel_idx = -1   # old panel index (0-9)
        self._active_stage_idx = -1   # stage index (0-4)
        self._worker = None

        self.setWindowTitle("PyTOPKAPI GUI")
        self.setMinimumSize(1280, 780)
        self.resize(1440, 860)

        self._build_ui()
        self._build_menu()

        # Auto-reload last project
        last = _load_recent()
        if last and os.path.exists(os.path.join(last, "project_state.json")):
            try:
                self._state = ProjectState.load(last)
                self._refresh_ribbon_completion()
                self._layers_dock.refresh_from_state(self._state)
                self._log_dock.append_line(
                    f"Resumed project: {self._state.project_name or last}", "ok"
                )
            except Exception:
                pass

        if not self._state.project_name:
            self._log_dock.append_line(
                "PyTOPKAPI GUI ready. Select a stage from the ribbon to begin.",
                "ok",
            )
            self._map_view.set_hint(
                "Welcome — click 'Setup' in the ribbon above to create a project"
            )

    # ======================================================================
    #  UI construction
    # ======================================================================

    def _build_ui(self):
        # -- Central area: ribbon + tabs -----------------------------------
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Workflow ribbon (top)
        self._ribbon = WorkflowRibbon()
        self._ribbon.step_selected.connect(self._on_stage_selected)
        self._ribbon.panel_requested.connect(self._on_panel_requested)
        central_layout.addWidget(self._ribbon)

        # Tab widget: Map + Charts only
        self._centre_tabs = QTabWidget()
        self._centre_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._centre_tabs.setDocumentMode(True)

        # Tab 0: Map — ONE persistent MapWidget shared by all panels
        self._map_view = MapView()
        from gui.widgets.map_widget import MapWidget
        self._shared_map = MapWidget()
        self._shared_map.bbox_drawn.connect(self._on_map_bbox_drawn)
        self._shared_map.outlet_placed.connect(self._on_map_outlet_placed)
        self._shared_map.polygon_drawn.connect(self._on_map_polygon_drawn)
        self._shared_map.feature_clicked.connect(self._on_map_feature_clicked)
        html = MapWidget.build_base_map()
        self._shared_map.load_map(html)
        self._map_view.set_map_widget(self._shared_map)
        self._centre_tabs.addTab(self._map_view, "Map")

        # Tab 1: Charts
        self._chart_placeholder = QLabel("No chart to display yet.")
        self._chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_placeholder.setStyleSheet("color:#888; font-size:14px;")
        self._centre_tabs.addTab(self._chart_placeholder, "Charts")

        central_layout.addWidget(self._centre_tabs, stretch=1)
        self.setCentralWidget(central)

        # -- Left dock: Layers ---------------------------------------------
        self._layers_dock = LayersDock(self)
        self._layers_dock.raster_selected.connect(self._on_layer_selected)
        self._layers_dock.set_as_overlay.connect(self._on_overlay_requested)
        self._layers_dock.layer_visibility_changed.connect(
            self._on_layer_visibility_changed
        )
        self._layers_dock.layer_opacity_changed.connect(
            self._on_layer_opacity_changed
        )
        self._layers_dock.layer_limits_changed.connect(
            self._on_layer_limits_changed
        )
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._layers_dock)

        # -- Right dock: Form (replaces floating dialogs) ------------------
        self._form_dock = QDockWidget("Tool", self)
        self._form_dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self._form_dock.setMinimumWidth(380)
        self._form_dock.setStyleSheet(_FORM_DOCK_STYLE)

        # Persistent container inside a scroll area (never replaced by setWidget)
        self._form_container = QWidget()
        self._form_container.setObjectName("formContainer")
        self._form_container.setStyleSheet(_FORM_STYLE)
        self._form_container_layout = QVBoxLayout(self._form_container)
        self._form_container_layout.setContentsMargins(0, 0, 0, 0)
        self._form_container_layout.setSpacing(0)

        self._form_scroll = QScrollArea()
        self._form_scroll.setWidgetResizable(True)
        self._form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._form_scroll.setStyleSheet("QScrollArea { background: #252729; border: none; }")
        self._form_scroll.setWidget(self._form_container)
        self._form_dock.setWidget(self._form_scroll)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._form_dock)
        self._form_dock.setVisible(False)

        # -- Bottom dock: log ----------------------------------------------
        self._log_dock = LogDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)

        # -- Status bar ----------------------------------------------------
        self._status_label = QLabel("Ready")
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedWidth(200)
        self._progress_bar.setVisible(False)
        self.statusBar().addWidget(self._status_label)
        self.statusBar().addPermanentWidget(self._progress_bar)

    def _build_menu(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        new_act = QAction("&New Project...", self)
        new_act.setShortcut("Ctrl+N")
        new_act.triggered.connect(self._new_project)
        file_menu.addAction(new_act)

        open_act = QAction("&Open Project...", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self._open_project)
        file_menu.addAction(open_act)

        save_act = QAction("&Save Project", self)
        save_act.setShortcut("Ctrl+S")
        save_act.triggered.connect(lambda: self._state.save())
        file_menu.addAction(save_act)

        file_menu.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_act)

        help_menu = menu.addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    # ======================================================================
    #  Ribbon / panel activation
    # ======================================================================

    def _on_stage_selected(self, stage_idx: int):
        """Called when a stage tab is clicked. Activate first panel's map + form."""
        self._active_stage_idx = stage_idx
        if STAGE_TOOLS[stage_idx]:
            first_panel_idx = STAGE_FIRST_PANEL[stage_idx]
            self._ribbon.set_active_tool(first_panel_idx)
            self._activate_panel_map(first_panel_idx)
            self._show_panel_form(first_panel_idx)

    def _on_panel_requested(self, panel_idx: int):
        """Called when a tool button is clicked. Show that panel's form in dock."""
        self._ribbon.set_active_tool(panel_idx)
        self._activate_panel_map(panel_idx)
        self._show_panel_form(panel_idx)

    def _activate_panel_map(self, panel_idx: int):
        """Load a panel and run its on_activated() (sets up map), but don't show form."""
        if panel_idx < 0:
            return
        self._active_panel_idx = panel_idx

        if self._panels[panel_idx] is None:
            try:
                cls = _load_panel_class(panel_idx)
                panel = cls(self._state, self)
                self._panels[panel_idx] = panel
            except Exception as exc:
                self._log_dock.append_line(f"Panel load error: {exc}", "error")
                return

        panel = self._panels[panel_idx]
        # build_form() must run before on_activated() — some panels reference
        # form widgets (labels, spinboxes) during activation
        panel.build_form()
        panel.on_activated()

    def _show_panel_form(self, panel_idx: int):
        """Display a panel's form widget in the right dock."""
        if self._panels[panel_idx] is None:
            self._activate_panel_map(panel_idx)

        panel = self._panels[panel_idx]
        if panel is None:
            return

        form = panel.build_form()

        # Detach the current form from the container layout (don't delete it)
        while self._form_container_layout.count():
            item = self._form_container_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)

        # Add the new form into the container
        self._form_container_layout.addWidget(form)
        form.show()

        self._form_dock.setWindowTitle(PANEL_TITLES[panel_idx])
        self._form_dock.setVisible(True)
        self._form_dock.raise_()

        # Scroll to top and refresh
        self._form_scroll.verticalScrollBar().setValue(0)
        panel.refresh_from_state()

    def get_active_panel(self):
        if 0 <= self._active_panel_idx < len(self._panels):
            return self._panels[self._active_panel_idx]
        return None

    # ======================================================================
    #  Draw signal routing (shared map → active panel)
    # ======================================================================

    def _on_map_bbox_drawn(self, bbox: dict) -> None:
        panel = self.get_active_panel()
        if panel and hasattr(panel, '_on_bbox_drawn'):
            panel._on_bbox_drawn(bbox)

    def _on_map_outlet_placed(self, lat: float, lon: float) -> None:
        panel = self.get_active_panel()
        if panel and hasattr(panel, '_on_outlet_placed'):
            panel._on_outlet_placed(lat, lon)

    def _on_map_polygon_drawn(self, geojson: dict) -> None:
        panel = self.get_active_panel()
        if panel and hasattr(panel, '_on_polygon_drawn'):
            panel._on_polygon_drawn(geojson)

    def _on_map_feature_clicked(self, overlay_name: str, feature_json: str) -> None:
        panel = self.get_active_panel()
        if panel and hasattr(panel, '_on_feature_clicked'):
            panel._on_feature_clicked(overlay_name, feature_json)

    # ======================================================================
    #  Ribbon completion badges
    # ======================================================================

    def _refresh_ribbon_completion(self):
        for i in range(5):
            status = self._state.stage_status(i)
            self._ribbon.set_step_complete(i, status)
        if self._state.project_dir:
            _save_recent(self._state.project_dir)

    # Backwards-compatible alias used by panels
    def refresh_workflow_list(self):
        self._refresh_ribbon_completion()

    # ======================================================================
    #  Worker management
    # ======================================================================

    def start_worker(self, worker):
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.warning(self, "Busy", "A task is already running. Please wait.")
            return
        self._worker = worker
        worker.log_message.connect(self._log_dock.append_line)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)
        worker.start()

    def _on_progress(self, pct: int):
        self._progress_bar.setValue(pct)

    def _on_worker_finished(self, updates: dict):
        for key, value in updates.items():
            setattr(self._state, key, value)
        self._state.save()
        if self._state.project_dir:
            _save_recent(self._state.project_dir)
        self._refresh_ribbon_completion()
        self._layers_dock.refresh_from_state(self._state)
        panel = self.get_active_panel()
        if panel is not None:
            panel.refresh_from_state()
        self._progress_bar.setVisible(False)
        self._status_label.setText("Ready")

    def _on_worker_error(self, msg: str):
        self._log_dock.append_line(msg, "error")
        QMessageBox.critical(self, "Error", msg)
        self._progress_bar.setVisible(False)
        self._status_label.setText("Error - see log")

    def set_status(self, msg: str):
        self._status_label.setText(msg)

    # ======================================================================
    #  Central tab helpers (called by panels)
    # ======================================================================

    _TAB_MAP    = 0
    _TAB_CHARTS = 1

    def set_map_widget(self, widget: QWidget):
        """Load a MapWidget into the persistent MapView toolbar container."""
        self._map_view.set_map_widget(widget)
        self._centre_tabs.setCurrentIndex(self._TAB_MAP)

    def set_map_hint(self, msg: str) -> None:
        self._map_view.set_hint(msg)

    def clear_map_hint(self) -> None:
        self._map_view.clear_hint()

    def set_chart_widget(self, widget: QWidget):
        """Replace the Charts tab content."""
        self._centre_tabs.removeTab(self._TAB_CHARTS)
        self._centre_tabs.insertTab(self._TAB_CHARTS, widget, "Charts")
        self._centre_tabs.setCurrentIndex(self._TAB_CHARTS)

    # Backwards-compatible stubs for removed tabs — redirect to map
    def set_raster_widget(self, widget: QWidget):
        """No-op: Raster tab removed. Rasters are overlaid on the map."""
        self.show_map_tab()

    def show_map_tab(self):
        self._centre_tabs.setCurrentIndex(self._TAB_MAP)

    def show_layers_tab(self):
        self.show_map_tab()

    def show_raster_tab(self):
        self.show_map_tab()

    def show_chart_tab(self):
        self._centre_tabs.setCurrentIndex(self._TAB_CHARTS)

    # ======================================================================
    #  Layer visibility (overlay on the Leaflet map)
    # ======================================================================

    # Per-layer rendering overrides (state_attr → kwargs for add_raster_overlay).
    # Shaded relief is 3-band RGB from GRASS r.shade — render nearly opaque.
    _LAYER_RENDER_HINTS: dict[str, dict] = {
        "shaded_relief_path": {"alpha": 0.9},
    }

    def _on_layer_visibility_changed(
        self, name: str, path: str, cmap: str, ltype: str, visible: bool,
        attr: str = "",
    ) -> None:
        """Toggle a layer as an overlay on the Leaflet map."""
        if ltype == "basemap":
            self._map_view.toggle_basemap(visible)
            return
        if not path:
            return
        if visible:
            if ltype == "raster":
                limits = (self._state.layer_display_limits or {}).get(attr, {})
                hints = self._LAYER_RENDER_HINTS.get(attr, {})
                self._map_view.add_raster_overlay(
                    name, path, cmap or "terrain",
                    alpha=hints.get("alpha", 0.7),
                    vmin=limits.get("vmin"),
                    vmax=limits.get("vmax"),
                    state_attr=attr,
                )
            elif ltype == "vector":
                self._add_vector_to_map(name, path)
        else:
            self._map_view.toggle_overlay(name, False)

    def _on_layer_opacity_changed(self, name: str, opacity: float) -> None:
        """Update overlay opacity on the Leaflet map."""
        self._map_view.set_overlay_opacity(name, opacity)

    def _on_layer_limits_changed(self, attr: str, vmin, vmax) -> None:
        """Persist colour limits and re-render the affected overlay."""
        limits = dict(self._state.layer_display_limits or {})
        if vmin is None and vmax is None:
            limits.pop(attr, None)
        else:
            entry = {}
            if vmin is not None:
                entry["vmin"] = float(vmin)
            if vmax is not None:
                entry["vmax"] = float(vmax)
            limits[attr] = entry
        self._state.layer_display_limits = limits
        self._state.save()
        self._map_view.rerender_by_state_attr(attr, limits.get(attr, {}))

    def _on_layer_selected(self, name: str, path: str, cmap: str) -> None:
        """Layer single-click: add as overlay on map."""
        self._map_view.add_raster_overlay(name, path, cmap or "terrain")

    def _on_overlay_requested(self, name: str, path: str, cmap: str) -> None:
        """Layer right-click 'Overlay on Map'."""
        if cmap:
            self._map_view.add_raster_overlay(name, path, cmap)
        else:
            self._add_vector_to_map(name, path)

    def _add_vector_to_map(self, name: str, path: str) -> None:
        """Read a vector file and add as GeoJSON overlay on the map."""
        try:
            import geopandas as gpd
            gdf = gpd.read_file(path)
            if gdf.crs and not gdf.crs.is_geographic:
                gdf = gdf.to_crs("EPSG:4326")
            geojson_str = gdf.to_json()
            # Detect stream vectors — use Strahler-weighted line widths
            weight_col = ""
            if "strahler" in gdf.columns:
                weight_col = "strahler"
            self._map_view.add_vector_overlay(
                name, geojson_str,
                color="#00BFFF" if weight_col else "#FF6B35",
                weight=2,
                fill_opacity=0.0 if weight_col else 0.15,
                weight_column=weight_col,
            )
        except Exception as exc:
            self._log_dock.append_line(f"Vector overlay error: {exc}", "error")

    # ======================================================================
    #  File menu actions
    # ======================================================================

    def _new_project(self):
        self._ribbon.set_active_step(0)
        self._on_stage_selected(0)

    def _open_project(self):
        path = QFileDialog.getExistingDirectory(
            self, "Open Project Directory", os.path.expanduser("~")
        )
        if not path:
            return
        state_file = os.path.join(path, "project_state.json")
        if not os.path.exists(state_file):
            QMessageBox.warning(
                self, "Not a project",
                f"No project_state.json found in:\n{path}\n\n"
                "Select the root folder of an existing PyTOPKAPI GUI project."
            )
            return
        try:
            self._state = ProjectState.load(path)
            _save_recent(path)
            self._panels = [None] * 10
            self._refresh_ribbon_completion()
            self._layers_dock.refresh_from_state(self._state)
            self._log_dock.append_line(
                f"Opened project: {self._state.project_name or path}", "ok"
            )
        except Exception as exc:
            QMessageBox.critical(self, "Load error", str(exc))

    def _show_about(self):
        QMessageBox.about(
            self, "About PyTOPKAPI GUI",
            "<b>PyTOPKAPI GUI</b><br>"
            "A desktop application for setting up and running the "
            "PyTOPKAPI physically-based distributed hydrological model.<br><br>"
            "Built with PyQt6 . pysheds . rasterio . h5py<br>"
            "Model: <a href='https://github.com/JustinPringle/PyTOPKAPI'>"
            "github.com/JustinPringle/PyTOPKAPI</a>"
        )
