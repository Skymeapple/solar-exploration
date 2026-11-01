"""Space radiation dose model for crew: galactic cosmic rays (GCR), solar
particle events (SPE) and planetary surfaces.

CITED anchors
- MSL/RAD cruise to Mars, Dec 2011 to Jul 2012: 1.84 mSv/day dose equivalent
  (Zeitlin et al., Science 340, 1080, 2013; SwRI release: about 1.8 mSv/day,
  0.66 Sv for a 360-day round-trip transit, ~5% of dose from SPEs).
- MSL/RAD Gale crater surface: 0.64 mSv/day (Hassler et al., Science 343, 2014).
- Chang'e-4 LND lunar far-side surface, 2019: 1.369 mSv/day; ISS same period
  0.731 mSv/day (Zhang et al., Science Advances 6, 2020).
- NASA-STD-3001 Vol 1 Rev B (2022) career effective dose limit 600 mSv for all
  ages and sexes. Storm shelter guidance: about 10 cm water-equivalent extra
  for a 1-in-100 year SPE, about 20 cm for a 1-in-1000 year event
  (NASA OCHMO radiation protection technical brief, 2023).
- NASA 30-day blood-forming-organ (BFO) limit 250 mGy-Eq (NASA-STD-3001
  Vol 1, short-term limits; carried over from NCRP Report 132).

ESTIMATES (ours, to be replaced by HZETRN/OLTARIS transport runs)
- Shape of the GCR shielding curve, f(x) = a + (1 - a) exp(-x / lam), with
  'a' the fraction left at large depth. Hydrogen-rich materials have lower
  'a'. The aluminium plateau is fitted so the two RAD anchors (cruise and
  Mars surface) are reproduced together. The effective RAD cruise depth
  (5 g/cm^2) and lam (20 g/cm^2) were chosen from a plausible range by
  comparing with Chang'e-4, so that comparison is a weak check, not an
  independent one. ``calibration_sensitivity`` shows that the deep-space dose
  behind 20 g/cm^2, which drives the mission results, moves only 1.7 to 2.3
  mSv/day across the whole plausible range.
- Solar-cycle scaling of GCR relative to the RAD cruise period.
- SPE dose-depth curve for an August-1972-class event.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

CAREER_LIMIT_MSV = 600.0  # CITED NASA-STD-3001 Rev B
BFO_30DAY_LIMIT_MGY = 250.0  # CITED NASA-STD-3001 Vol 1 short-term limit

RAD_CRUISE_MSV_D = 1.84  # CITED Zeitlin 2013
RAD_MARS_SURFACE_MSV_D = 0.64  # CITED Hassler 2014
CE4_MOON_SURFACE_MSV_D = 1.369  # CITED Zhang 2020 (used as a check, not a fit)
ISS_MSV_D = 0.731  # CITED Zhang 2020, same period as Chang'e-4

# ESTIMATES
RAD_CRUISE_SHIELD = 5.0  # g/cm^2 Al-eq, effective depth around RAD (much of its view was lightly shielded)
MARS_ATMOS_COLUMN = 21.0  # g/cm^2 vertical CO2 column at Gale crater (~750 Pa / 3.71 m/s^2 ~ 20 g/cm^2)
ALBEDO_FRACTION = {"mars": 0.10, "moon": 0.10}  # upward secondaries as fraction of downward dose
LAMBDA = 20.0  # g/cm^2 e-folding depth of the attenuating part of GCR dose equivalent
PLATEAU_RATIO = {"aluminum": 1.0, "regolith": 1.0, "water": 0.85, "polyethylene": 0.75}  # plateau relative to Al
SOLAR_FACTOR = {"min": 1.35, "rad2012": 1.0, "max": 0.80}  # GCR dose relative to RAD cruise epoch
CE4_SOLAR = "min"  # 2019 was solar minimum


def _f(x: float, a: float) -> float:
    return a + (1 - a) * math.exp(-x / LAMBDA)


def _hemisphere_mean(x_vertical: float, a: float, x_local: float = 0.0, n: int = 200) -> float:
    """Mean shielding factor over the upper hemisphere for an isotropic field
    (slant column x/cos(theta)), each direction weighted by solid angle."""
    mu = (np.arange(n) + 0.5) / n  # cos(theta) from 0 to 1, uniform in solid angle
    return float(np.mean([_f(x_vertical / m + x_local, a) for m in mu]))


@dataclass(frozen=True)
class GCRCalibration:
    plateau_al: float
    free_space_msv_d: float  # unshielded deep space, RAD epoch

    def predict_moon(self) -> float:
        h = 0.5 * self.free_space_msv_d * SOLAR_FACTOR[CE4_SOLAR] * _f(1.0, self.plateau_al)
        return h * (1 + ALBEDO_FRACTION["moon"])


def calibrate() -> GCRCalibration:
    """Fit the aluminium plateau and free-space rate to the two RAD anchors."""

    def surface_over_cruise(a):
        cruise = _f(RAD_CRUISE_SHIELD, a)
        surface = 0.5 * _hemisphere_mean(MARS_ATMOS_COLUMN, a) * (1 + ALBEDO_FRACTION["mars"])
        return surface / cruise - RAD_MARS_SURFACE_MSV_D / RAD_CRUISE_MSV_D

    a = brentq(surface_over_cruise, 0.05, 0.95)
    free = RAD_CRUISE_MSV_D / _f(RAD_CRUISE_SHIELD, a)
    return GCRCalibration(a, free)


CAL = calibrate()


def calibration_sensitivity(depths=(3.0, 5.0, 10.0, 16.0), lams=(8.0, 12.0, 20.0)) -> list[dict]:
    """Refit for other plausible (RAD depth, lam) pairs; report Moon prediction and 20 g/cm^2 deep-space rate."""
    global RAD_CRUISE_SHIELD, LAMBDA
    keep = RAD_CRUISE_SHIELD, LAMBDA
    rows = []
    try:
        for d in depths:
            for lam in lams:
                RAD_CRUISE_SHIELD, LAMBDA = d, lam
                c = calibrate()
                rows.append({"rad_depth": d, "lam": lam, "plateau_al": c.plateau_al, "moon_pred": c.predict_moon(),
                             "deep_space_20gcm2_solar_min": c.free_space_msv_d * SOLAR_FACTOR["min"] * _f(20.0, c.plateau_al)})
    finally:
        RAD_CRUISE_SHIELD, LAMBDA = keep
    return rows


def plateau(material: str) -> float:
    return CAL.plateau_al * PLATEAU_RATIO[material]


def gcr_rate(shield_gcm2: float, material: str = "aluminum", solar: str = "min",
             environment: str = "deep_space") -> float:
    """GCR dose equivalent rate (mSv/day) behind a uniform shield."""
    a = plateau(material)
    base = CAL.free_space_msv_d * SOLAR_FACTOR[solar]
    if environment == "deep_space":
        return base * _f(shield_gcm2, a)
    if environment == "mars_surface":
        hemi = _hemisphere_mean(MARS_ATMOS_COLUMN, CAL.plateau_al, x_local=0.0)
        # habitat shielding applied on top (approximate: multiply by its factor relative to none)
        return 0.5 * base * hemi * _f(shield_gcm2, a) * (1 + ALBEDO_FRACTION["mars"])
    if environment == "moon_surface":
        return 0.5 * base * _f(shield_gcm2, a) * (1 + ALBEDO_FRACTION["moon"])
    if environment == "leo":
        # ESTIMATE: scale the cited ISS value (solar-min epoch) by solar factor; ISS shielding implied
        return ISS_MSV_D * SOLAR_FACTOR[solar] / SOLAR_FACTOR["min"]
    raise ValueError(environment)


# SPE: ESTIMATE. August 1972-class event, BFO dose (mGy-Eq) behind water-equivalent depth.
# Exponential fit through ~1,000 mGy-Eq at 5 g/cm^2 and ~350 at 10 g/cm^2 (order of
# published HZETRN results for this event); hydrogen-rich shielding.
SPE_D0_MGY = 2_860.0
SPE_LAMBDA = 4.76  # g/cm^2


def spe_bfo_dose(shield_gcm2: float, severity: float = 1.0) -> float:
    """BFO dose from one large SPE (severity 1 = August 1972 class, ~1-in-100-year)."""
    return severity * SPE_D0_MGY * math.exp(-shield_gcm2 / SPE_LAMBDA)


def shelter_needed(hull_gcm2: float, severity: float = 1.0, limit: float = BFO_30DAY_LIMIT_MGY) -> float:
    """Extra water-equivalent shelter depth (g/cm^2) to stay under the 30-day BFO limit."""
    need = SPE_LAMBDA * math.log(severity * SPE_D0_MGY / limit) - hull_gcm2
    return max(need, 0.0)


@dataclass(frozen=True)
class DoseResult:
    transit_msv: float
    surface_msv: float
    spe_msv: float  # expected SPE contribution (sheltered)
    total_msv: float
    fraction_of_career_limit: float


def mission_dose(transit_days: float, surface_days: float = 0.0, surface: str = "mars_surface",
                 hull_gcm2: float = 20.0, hull_material: str = "aluminum", habitat_gcm2: float = 10.0,
                 solar: str = "min", spe_sheltered_msv: float = 0.05) -> DoseResult:
    """Total effective dose estimate for a mission.

    spe_sheltered_msv: ESTIMATE, expected SPE dose per transit day with a
    storm shelter (RAD saw ~5% of 1.84 mSv/day from SPEs in a quiet period).
    Dose equivalent is used as a stand-in for effective dose (they differ by
    roughly 10-20% for GCR; noted as an estimate).
    """
    t = transit_days * gcr_rate(hull_gcm2, hull_material, solar)
    s = surface_days * gcr_rate(habitat_gcm2, "regolith" if surface != "leo" else "aluminum", solar, surface) if surface_days else 0.0
    spe = transit_days * spe_sheltered_msv
    total = t + s + spe
    return DoseResult(t, s, spe, total, total / CAREER_LIMIT_MSV)


def max_transit_days_within_limit(hull_gcm2: float, material: str = "aluminum", solar: str = "min",
                                  surface_days: float = 0.0, surface: str = "mars_surface") -> float:
    """Longest transit time that keeps the whole mission under the career limit."""
    s = surface_days * gcr_rate(10.0, "regolith", solar, surface) if surface_days else 0.0
    per_day = gcr_rate(hull_gcm2, material, solar) + 0.05
    return max((CAREER_LIMIT_MSV - s) / per_day, 0.0)
