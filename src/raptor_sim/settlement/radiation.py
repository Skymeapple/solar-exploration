"""Cumulative radiation dose over a working tour or a whole life on another world.

Surface dose rates are measured (Curiosity RAD on Mars, Chang'e 4 on the Moon);
cruise dose is MSL's. Shielding by regolith is the uncertain part: galactic
cosmic rays (GCR) make secondary particles in the shield, so dose falls slowly
with depth. We use a two-component attenuation curve (estimate): a soft part
stopped in the first ~30 g/cm2 and a penetrating part with an e-folding length
of 150 g/cm2 (input "shield_lambda"), so that a few metres of regolith brings
dose near Earth background, as subsurface transport studies suggest. The study
reruns every case with lambda = 100 and 250 g/cm2 because this is the least
certain number in the radiation model.

Risk uses the ICRP linear coefficient (5.5 %/Sv), times 2.5 for dose received
in childhood, and the result is reported with a factor-of-3 band because GCR
heavy-ion biology is not known well enough to do better.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .inputs import v

REGOLITH_DENSITY = 1.5  # g/cm3, loose fill (estimate; sintered ~2.0)


def shield_factor(areal_density_g_cm2: float, lam: float | None = None) -> float:
    """Dose behind regolith relative to the unshielded surface (estimate)."""
    x = max(0.0, areal_density_g_cm2)
    lam = v("shield_lambda") if lam is None else lam
    return 0.35 * math.exp(-x / 30.0) + 0.65 * math.exp(-x / lam)


def regolith_depth_m(areal_density_g_cm2: float, density: float = REGOLITH_DENSITY) -> float:
    return areal_density_g_cm2 / density / 100.0


SURFACE_DOSE = {  # mSv/day unshielded
    "Mars": v("dose_mars_surface"),
    "Moon": v("dose_moon_surface"),
    "Deep space": v("dose_cruise"),
}


@dataclass(frozen=True)
class Exposure:
    site: str = "Mars"
    habitat_shield_g_cm2: float = 200.0  # roof over living areas
    hours_outside_per_week: float = 4.0  # EVA or surface work in a suit (~5 g/cm2)
    suit_shield_g_cm2: float = 5.0
    years: float = 80.0
    born_there: bool = True
    transits: int = 0  # Earth-Mars trips made (each about 0.5 yr in cruise)
    transit_days: float = 180.0
    lam: float | None = None  # shielding e-folding length override (g/cm2)


def annual_dose_msv(e: Exposure) -> float:
    d0 = SURFACE_DOSE[e.site]
    out_share = e.hours_outside_per_week / (7 * 24)
    daily = d0 * ((1 - out_share) * shield_factor(e.habitat_shield_g_cm2, e.lam) + out_share * shield_factor(e.suit_shield_g_cm2, e.lam))
    return daily * 365.25


def lifetime(e: Exposure) -> dict[str, float]:
    """Cumulative dose (mSv) and excess cancer mortality risk with its band."""
    annual = annual_dose_msv(e)
    transit = e.transits * e.transit_days * v("dose_cruise")
    total = annual * e.years + transit
    # Childhood share (first 18 years) carries the higher risk coefficient.
    child_years = min(18.0, e.years) if e.born_there else 0.0
    child_dose = annual * child_years
    adult_dose = total - child_dose
    risk = v("risk_per_sv") * (adult_dose + v("risk_child_multiplier") * child_dose) / 1000.0
    u = v("gcr_quality_uncertainty")
    return {
        "annual_msv": annual,
        "total_msv": total,
        "risk": risk,
        "risk_low": risk / u,
        "risk_high": min(1.0, risk * u),
        "earth_background_msv": v("dose_earth_background") * e.years,
        "career_limit_msv": v("career_limit"),
    }


def shield_needed(site: str = "Mars", target_annual_msv: float = 10.0, hours_outside: float = 4.0, lam: float | None = None) -> float:
    """Areal density (g/cm2) that brings annual dose under the target, or inf."""
    lo, hi = 0.0, 3000.0
    f = lambda x: annual_dose_msv(Exposure(site, x, hours_outside, lam=lam)) - target_annual_msv
    if f(hi) > 0:
        return math.inf
    if f(lo) <= 0:
        return 0.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return hi


def dose_table() -> list[dict]:
    rows = []
    cases = [
        ("Mars, 2.5-yr crew tour, light shielding", Exposure("Mars", 20.0, 10.0, years=1.5, born_there=False, transits=2)),
        ("Mars, 2.5-yr crew tour, 2 m regolith", Exposure("Mars", 300.0, 4.0, years=1.5, born_there=False, transits=2)),
        ("Mars, born there, 1 m regolith", Exposure("Mars", 150.0, 4.0, 5.0, 80.0, True)),
        ("Mars, born there, 3 m regolith", Exposure("Mars", 450.0, 4.0, 5.0, 80.0, True)),
        ("Mars, born there, 5 m regolith", Exposure("Mars", 750.0, 4.0, 5.0, 80.0, True)),
        ("Moon, born there, 5 m regolith", Exposure("Moon", 750.0, 4.0, 5.0, 80.0, True)),
        ("Moon, 6-month tour, 1 m regolith", Exposure("Moon", 150.0, 10.0, years=0.5, born_there=False)),
    ]
    for name, e in cases:
        r = lifetime(e)
        lo = lifetime(Exposure(**{**e.__dict__, "lam": 100.0}))["total_msv"]
        hi = lifetime(Exposure(**{**e.__dict__, "lam": 250.0}))["total_msv"]
        rows.append({"case": name, **r, "total_msv_lam100": lo, "total_msv_lam250": hi, "shield_g_cm2": e.habitat_shield_g_cm2, "regolith_m": regolith_depth_m(e.habitat_shield_g_cm2)})
    return rows
