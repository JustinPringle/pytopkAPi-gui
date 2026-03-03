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

# Panels (imported lazily to avoid circular imports at module level)
PANEL_TITLES = [
    "1  Study Area",
    "2  DEM Processing",
    "3  Watershed",
    "4  Stream Network",
    "5  Soil Parameters",
    "6  Land Cover",
    "7  Parameter Files",
    "8  Forcing Data",
    "9  Run Model",
    "10  Results",
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
        self._activate_panel(0)
        self._log_dock.append_line("PyTOPKAPI GUI ready. Create or open a project to begin.", "ok")

    # ══════════════════════════════════════════════════════════════════════════
    #  UI construction
    # ══════════════════════════════════════════════════════════════════════════

    def _build_ui(self):
        # ── Central area ─────────────────────────────────────────────────────
        self._centre_tabs = QTabWidget()
        self._centre_tabs.setTabPosition(QTabWidget.TabPosition.North)
        self._centre_tabs.setDocumentMode(True)

        # Map tab — populated by MapWidget when panels need it
        self._map_placeholder = QLabel("Select a step to load the map.")
        self._map_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._map_placeholder.setStyleSheet("color:#888; font-size:14px;")
        self._centre_tabs.addTab(self._map_placeholder, "🗺  Map")

        # Raster tab — populated by RasterCanvas
        self._raster_placeholder = QLabel("No raster to display yet.")
        self._raster_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._raster_placeholder.setStyleSheet("color:#888; font-size:14px;")
        self._centre_tabs.addTab(self._raster_placeholder, "🖼  Raster")

        # Charts tab — populated by HydrographCanvas
        self._chart_placeholder = QLabel("No chart to display yet.")
        self._chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_placeholder.setStyleSheet("color:#888; font-size:14px;")
        self._centre_tabs.addTab(self._chart_placeholder, "📈  Charts")

        self.setCentralWidget(self._centre_tabs)

        # ── Left dock — workflow list ─────────────────────────────────────────
        self._workflow_list = QListWidget()
        self._workflow_list.setIconSize(QSize(16, 16))
        self._workflow_list.setSpacing(2)
        font = QFont()
        font.setPointSize(12)
        self._workflow_list.setFont(font)
        self._workflow_list.setFixedWidth(200)
        self._populate_workflow_list()
        self._workflow_list.currentRowChanged.connect(self._activate_panel)

        # Project info label below the list
        self._project_label = QLabel("No project open")
        self._project_label.setWordWrap(True)
        self._project_label.setStyleSheet("color:#888; font-size:11px; padding:4px;")

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(4, 4, 4, 4)
        left_layout.addWidget(self._workflow_list)
        left_layout.addWidget(self._project_label)

        left_dock = QDockWidget("Workflow")
        left_dock.setWidget(left_widget)
        left_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        left_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

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
            item.setForeground(QColor("#2ecc71" if done else "#ecf0f1"))
            item.setToolTip("✅ Complete" if done else "⬜ Not yet complete")
            self._workflow_list.addItem(item)

    def refresh_workflow_list(self):
        """Refresh icons/colours after state changes."""
        for i in range(self._workflow_list.count()):
            item = self._workflow_list.item(i)
            done = self._state.step_complete(i)
            item.setForeground(QColor("#2ecc71" if done else "#ecf0f1"))
            item.setToolTip("✅ Complete" if done else "⬜ Not yet complete")
        # Update project info label
        if self._state.project_name:
            cells = f"\n{self._state.n_cells:,} cells" if self._state.n_cells else ""
            self._project_label.setText(f"📁 {self._state.project_name}{cells}")
        else:
            self._project_label.setText("No project open")

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

        # Swap the right-dock form
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
        self.refresh_workflow_list()
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

    # ══════════════════════════════════════════════════════════════════════════
    #  Central tab helpers (called by panels)
    # ══════════════════════════════════════════════════════════════════════════

    def set_map_widget(self, widget: QWidget):
        """Replace the Map tab content."""
        self._centre_tabs.removeTab(0)
        self._centre_tabs.insertTab(0, widget, "🗺  Map")
        self._centre_tabs.setCurrentIndex(0)

    def set_raster_widget(self, widget: QWidget):
        """Replace the Raster tab content."""
        self._centre_tabs.removeTab(1)
        self._centre_tabs.insertTab(1, widget, "🖼  Raster")
        self._centre_tabs.setCurrentIndex(1)

    def set_chart_widget(self, widget: QWidget):
        """Replace the Charts tab content."""
        self._centre_tabs.removeTab(2)
        self._centre_tabs.insertTab(2, widget, "📈  Charts")
        self._centre_tabs.setCurrentIndex(2)

    def show_map_tab(self):
        self._centre_tabs.setCurrentIndex(0)

    def show_raster_tab(self):
        self._centre_tabs.setCurrentIndex(1)

    def show_chart_tab(self):
        self._centre_tabs.setCurrentIndex(2)

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
            # Reset all panels so they re-read fresh state on next activation
            self._panels = [None] * 10
            self.refresh_workflow_list()
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
