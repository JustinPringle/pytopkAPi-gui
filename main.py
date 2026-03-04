"""
main.py
=======
PyTOPKAPI GUI — entry point.

Usage:
    python main.py
    # or after packaging:
    ./PyTOPKAPI_GUI.app
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))

# ── Scientific packages venv (~/.pyenvs/pytopkapi-gui/) ────────────────────────
# Scientific packages (rasterio, pysheds, numpy, h5py, matplotlib, folium,
# geopandas, pytopkapi, etc.) live in a venv outside iCloud to avoid the macOS
# UF_HIDDEN bug that makes Python 3.14 skip .pth files in iCloud-synced folders.
_pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
_sci_site = os.path.expanduser(f"~/.pyenvs/pytopkapi-gui/lib/{_pyver}/site-packages")
if os.path.isdir(_sci_site) and _sci_site not in sys.path:
    sys.path.insert(0, _sci_site)
del _pyver, _sci_site

# ── macOS Homebrew PyQt6 path ───────────────────────────────────────────────────
# PyQt6 and PyQt6-WebEngine are installed via Homebrew (not in the sci venv).
# Insert the Homebrew site-packages so PyQt6 is importable when running with
# the system Python directly.
if sys.platform == "darwin":
    import sysconfig as _sc
    _pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    _hb_site = f"/opt/homebrew/lib/{_pyver}/site-packages"
    if os.path.isdir(os.path.join(_hb_site, "PyQt6")) and _hb_site not in sys.path:
        sys.path.insert(0, _hb_site)
    del _sc, _pyver, _hb_site

# ── Vendor path (create_file.py for parameter file generation) ─────────────────
_VENDOR = os.path.join(_HERE, "vendor")
if _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

# ── GDAL data path fix for PyInstaller bundles ─────────────────────────────────
if getattr(sys, "frozen", False):
    os.environ.setdefault(
        "GDAL_DATA",
        os.path.join(sys._MEIPASS, "rasterio", "gdal_data"),
    )

# ── Qt application ─────────────────────────────────────────────────────────────
# QtWebEngineWidgets MUST be imported before QApplication is created, otherwise
# Qt raises: "AA_ShareOpenGLContexts must be set before a QCoreApplication"
from PyQt6.QtWebEngineWidgets import QWebEngineView as _QWebEngineView  # noqa: F401
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from gui.app import MainWindow


def main():
    # Enable high-DPI scaling (Qt6 default, but explicit for clarity)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("PyTOPKAPI GUI")
    app.setOrganizationName("UKZN Water Research Group")
    app.setApplicationVersion("0.1.0")

    # Set default font (use platform system defaults)
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    elif sys.platform == "darwin":
        app.setFont(QFont(".AppleSystemUIFont", 13))

    # Load stylesheet
    qss_path = os.path.join(_HERE, "gui", "resources", "style.qss")
    if os.path.exists(qss_path):
        with open(qss_path) as f:
            app.setStyleSheet(f.read())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
