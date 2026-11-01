"""Crew consumables and radiation for lunar surface missions of increasing length.

Uses the crewed missions models: raptor_sim.crew.life_support.consumables and
raptor_sim.crew.radiation.mission_dose. This module only defines the lunar cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..crew.life_support import consumables
from ..crew.radiation import mission_dose
from .legs import tli_transfer_days


@dataclass(frozen=True)
class SurfaceCase:
    name: str
    crew: int
    surface_days: float
    loop: str  # life support loop type
    habitat_gcm2: float  # surface shielding (regolith-equivalent)


CASES = (
    SurfaceCase("Artemis-class sortie", 4, 7.0, "open", 10.0),  # 7 days cited for HLS; open loop estimated
    SurfaceCase("Extended stay", 4, 30.0, "iss", 10.0),
    SurfaceCase("Base rotation, regolith-covered habitat", 4, 180.0, "iss", 50.0),
)


def transit_days() -> float:
    """Round trip in space: two transfers plus NRHO phasing and rendezvous (6.5-day NRHO period, cited)."""
    return 2 * tli_transfer_days() + 6.5


def surface_cases() -> list[dict]:
    out = []
    for c in CASES:
        days = transit_days() + c.surface_days
        cons = consumables(c.crew, days, c.loop)
        dose = mission_dose(transit_days(), c.surface_days, surface="moon_surface", habitat_gcm2=c.habitat_gcm2)
        out.append({
            "case": c.name, "crew": c.crew, "surface_days": c.surface_days, "mission_days": days,
            "loop": c.loop, "consumables_t": cons.total_kg / 1e3,
            "dose_msv": dose.total_msv, "career_fraction": dose.fraction_of_career_limit,
        })
    return out
