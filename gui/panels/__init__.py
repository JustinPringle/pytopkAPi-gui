"""
gui/panels/__init__.py
======================
BasePanel — abstract base class for all 10 workflow step panels.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QDialog, QScrollArea, QVBoxLayout, QWidget


class BasePanel(QWidget):
    """Abstract base for all step panels."""

    step_complete = pyqtSignal(int)   # emitted with step index 0-9 when outputs are ready

    def __init__(self, state, main_window, parent=None):
        super().__init__(parent)
        self._state = state           # gui.state.ProjectState
        self._mw    = main_window     # gui.app.MainWindow
        self._form: QWidget | None = None
        self._dialog: QDialog | None = None

    def build_form(self) -> QWidget:
        raise NotImplementedError

    def on_activated(self) -> None:
        raise NotImplementedError

    def refresh_from_state(self) -> None:
        raise NotImplementedError

    # ── Dialog support ─────────────────────────────────────────────────────

    def show_as_dialog(self, title: str = "") -> None:
        """Show the panel's form inside a non-modal floating QDialog."""
        if self._dialog is None:
            self._dialog = QDialog(self._mw)
            self._dialog.setWindowTitle(title or "Tool")
            self._dialog.setMinimumSize(380, 300)
            self._dialog.resize(420, 640)

            # Dark theme styling
            self._dialog.setStyleSheet("""
                QDialog {
                    background: #252729;
                    color: #d4d4d4;
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
                QLineEdit, QSpinBox, QComboBox {
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
            """)

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setWidget(self.build_form())

            dlg_layout = QVBoxLayout(self._dialog)
            dlg_layout.setContentsMargins(0, 0, 0, 0)
            dlg_layout.addWidget(scroll)

        # Refresh content and map
        self.on_activated()
        self.refresh_from_state()

        self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    # ── Existing helpers ───────────────────────────────────────────────────

    def log(self, msg: str, level: str = "info") -> None:
        self._mw._log_dock.append_line(msg, level)

    def start_worker(self, worker) -> None:
        self._mw.start_worker(worker)

    def set_status(self, msg: str) -> None:
        self._mw.set_status(msg)

    def _browse_and_set(self, state_attr: str, label: str,
                        post_fn=None, start_dir: str = "") -> "str | None":
        """Open a GeoTIFF file dialog, set state attribute, save and refresh."""
        import os
        from PyQt6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self._mw,
            f"Select {label}",
            start_dir or (self._state.project_dir or os.path.expanduser("~")),
            "GeoTIFF (*.tif *.tiff);;All files (*)",
        )
        if path:
            setattr(self._state, state_attr, path)
            if post_fn:
                post_fn(path)
            self._state.save()
            self.refresh_from_state()
            self._mw.refresh_workflow_list()
            self.log(f"Loaded {label}: {os.path.basename(path)}", "ok")
            return path
        return None

    @staticmethod
    def _get_limits(state, attr: str) -> "tuple":
        """Return (vmin, vmax) for *attr* from state.layer_display_limits.

        Returns (None, None) when no limits have been set by the user.
        Pass the results directly to add_raster_overlay(vmin=…, vmax=…).
        """
        limits = getattr(state, "layer_display_limits", {}) or {}
        pair = limits.get(attr, {})
        return pair.get("vmin"), pair.get("vmax")

    @staticmethod
    def _read_n_cells_from_mask(mask_path: str) -> "int | None":
        """Count catchment cells in a mask GeoTIFF (non-nodata pixels)."""
        try:
            import rasterio
            import numpy as np
            with rasterio.open(mask_path) as src:
                data = src.read(1)
                nd   = src.nodata
            if nd is not None:
                return int(np.sum(data != int(nd)))
            return int(np.sum((data != 0) & (data != 255)))
        except Exception:
            return None
