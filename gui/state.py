"""
gui/state.py
============
ProjectState — single source of truth for the entire application.
Persisted as JSON in <project_dir>/project_state.json.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional, Tuple


@dataclass
class ProjectState:
    # ── Project identity ───────────────────────────────────────────────────────
    project_name: Optional[str] = None
    project_dir:  Optional[str] = None
    crs: str = "EPSG:32736"   # default UTM 36S (KwaZulu-Natal)

    # ── AOI + outlet ──────────────────────────────────────────────────────────
    bbox: Optional[dict] = None
    # bbox keys: south, north, west, east (WGS84 decimal degrees)
    outlet_xy: Optional[Tuple[float, float]] = None
    # outlet_xy: (lon, lat) in WGS84

    # ── API credentials ───────────────────────────────────────────────────────
    ot_api_key: Optional[str] = None
    dem_type: str = "SRTMGL1"   # SRTMGL1 | SRTMGL3 | COP30 | NASADEM

    # ── Raster paths ──────────────────────────────────────────────────────────
    dem_path:        Optional[str] = None   # raw downloaded DEM (WGS84)
    proj_dem_path:   Optional[str] = None   # gdalwarp reprojected to CRS
    filled_dem_path: Optional[str] = None   # pysheds pit/depression/flat filled
    fdir_path:       Optional[str] = None   # D8 flow direction (GRASS 1-8 coding)
    accum_path:      Optional[str] = None   # flow accumulation (cells)
    mask_path:       Optional[str] = None   # catchment mask (1=cell, nodata=255)
    slope_path:      Optional[str] = None   # slope in degrees (gdaldem)
    streamnet_path:  Optional[str] = None   # stream network binary (1=stream, 0=land)
    strahler_path:   Optional[str] = None   # Strahler order raster

    # ── Soil raster paths ─────────────────────────────────────────────────────
    hwsd_path:          Optional[str]  = None
    hwsd_clipped_path:  Optional[str]  = None   # HWSD clipped to catchment mask
    hwsd_codes:         Optional[list] = None   # list of int HWSD codes in catchment
    hwsd_param_overrides: Optional[dict] = None  # {str(code): {param: value}}
    soil_depth_path:    Optional[str]  = None   # soil_depth.tif
    hwsd_ks_path:       Optional[str]  = None   # Ks.tif   (m/s)
    hwsd_theta_path:    Optional[str]  = None   # theta_s.tif
    hwsd_theta_r_path:  Optional[str]  = None   # theta_r.tif
    hwsd_psi_b_path:    Optional[str]  = None   # psi_b.tif (cm)
    hwsd_pore_path:     Optional[str]  = None   # pore index raster
    mannings_path:      Optional[str]  = None   # mannings_no.tif (overland n_o)

    # ── Parameter files ───────────────────────────────────────────────────────
    cell_param_path:   Optional[str] = None   # cell_param.dat
    global_param_path: Optional[str] = None   # global_param.dat
    ini_path:          Optional[str] = None   # TOPKAPI.ini (run config)
    param_setup_path:  Optional[str] = None   # param_setup.ini (create_file input)

    # ── Forcing files ─────────────────────────────────────────────────────────
    rainfields_path: Optional[str] = None   # rainfields.h5
    et_path:         Optional[str] = None   # ET.h5

    # ── Results ───────────────────────────────────────────────────────────────
    results_path: Optional[str] = None   # simulation_output.h5

    # ── Computed scalars ──────────────────────────────────────────────────────
    n_cells:          Optional[int] = None
    stream_threshold: int = 500   # accumulation cells → stream initiation

    # ── Step completion flags ─────────────────────────────────────────────────
    soil_ready:      bool = False
    landcover_ready: bool = False

    # ── Global model parameters ───────────────────────────────────────────────
    cell_size_m: float = 30.0
    dt_s:        int   = 86400
    alpha_s:     float = 2.5
    alpha_oc:    float = 1.6667
    A_thres:     float = 1_000_000.0
    W_min:       float = 2.0
    W_max:       float = 25.0

    # ── Initial conditions ────────────────────────────────────────────────────
    pVs_t0: float = 60.0   # % of max soil storage (Fatoyinbo 2018)
    Vo_t0:  float = 0.0
    Qc_t0:  float = 0.0
    Kc:     float = 1.0

    # ── Calibration multipliers ───────────────────────────────────────────────
    fac_L:   float = 1.00
    fac_Ks:  float = 0.68   # from Fatoyinbo (2018) calibration
    fac_n_o: float = 1.00
    fac_n_c: float = 1.00

    # ── HDF5 group name (shared by rainfields.h5 and ET.h5) ──────────────────
    group_name: str = "sample_event"   # must match in both HDF5 files

    # ── Manning channel lookup (Strahler order → n_c) ─────────────────────────
    manning_nc: dict = field(default_factory=lambda: {
        1: 0.050, 2: 0.040, 3: 0.035, 4: 0.030, 5: 0.030, 6: 0.025
    })

    # ── Land cover settings ───────────────────────────────────────────────────
    lc_source:        str = "fatoyinbo"   # "fatoyinbo" | "upload"
    lc_mode:          str = "uniform"     # "uniform" | "raster"
    dominant_lc_code: int = 1
    lc_path:          Optional[str] = None   # land cover GeoTIFF path

    # ──────────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────────

    def save(self) -> None:
        """Serialise to <project_dir>/project_state.json."""
        if not self.project_dir:
            return
        path = os.path.join(self.project_dir, "project_state.json")
        data = asdict(self)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    @classmethod
    def load(cls, project_dir: str) -> "ProjectState":
        """Deserialise from <project_dir>/project_state.json."""
        path = os.path.join(project_dir, "project_state.json")
        with open(path) as f:
            data = json.load(f)
        # JSON keys are always strings — restore int keys for manning_nc
        if "manning_nc" in data and data["manning_nc"]:
            data["manning_nc"] = {int(k): v for k, v in data["manning_nc"].items()}
        # outlet_xy stored as list in JSON — restore as tuple
        if data.get("outlet_xy"):
            data["outlet_xy"] = tuple(data["outlet_xy"])
        # Filter out any keys not in the dataclass (forward-compat)
        valid = {f.name for f in cls.__dataclass_fields__.values()}
        data = {k: v for k, v in data.items() if k in valid}
        return cls(**data)

    # ──────────────────────────────────────────────────────────────────────────
    # Step completion logic (drives left-dock checkbox icons)
    # ──────────────────────────────────────────────────────────────────────────

    def step_complete(self, idx: int) -> bool:
        """Return True if step idx (0-indexed) has usable outputs."""
        checks = [
            self.dem_path is not None,                                       # 0 Study Area
            self.filled_dem_path is not None and self.accum_path is not None,# 1 DEM Processing
            self.mask_path is not None and self.slope_path is not None,      # 2 Watershed
            self.streamnet_path is not None and self.strahler_path is not None, # 3 Streams
            self.soil_ready,                                                  # 4 Soil
            self.landcover_ready,                                             # 5 Land Cover
            self.cell_param_path is not None,                                # 6 Param Files
            self.rainfields_path is not None and self.et_path is not None,   # 7 Forcing
            self.results_path is not None,                                   # 8 Run Model
            self.results_path is not None,                                   # 9 Results
        ]
        return checks[idx] if 0 <= idx < len(checks) else False

    def subdirs(self) -> dict:
        """Return standard subdirectory paths (created by StudyAreaPanel)."""
        d = self.project_dir or ""
        return {
            "rasters":   os.path.join(d, "rasters"),
            "params":    os.path.join(d, "parameter_files"),
            "forcing":   os.path.join(d, "forcing_variables"),
            "results":   os.path.join(d, "results"),
        }
