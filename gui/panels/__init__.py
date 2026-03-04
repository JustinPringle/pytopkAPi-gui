"""
gui/panels/__init__.py
======================
BasePanel — abstract base class for all 10 workflow step panels.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget


class BasePanel(QWidget):
    """Abstract base for all step panels."""

    step_complete = pyqtSignal(int)   # emitted with step index 0-9 when outputs are ready

    def __init__(self, state, main_window, parent=None):
        super().__init__(parent)
        self._state = state           # gui.state.ProjectState
        self._mw    = main_window     # gui.app.MainWindow
        self._form: QWidget | None = None

    def build_form(self) -> QWidget:
        raise NotImplementedError

    def on_activated(self) -> None:
        raise NotImplementedError

    def refresh_from_state(self) -> None:
        raise NotImplementedError

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
            self,
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
