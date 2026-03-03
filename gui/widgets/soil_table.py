"""
gui/widgets/soil_table.py
==========================
SoilTableWidget  — editable QTableWidget showing HWSD soil codes mapped to
PyTOPKAPI parameters (depth, Ks, theta_s, theta_r, psi_b).

Usage:
    table = SoilTableWidget()
    table.load_codes(codes, state_params)   # populate from HWSD codes + any overrides
    params = table.get_params()             # {code: {depth, Ks, theta_s, theta_r, psi_b}}
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView


_COLUMNS = ["HWSD Code", "Texture", "Depth (m)", "Ks (m/s)", "θs", "θr", "ψb (cm)"]
_PARAM_KEYS = ["depth", "Ks", "theta_s", "theta_r", "psi_b"]


class SoilTableWidget(QTableWidget):
    """Editable table for soil parameter overrides."""

    def __init__(self, parent=None):
        super().__init__(0, len(_COLUMNS), parent)
        self.setHorizontalHeaderLabels(_COLUMNS)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setAlternatingRowColors(True)
        self.setStyleSheet(
            "QTableWidget { alternate-background-color: #323436; }"
        )

    def load_codes(self, codes: list[int], overrides: dict | None = None) -> None:
        """Populate the table from a list of HWSD codes.

        Parameters
        ----------
        codes:     list of integer HWSD soil unit codes
        overrides: optional {code: {param: value}} from a previously-saved state
        """
        from core.soil_params import get_params

        self.setRowCount(0)
        for code in sorted(codes):
            params = overrides.get(code, get_params(code)) if overrides else get_params(code)
            row = self.rowCount()
            self.insertRow(row)

            # HWSD code (read-only)
            code_item = QTableWidgetItem(str(code))
            code_item.setFlags(code_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 0, code_item)

            # Texture (read-only)
            tex_item = QTableWidgetItem(params.get("texture", "Unknown"))
            tex_item.setFlags(tex_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.setItem(row, 1, tex_item)

            # Editable numeric fields
            for col, key in enumerate(_PARAM_KEYS, start=2):
                val = params.get(key, 0.0)
                item = QTableWidgetItem(f"{val:.6g}")
                self.setItem(row, col, item)

    def get_params(self) -> dict[int, dict]:
        """Return current table values as {code: {param: value}}."""
        result = {}
        for row in range(self.rowCount()):
            try:
                code = int(self.item(row, 0).text())
                p = {}
                for col, key in enumerate(_PARAM_KEYS, start=2):
                    item = self.item(row, col)
                    p[key] = float(item.text()) if item else 0.0
                result[code] = p
            except (ValueError, AttributeError):
                continue
        return result
