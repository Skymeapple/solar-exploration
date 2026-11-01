"""Construction with regolith: radiation cover for habitats, sintered pads and blast berms."""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.optimize import brentq

from . import plume
from .provenance import Value

CHANGE4 = "Zhang et al. 2020, Science Advances 6, eaaz1334 (Chang'e 4 LND: 1,369 uSv/day)"

SPEC: dict[str, Value] = {
    "gcr_dose_msv_day": Value(1.369, "mSv/day", "cited", CHANGE4),
    "regolith_density": Value(1.5, "g/cm^3", "cited", "bulk density, Lunar Sourcebook"),
    "shield_a": Value(0.6, "-", "estimated", "fast-falling dose share (primaries, soft secondaries)"),
    "shield_l1": Value(40.0, "g/cm^2", "estimated", "e-folding depth of the fast part"),
    "shield_l2": Value(170.0, "g/cm^2", "estimated", "e-folding depth of the penetrating neutrons and muons"),
    "dose_limit_msv_yr": Value(50.0, "mSv/yr", "estimated", "design goal for permanent residents, terrestrial occupational limit"),
    "excavation_t_day": Value(10.0, "t/day", "estimated", "one RASSOR-class excavator in continuous operation"),
    "sinter_depth": Value(0.15, "m", "estimated", "sintered pad thickness"),
    "sinter_density": Value(2.2, "t/m^3", "estimated", "sintered regolith"),
    "sinter_mj_per_kg": Value(1.6, "MJ/kg", "computed", "heat 250 K to 1,400 K at 0.85 kJ/(kg K), 60% microwave efficiency"),
    "repose_deg": Value(35.0, "deg", "estimated", "berm side slope near the angle of repose"),
}


def dose_msv_yr(cover_m: float) -> float:
    x = cover_m * 100 * SPEC["regolith_density"].value  # g/cm^2
    a, l1, l2 = SPEC["shield_a"].value, SPEC["shield_l1"].value, SPEC["shield_l2"].value
    return 365.25 * SPEC["gcr_dose_msv_day"].value * (a * math.exp(-x / l1) + (1 - a) * math.exp(-x / l2))


def cover_for_dose(limit_msv_yr: float | None = None, occupancy: float = 0.95) -> float:
    """Regolith cover (m) that meets the dose limit, with `occupancy` of time spent inside."""
    limit = SPEC["dose_limit_msv_yr"].value if limit_msv_yr is None else limit_msv_yr
    outside = (1 - occupancy) * dose_msv_yr(0.0)
    if outside >= limit:
        raise ValueError("time outside alone exceeds the limit")
    return brentq(lambda t: occupancy * dose_msv_yr(t) + outside - limit, 0.0, 20.0)


@dataclass(frozen=True)
class Habitat:
    name: str
    radius_m: float
    length_m: float
    crew: int


HABITATS = (
    Habitat("Outpost module (inflatable, 4 crew)", 4.0, 12.0, 4),
    Habitat("Settlement block (16 crew)", 6.0, 40.0, 16),
)


def cover_mass_t(h: Habitat, cover_m: float) -> float:
    """Regolith mound over a half-buried cylinder: half annulus along the length plus two quarter-sphere ends."""
    r0, r1 = h.radius_m, h.radius_m + cover_m
    body = 0.5 * math.pi * (r1**2 - r0**2) * h.length_m
    ends = (2 / 3) * math.pi * (r1**3 - r0**3)  # two quarter-sphere shells make one hemisphere shell
    return (body + ends) * SPEC["regolith_density"].value


def excavation_days(mass_t: float, machines: int = 2) -> float:
    return mass_t / (SPEC["excavation_t_day"].value * machines)


@dataclass(frozen=True)
class PadWorks:
    pad_radius_m: float
    pad_area_m2: float
    sinter_energy_mwh: float
    sinter_days_at_kw: float
    berm_distance_m: float
    berm_height_m: float
    berm_volume_m3: float
    berm_mass_t: float
    berm_excavation_days: float


def pad_works(sizing: plume.PadSizing, sinter_kw: float = 200.0, berm_distance_m: float | None = None,
              machines: int = 2) -> PadWorks:
    r = sizing.pad_radius_m
    area = math.pi * r * r
    mass_kg = area * SPEC["sinter_depth"].value * SPEC["sinter_density"].value * 1e3
    e_mwh = mass_kg * SPEC["sinter_mj_per_kg"].value / 3600
    days = e_mwh * 1e3 / sinter_kw / 24
    d = berm_distance_m if berm_distance_m is not None else max(2 * r, r + 50.0)
    hb = plume.berm_height_m(d - r)
    slope = math.tan(math.radians(SPEC["repose_deg"].value))
    top = 1.0
    section = hb * (top + hb / slope)  # trapezoid: top width plus two side slopes
    vol = 2 * math.pi * d * section
    mass = vol * SPEC["regolith_density"].value
    return PadWorks(r, area, e_mwh, days, d, hb, vol, mass, excavation_days(mass, machines))
