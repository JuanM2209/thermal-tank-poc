"""Real-world tank geometry conversions.

All functions are pure and side-effect free.

Conventions
-----------
- Height, diameter, level in feet (ft). Convert to/from inches at UI edges only.
- Volume in barrels (bbl, oilfield standard, 1 bbl = 5.6146 ft^3) and gallons.
- Tanks are vertical cylinders by default. `compute()` honors a `shape` field.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

FT3_PER_BBL: float = 5.6145833333  # US petroleum barrel
GAL_PER_FT3: float = 7.4805195
IN_PER_FT: int = 12

Shape = Literal["vertical_cylinder", "rectangular"]


@dataclass(frozen=True)
class Geometry:
    height_ft: float
    diameter_ft: float
    shape: Shape = "vertical_cylinder"
    # Optional rectangular prism footprint. Ignored for cylinders.
    length_ft: float = 0.0
    width_ft: float = 0.0

    def is_valid(self) -> bool:
        if self.height_ft <= 0:
            return False
        if self.shape == "vertical_cylinder":
            return self.diameter_ft > 0
        if self.shape == "rectangular":
            return self.length_ft > 0 and self.width_ft > 0
        return False


@dataclass(frozen=True)
class Reading:
    level_ft: float
    level_in: float
    volume_bbl: float
    volume_gal: float
    ullage_ft: float


def footprint_ft2(g: Geometry) -> float:
    """Cross-sectional area of the tank at any horizontal slice."""
    if g.shape == "vertical_cylinder":
        r = g.diameter_ft / 2.0
        return math.pi * r * r
    if g.shape == "rectangular":
        return g.length_ft * g.width_ft
    return 0.0


def volume_ft3_at_level(g: Geometry, level_ft: float) -> float:
    """Liquid volume (ft^3) at a given level height."""
    level = max(0.0, min(level_ft, g.height_ft))
    return footprint_ft2(g) * level


def ft3_to_bbl(v_ft3: float) -> float:
    return v_ft3 / FT3_PER_BBL


def ft3_to_gal(v_ft3: float) -> float:
    return v_ft3 * GAL_PER_FT3


def compute(g: Geometry, level_pct: float) -> Reading:
    """Derive human-readable level/volume from a 0..100 %% reading."""
    pct = max(0.0, min(100.0, float(level_pct)))
    level_ft = (pct / 100.0) * g.height_ft
    v_ft3 = volume_ft3_at_level(g, level_ft)
    return Reading(
        level_ft=round(level_ft, 2),
        level_in=round(level_ft * IN_PER_FT, 1),
        volume_bbl=round(ft3_to_bbl(v_ft3), 1),
        volume_gal=round(ft3_to_gal(v_ft3), 0),
        ullage_ft=round(max(0.0, g.height_ft - level_ft), 2),
    )


def parse_geometry(raw: dict | None) -> Geometry | None:
    """Accept a dict from config / HTTP body. Return None if invalid."""
    if not raw:
        return None
    try:
        g = Geometry(
            height_ft=float(raw.get("height_ft", 0.0)),
            diameter_ft=float(raw.get("diameter_ft", 0.0)),
            shape=str(raw.get("shape", "vertical_cylinder")),  # type: ignore[arg-type]
            length_ft=float(raw.get("length_ft", 0.0)),
            width_ft=float(raw.get("width_ft", 0.0)),
        )
    except (TypeError, ValueError):
        return None
    return g if g.is_valid() else None
