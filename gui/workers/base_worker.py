"""
gui/workers/base_worker.py
==========================
BaseWorker — QThread subclass with four standard signals used by every worker.

Usage pattern in a panel:
    worker = SomeDerivedWorker(self._state, task="fill")
    worker.log_message.connect(main_window.log_dock.append_line)
    worker.progress.connect(main_window.progress_bar.setValue)
    worker.finished.connect(main_window._on_worker_finished)
    worker.error.connect(main_window._on_worker_error)
    worker.start()
"""

from PyQt6.QtCore import QThread, pyqtSignal


class BaseWorker(QThread):
    """Abstract QThread base for all background processing tasks.

    Subclasses override ``run()`` and emit the four signals below.
    All signals are thread-safe — Qt queues them to the main thread.
    """

    log_message = pyqtSignal(str)
    # Plain-text line to display in the LogDock.
    # Workers should call: self.log_message.emit("DEM filled successfully.")

    progress = pyqtSignal(int)
    # Integer 0–100. Drives the QStatusBar progress bar.
    # Emit 0 at start, 100 on completion.

    finished = pyqtSignal(dict)
    # Dict of {state_field_name: new_value} patches.
    # MainWindow._on_worker_finished() applies them via setattr(state, k, v),
    # then saves state to JSON, refreshes the workflow list and the active panel.
    # Example: self.finished.emit({"dem_path": "/path/to/dem.tif"})

    error = pyqtSignal(str)
    # Human-readable error message. Shown in QMessageBox.critical() by MainWindow.
    # Workers should catch exceptions and emit this signal instead of raising.

    def __init__(self, state, task: str = "", parent=None):
        super().__init__(parent)
        self.state = state   # ProjectState (read-only in workers; emit updates via finished)
        self.task  = task    # Discriminator when one worker class handles multiple tasks

    def run(self) -> None:  # pragma: no cover
        raise NotImplementedError("Subclasses must implement run()")
