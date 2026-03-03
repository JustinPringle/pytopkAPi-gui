# pytopkapi_gui.spec
# ==================
# PyInstaller spec for PyTOPKAPI GUI.
#
# Build instructions:
#   macOS:   pyinstaller pytopkapi_gui.spec
#   Windows: pyinstaller pytopkapi_gui.spec
#
# Output:
#   dist/PyTOPKAPI GUI.app  (macOS)
#   dist/PyTOPKAPI GUI/     (Windows one-folder)

import sys
import os
from pathlib import Path

HERE = Path(spec.pathex[0]) if hasattr(spec, 'pathex') and spec.pathex else Path('.')

# ── Detect platform ────────────────────────────────────────────────────────────
IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform == "win32"

# ── GDAL data files (rasterio ships its own GDAL) ─────────────────────────────
import rasterio
GDAL_DATA = str(Path(rasterio.__file__).parent / "gdal_data")

# ── Collect all rasterio / pysheds / folium data files ────────────────────────
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("gui/resources/style.qss", "gui/resources"),
    ("vendor/create_file.py",   "vendor"),
]
datas += collect_data_files("rasterio")
datas += collect_data_files("pysheds")
datas += collect_data_files("folium")
datas += collect_data_files("pyproj")

# ── Hidden imports ─────────────────────────────────────────────────────────────
hiddenimports = [
    # Qt
    "PyQt6",
    "PyQt6.QtCore",
    "PyQt6.QtGui",
    "PyQt6.QtWidgets",
    "PyQt6.QtWebEngineWidgets",
    "PyQt6.QtWebChannel",
    # Science
    "numpy",
    "scipy",
    "pandas",
    "matplotlib",
    "matplotlib.backends.backend_qtagg",
    # GIS
    "rasterio",
    "rasterio._shim",
    "rasterio.features",
    "rasterio.warp",
    "pysheds",
    "pysheds.grid",
    "pyproj",
    "shapely",
    "geopandas",
    "folium",
    # HDF5
    "h5py",
    # PyTOPKAPI
    "pytopkapi",
    "pytopkapi.run",
    # Networking
    "requests",
    # Data
    "networkx",
    "openpyxl",
]
hiddenimports += collect_submodules("pytopkapi")
hiddenimports += collect_submodules("rasterio")

# ── Analysis ───────────────────────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "unittest", "test", "distutils"],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# ── macOS .app bundle ──────────────────────────────────────────────────────────
if IS_MAC:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="PyTOPKAPI GUI",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=True,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="PyTOPKAPI GUI",
    )
    app = BUNDLE(
        coll,
        name="PyTOPKAPI GUI.app",
        icon=None,
        bundle_identifier="za.ac.ukzn.waterq.pytopkapi-gui",
        info_plist={
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "CFBundleShortVersionString": "0.1.0",
        },
    )

# ── Windows / Linux one-folder ─────────────────────────────────────────────────
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="PyTOPKAPI_GUI",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
