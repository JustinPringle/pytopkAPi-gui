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
