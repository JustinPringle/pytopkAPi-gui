"""
core/soil_params.py
===================
HWSD soil code → PyTOPKAPI soil parameter lookup tables.

Default values from Rawls et al. (1982), as used in Fatoyinbo (2018)
for the Mhlanga/Umhlanga catchment.

Each entry:
    hwsd_code : {
        'texture'  : str,
        'depth'    : float,   # soil depth (m)
        'Ks'       : float,   # saturated hydraulic conductivity (m/s)
        'theta_s'  : float,   # saturated moisture content (cm³/cm³)
        'theta_r'  : float,   # residual moisture content (cm³/cm³)
        'psi_b'    : float,   # bubbling pressure (cm)
        'lambda'   : float,   # pore size distribution index
        'n_o'      : float,   # overland Manning roughness (default, overridden by land cover)
    }
"""

# ── HWSD code → soil properties ───────────────────────────────────────────────
# Source: Rawls et al. (1982) Table 2 + HWSD v1.2 documentation
# Units match PyTOPKAPI cell_param.dat column definitions

HWSD_PARAMS: dict = {
    # ── Umhlanga catchment soil units (Fatoyinbo 2018, Table 4-1) ────────────
    28718: {
        "texture": "Sandy clay loam",
        "depth":   1.00,        # m
        "Ks":      6.38e-6,     # m/s  (0.023 cm/h → m/s)  [Rawls 1982]
        "theta_s": 0.398,
        "theta_r": 0.068,
        "psi_b":   2.810,       # cm (bubbling pressure)
        "lambda":  0.177,
    },
    28733: {
        "texture": "Clay loam",
        "depth":   0.30,        # m
        "Ks":      6.39e-7,     # m/s
        "theta_s": 0.465,
        "theta_r": 0.075,
        "psi_b":   2.586,
        "lambda":  0.242,
    },
    28824: {
        "texture": "Clay loam",
        "depth":   0.10,        # m
        "Ks":      6.39e-7,     # m/s
        "theta_s": 0.465,
        "theta_r": 0.075,
        "psi_b":   2.586,
        "lambda":  0.242,
    },
    28844: {
        "texture": "Sandy loam",
        "depth":   1.00,        # m
        "Ks":      7.19e-6,     # m/s
        "theta_s": 0.453,
        "theta_r": 0.041,
        "psi_b":   1.478,
        "lambda":  0.378,
    },

    # ── Rawls (1982) full texture class defaults (fallback for unknown codes) ─
    "Sand": {
        "texture": "Sand",
        "depth":   1.00,
        "Ks":      1.656e-4,
        "theta_s": 0.437,
        "theta_r": 0.020,
        "psi_b":   0.726,
        "lambda":  0.694,
    },
    "Loamy sand": {
        "texture": "Loamy sand",
        "depth":   1.00,
        "Ks":      5.556e-5,
        "theta_s": 0.437,
        "theta_r": 0.035,
        "psi_b":   0.869,
        "lambda":  0.553,
    },
    "Sandy loam": {
        "texture": "Sandy loam",
        "depth":   1.00,
        "Ks":      7.19e-6,
        "theta_s": 0.453,
        "theta_r": 0.041,
        "psi_b":   1.478,
        "lambda":  0.378,
    },
    "Loam": {
        "texture": "Loam",
        "depth":   1.00,
        "Ks":      3.67e-6,
        "theta_s": 0.463,
        "theta_r": 0.027,
        "psi_b":   1.116,
        "lambda":  0.252,
    },
    "Silt loam": {
        "texture": "Silt loam",
        "depth":   1.00,
        "Ks":      1.89e-6,
        "theta_s": 0.501,
        "theta_r": 0.015,
        "psi_b":   2.076,
        "lambda":  0.234,
    },
    "Sandy clay loam": {
        "texture": "Sandy clay loam",
        "depth":   1.00,
        "Ks":      6.38e-6,
        "theta_s": 0.398,
        "theta_r": 0.068,
        "psi_b":   2.810,
        "lambda":  0.177,
    },
    "Clay loam": {
        "texture": "Clay loam",
        "depth":   0.50,
        "Ks":      6.39e-7,
        "theta_s": 0.465,
        "theta_r": 0.075,
        "psi_b":   2.586,
        "lambda":  0.242,
    },
    "Silty clay loam": {
        "texture": "Silty clay loam",
        "depth":   0.50,
        "Ks":      4.17e-7,
        "theta_s": 0.471,
        "theta_r": 0.040,
        "psi_b":   3.252,
        "lambda":  0.177,
    },
    "Sandy clay": {
        "texture": "Sandy clay",
        "depth":   0.30,
        "Ks":      3.33e-7,
        "theta_s": 0.430,
        "theta_r": 0.109,
        "psi_b":   2.914,
        "lambda":  0.223,
    },
    "Silty clay": {
        "texture": "Silty clay",
        "depth":   0.30,
        "Ks":      2.50e-7,
        "theta_s": 0.479,
        "theta_r": 0.056,
        "psi_b":   3.419,
        "lambda":  0.150,
    },
    "Clay": {
        "texture": "Clay",
        "depth":   0.30,
        "Ks":      1.67e-7,
        "theta_s": 0.475,
        "theta_r": 0.090,
        "psi_b":   3.730,
        "lambda":  0.165,
    },
}

# ── Parameter names (as needed by generate_param_file) ───────────────────────
PARAM_FIELDS = ["depth", "Ks", "theta_s", "theta_r", "psi_b", "lambda"]

# ── Default fallback (use loam if code is unknown) ────────────────────────────
DEFAULT_PARAMS = HWSD_PARAMS["Loam"]


def get_params(hwsd_code: int) -> dict:
    """Return soil parameters for a given HWSD soil unit code."""
    return HWSD_PARAMS.get(hwsd_code, DEFAULT_PARAMS)
