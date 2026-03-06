"""
gui/app.py
==========
MainWindow — the top-level QMainWindow that hosts:
  - Left dock:   QListWidget  (10 workflow steps with ✅/⬜ icons)
  - Centre:      QTabWidget   (Map | Raster | Charts)
  - Right dock:  QScrollArea  (active panel's parameter form)
  - Bottom dock: LogDock      (timestamped processing messages)
  - Status bar:  QProgressBar + step label
"""

import json
import os

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QFont, QIcon, QColor
from PyQt6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QScrollArea, QSplitter, QStackedWidget,
    QTabWidget, QVBoxLayout, QWidget,
)

from gui.state import ProjectState
from gui.widgets.log_dock import LogDock
from gui.widgets.map_view import MapView
from gui.widgets.gis_canvas import GISCanvas
from gui.widgets.layers_dock import LayersDock
from gui.widgets.workflow_delegate import WorkflowDelegate

# Panels (imported lazily to avoid circular imports at module level)
# Step numbers are rendered by WorkflowDelegate — keep titles clean.
PANEL_TITLES = [
    "Study Area",
    "DEM Processing",
    "Watershed",
    "Stream Network",
    "Soil Parameters",
    "Land Cover",
    "Parameter Files",
    "Forcing Data",
    "Run Model",
    "Results",
]


def _load_panel_class(idx: int):
    """Lazily import panel classes to keep startup time low."""
    modules = [
        ("gui.panels.p01_study_area",    "StudyAreaPanel"),
        ("gui.panels.p02_dem_processing","DEMProcessingPanel"),
        ("gui.panels.p03_watershed",     "WatershedPanel"),
        ("gui.panels.p04_stream_network","StreamNetworkPanel"),
        ("gui.panels.p05_soil_params",   "SoilParametersPanel"),
        ("gui.panels.p06_land_cover",    "LandCoverPanel"),
        ("gui.panels.p07_parameter_files","ParameterFilesPanel"),
        ("gui.panels.p08_forcing_data",  "ForcingDataPanel"),
        ("gui.panels.p09_run_model",     "RunModelPanel"),
        ("gui.panels.p10_results",       "ResultsPanel"),
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._state  = ProjectState()
        self._panels: list = [None] * 10   # panel instances, created on first activation
        self._active_idx = 0
        self._worker = None   # currently running BaseWorker (one at a time)

        self.setWindowTitle("PyTOPKAPI GUI")
        self.setMinimumSize(1280, 780)
        self.resize(1440, 860)

        self._build_ui()
        self._build_menu()

        # Auto-reload last project if it still exists
        last = _load_recent()
        if last and os.path.exists(os.path.join(last, "project_state.json")):
            try:
                self._state = ProjectState.load(last)
                self.refresh_workflow_list()
                self._layers_dock.refresh_from_state(self._state)
                self._sync_gis_canvas_crs()
                self._log_dock.append_line(
                    f"Resumed project: {self._state.project_name or last}", "ok"
                )
            except Exception:
                pass

        self._activate_panel(0)
        if not self._state.project_name:
            self._log_dock.append_line(
                "PyTOPKAPI GUI ready. Create or open a project to begin.", "ok"
            )

    # ══════════════════════════════════════════════════════════════════════════
    #  UI construction
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── Central area ─────────────────────────────────────────────────────
        self._centre_tabs = QTabWidget()
        self._centre_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._centre_tabs.setDocumentMode(True)

        # Tab 0: Map — persistent MapView (toolbar + swappable Folium widget)
        self._map_view = MapView()
        self._centre_tabs.addTab(self._map_view, "Map")

        # Tab 1: Layers — persistent GISCanvas (georeferenced raster + vector)
        self._gis_canvas = GISCanvas()
        self._centre_tabs.addTab(self._gis_canvas, "Layers")

        # Tab 2: Raster — swappable intermediate view used by processing panels
        self._raster_placeholder = QLabel("No raster to display yet.")
        self._raster_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._raster_placeholder.setStyleSheet("color:#888; font-size:14px;")
        self._centre_tabs.addTab(self._raster_placeholder, "Raster")

        # Tab 3: Charts — populated by panels via set_chart_widget()
        self._chart_placeholder = QLabel("No chart to display yet.")
        self._chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_placeholder.setStyleSheet("color:#888; font-size:14px;")
        self._centre_tabs.addTab(self._chart_placeholder, "Charts")

        self.setCentralWidget(self._centre_tabs)

        # ── Left dock — workflow list ─────────────────────────────────────────
        self._workflow_list = QListWidget()
        self._workflow_list.setSpacing(0)
        self._workflow_list.setFixedWidth(210)
        self._workflow_list.setItemDelegate(WorkflowDelegate(self._workflow_list))
        self._populate_workflow_list()
        self._workflow_list.currentRowChanged.connect(self._activate_panel)

        # Project info label below the list
        self._project_label = QLabel("No project open")
        self._project_label.setWordWrap(True)
        self._project_label.setObjectName("projectLabel")

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(self._workflow_list)
        left_layout.addWidget(self._project_label)

        left_dock = QDockWidget("Workflow")
        left_dock.setWidget(left_widget)
        left_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        left_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        # ── Layers dock — below the workflow list ──────────────────────────────
        self._layers_dock = LayersDock(self)
        self._layers_dock.raster_selected.connect(self._show_layer_raster)
        self._layers_dock.set_as_overlay.connect(self._set_layer_as_overlay)
        self._layers_dock.layer_visibility_changed.connect(self._on_layer_visibility_changed)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._layers_dock)
        self.splitDockWidget(left_dock, self._layers_dock, Qt.Orientation.Vertical)

        # ── Right dock — properties panel ────────────────────────────────────
        self._props_scroll = QScrollArea()
        self._props_scroll.setWidgetResizable(True)
        self._props_scroll.setMinimumWidth(320)
        self._props_scroll.setMaximumWidth(420)

        right_dock = QDockWidget("Properties")
        right_dock.setWidget(self._props_scroll)
        right_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        right_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, right_dock)

        # ── Bottom dock — log ────────────────────────────────────────────────
        self._log_dock = LogDock(self)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)

        # ── Status bar ────────────────────────────────────────────────────────
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

        # ── File menu ─────────────────────────────────────────────────────────
        file_menu = menu.addMenu("&File")

        new_act = QAction("&New Project…", self)
        new_act.setShortcut("Ctrl+N")
        new_act.triggered.connect(self._new_project)
        file_menu.addAction(new_act)

        open_act = QAction("&Open Project…", self)
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

        # ── Help menu ─────────────────────────────────────────────────────────
        help_menu = menu.addMenu("&Help")
        about_act = QAction("&About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    # ══════════════════════════════════════════════════════════════════════════
    #  Workflow list
    # ══════════════════════════════════════════════════════════════════════════

    def _populate_workflow_list(self):
        self._workflow_list.clear()
        for i, title in enumerate(PANEL_TITLES):
            item = QListWidgetItem(title)
            done = self._state.step_complete(i)
            item.setData(Qt.ItemDataRole.UserRole, done)
            item.setToolTip("Complete" if done else "Not yet complete")
            self._workflow_list.addItem(item)

    def refresh_workflow_list(self):
        """Refresh step completion state after state changes."""
        for i in range(self._workflow_list.count()):
            item = self._workflow_list.item(i)
            done = self._state.step_complete(i)
            item.setData(Qt.ItemDataRole.UserRole, done)
            item.setToolTip("Complete" if done else "Not yet complete")
        self._workflow_list.update()
        # Persist the last-used project dir
        if self._state.project_dir:
            _save_recent(self._state.project_dir)
        # Update project info label
        if self._state.project_name:
            cells = f"  ·  {self._state.n_cells:,} cells" if self._state.n_cells else ""
            self._project_label.setText(f"  {self._state.project_name}{cells}")
        else:
            self._project_label.setText("  No project open")

    # ══════════════════════════════════════════════════════════════════════════
    #  Panel activation
    # ══════════════════════════════════════════════════════════════════════════

    def _activate_panel(self, idx: int):
        if idx < 0:
            return
        self._active_idx = idx

        # Create panel on first activation
        if self._panels[idx] is None:
            try:
                cls = _load_panel_class(idx)
                panel = cls(self._state, self)
                self._panels[idx] = panel
            except Exception as exc:
                self._log_dock.append_line(f"Panel load error: {exc}", "error")
                return

        panel = self._panels[idx]

        # Release the current widget WITHOUT deleting it (it's cached by its panel).
        # setWidget() would delete the old widget, corrupting the next panel switch.
        self._props_scroll.takeWidget()
        self._props_scroll.setWidget(panel.build_form())

        # Tell the panel it's now active (loads map, raster, etc.)
        panel.on_activated()

        # Keep list selection in sync (if called programmatically)
        self._workflow_list.blockSignals(True)
        self._workflow_list.setCurrentRow(idx)
        self._workflow_list.blockSignals(False)

    def get_active_panel(self):
        return self._panels[self._active_idx]

    # ══════════════════════════════════════════════════════════════════════════
    #  Worker management
    # ══════════════════════════════════════════════════════════════════════════

    def start_worker(self, worker):
        """Connect standard signals and start a background worker."""
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
        """Apply state patches, save, refresh UI."""
        for key, value in updates.items():
            setattr(self._state, key, value)
        self._state.save()
        if self._state.project_dir:
            _save_recent(self._state.project_dir)
        self.refresh_workflow_list()
        self._layers_dock.refresh_from_state(self._state)
        self._sync_gis_canvas_crs()
        panel = self.get_active_panel()
        if panel is not None:
            panel.refresh_from_state()
        self._progress_bar.setVisible(False)
        self._status_label.setText("Ready")

    def _on_worker_error(self, msg: str):
        self._log_dock.append_line(msg, "error")
        QMessageBox.critical(self, "Error", msg)
        self._progress_bar.setVisible(False)
        self._status_label.setText("Error — see log")

    def set_status(self, msg: str):
        self._status_label.setText(msg)

    def _sync_gis_canvas_crs(self) -> None:
        """Pass project CRS to GISCanvas so vectors reproject correctly."""
        crs = getattr(self._state, "crs", None)
        if crs:
            self._gis_canvas.set_project_crs(crs)

    # ══════════════════════════════════════════════════════════════════════════
    #  Central tab helpers (called by panels)
    # ══════════════════════════════════════════════════════════════════════════

    # Tab indices
    _TAB_MAP     = 0
    _TAB_LAYERS  = 1
    _TAB_RASTER  = 2
    _TAB_CHARTS  = 3

    def set_map_widget(self, widget: QWidget):
        """Load a MapWidget into the persistent MapView toolbar container."""
        self._map_view.set_map_widget(widget)
        self._centre_tabs.setCurrentIndex(self._TAB_MAP)

    def set_map_hint(self, msg: str) -> None:
        """Show an instruction hint in the map toolbar (e.g. 'Click to place outlet')."""
        self._map_view.set_hint(msg)

    def clear_map_hint(self) -> None:
        self._map_view.clear_hint()

    def set_raster_widget(self, widget: QWidget):
        """Replace the Raster tab content (used by processing panels for intermediate views)."""
        self._centre_tabs.removeTab(self._TAB_RASTER)
        self._centre_tabs.insertTab(self._TAB_RASTER, widget, "Raster")
        self._centre_tabs.setCurrentIndex(self._TAB_RASTER)

    def set_chart_widget(self, widget: QWidget):
        """Replace the Charts tab content."""
        self._centre_tabs.removeTab(self._TAB_CHARTS)
        self._centre_tabs.insertTab(self._TAB_CHARTS, widget, "Charts")
        self._centre_tabs.setCurrentIndex(self._TAB_CHARTS)

    def show_map_tab(self):
        self._centre_tabs.setCurrentIndex(self._TAB_MAP)

    def show_layers_tab(self):
        self._centre_tabs.setCurrentIndex(self._TAB_LAYERS)

    def show_raster_tab(self):
        self._centre_tabs.setCurrentIndex(self._TAB_RASTER)

    def show_chart_tab(self):
        self._centre_tabs.setCurrentIndex(self._TAB_CHARTS)

    def _on_layer_visibility_changed(
        self, name: str, path: str, cmap: str, ltype: str, visible: bool
    ) -> None:
        """Toggle a layer in GISCanvas when the LayersDock checkbox changes."""
        if not path:
            return
        if visible:
            if self._gis_canvas.has_layer(name):
                self._gis_canvas.show_layer(name)
            elif ltype == "raster":
                self._gis_canvas.add_raster(name, path, cmap or "terrain")
            else:
                self._gis_canvas.add_vector(name, path)
        else:
            self._gis_canvas.hide_layer(name)
        # Switch to Layers tab so the user sees the result
        self.show_layers_tab()

    def _show_layer_raster(self, name: str, path: str, cmap: str) -> None:
        """Called by LayersDock single-click — toggle layer into GISCanvas."""
        if self._gis_canvas.has_layer(name):
            self._gis_canvas.show_layer(name)
        else:
            self._gis_canvas.add_raster(name, path, cmap or "terrain")
        self.show_layers_tab()

    def _set_layer_as_overlay(self, name: str, path: str, cmap: str) -> None:
        """Called by LayersDock right-click → 'Set as Overlay' — adds to Raster tab."""
        raster_widget = self._centre_tabs.widget(self._TAB_RASTER)
        if raster_widget and hasattr(raster_widget, "set_overlay"):
            raster_widget.set_overlay(name, path, cmap)
            self.show_raster_tab()
        else:
            from gui.widgets.raster_canvas import RasterCanvas
            canvas = RasterCanvas()
            canvas.show_file(path, title=name, cmap=cmap)
            self._centre_tabs.removeTab(self._TAB_RASTER)
            self._centre_tabs.insertTab(self._TAB_RASTER, canvas, "Raster")
            self.show_raster_tab()

    # ══════════════════════════════════════════════════════════════════════════
    #  File menu actions
    # ══════════════════════════════════════════════════════════════════════════

    def _new_project(self):
        """Open Step 1 — the panel itself handles directory creation."""
        self._activate_panel(0)
        self._workflow_list.setCurrentRow(0)

    def _open_project(self):
        """Load a project from an existing project_state.json."""
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
            # Reset all panels so they re-read fresh state on next activation
            self._panels = [None] * 10
            self._gis_canvas.clear()
            self.refresh_workflow_list()
            self._layers_dock.refresh_from_state(self._state)
            self._sync_gis_canvas_crs()
            self._activate_panel(0)
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
            "Built with PyQt6 · pysheds · rasterio · h5py<br>"
            "Model: <a href='https://github.com/JustinPringle/PyTOPKAPI'>"
            "github.com/JustinPringle/PyTOPKAPI</a>"
        )
