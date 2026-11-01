"""South-pole site candidates, a weighted score, and a synthetic illumination series.

Illumination figures are cited. Distances to permanently shadowed regions (PSRs),
slopes and Earth visibility are estimates from published maps, to be replaced by
a LOLA terrain analysis.

The synthetic illumination series feeds the power balance. Near a pole the Sun
circles the horizon once per synodic month (29.53 days) while its elevation
swings by +/-1.54 degrees over a draconic-type period (346.6 days, the Sun's
declination cycle seen from the Moon). A site off the pole by colatitude c sees
an extra c*cos(hour angle) swing. Terrain is a smooth random horizon profile
whose offset is solved so the lit fraction matches the cited value. That gives
a time series with the right lit fraction and realistic multi-day dark spells,
but it is not a terrain-exact ephemeris.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from .provenance import Value

GLASER = "Glaser et al. 2014, Icarus 243, 78 (19-year LOLA study)"
BUSSEY = "Bussey et al. 2010, via https://en.wikipedia.org/wiki/Peak_of_eternal_light"
WIKI_PEL = "https://en.wikipedia.org/wiki/Peak_of_eternal_light (table of 2020 illumination)"
NODA = "Noda et al. 2008 (SELENE), via https://en.wikipedia.org/wiki/Peak_of_eternal_light"

SYNODIC_DAYS = 29.530589
SUN_DECL_PERIOD_DAYS = 346.62
SUN_DECL_AMP_DEG = 1.54
SUN_RADIUS_DEG = 0.2665


@dataclass(frozen=True)
class Site:
    name: str
    lat_deg: float
    lon_deg: float
    illumination: Value  # fraction of time lit, at about 10 m mast height where known
    longest_dark_days: Value
    psr_distance_km: Value  # to the nearest large ice-bearing cold trap
    slope_deg: Value
    earth_visibility: Value  # fraction of time Earth is above the horizon (direct-to-Earth comms)


SITES: tuple[Site, ...] = (
    Site(
        "Connecting Ridge (Shackleton to de Gerlache)", -89.45, -137.3,
        Value(0.9565, "-", "cited", GLASER + ", 10 m above ground; 92.27% at 2 m"),
        Value(4.0, "days", "cited", GLASER + ", 'typically only 3-5 days' at best sites"),
        Value(3.0, "km", "estimated", "Shackleton and de Gerlache PSRs flank the ridge"),
        Value(6.0, "deg", "estimated", "ridge crest"),
        Value(0.55, "-", "estimated", "near-side limb, libration dependent"),
    ),
    Site(
        "Shackleton rim, point D", -88.79, 124.5,
        Value(0.86, "-", "cited", WIKI_PEL + ", 58-100% by lunar day"),
        Value(7.0, "days", "estimated", "worst lunar day lit 58%"),
        Value(2.0, "km", "estimated", "on the Shackleton PSR rim"),
        Value(8.0, "deg", "estimated", "crater rim"),
        Value(0.45, "-", "estimated", "far-side facing, libration dependent"),
    ),
    Site(
        "de Gerlache rim, point C", -88.71, -68.7,
        Value(0.85, "-", "cited", WIKI_PEL + ", 64-98% by lunar day"),
        Value(6.0, "days", "estimated", "worst lunar day lit 64%"),
        Value(2.0, "km", "estimated", "on the de Gerlache PSR rim"),
        Value(8.0, "deg", "estimated", "crater rim"),
        Value(0.55, "-", "estimated", "near-side limb"),
    ),
    Site(
        "Malapert massif, M1", -86.04, 2.7,
        Value(0.74, "-", "cited", BUSSEY + ", 2020"),
        Value(9.0, "days", "estimated", "worst lunar day lit 54%"),
        Value(15.0, "km", "estimated", "smaller cold traps nearby, large PSRs farther"),
        Value(10.0, "deg", "estimated", "massif flank"),
        Value(0.95, "-", "estimated", "near-side peak with near-continuous Earth view"),
    ),
    Site(
        "Peary crater rim (north pole)", 88.6, 33.0,
        Value(0.89, "-", "cited", NODA),
        Value(6.0, "days", "estimated", ""),
        Value(25.0, "km", "estimated", "north polar cold traps are smaller and ice evidence weaker"),
        Value(6.0, "deg", "estimated", ""),
        Value(0.5, "-", "estimated", ""),
    ),
)

# Weights are a design choice, shown in the report so they can be argued with.
WEIGHTS = {
    "power": 0.30,  # lit fraction
    "night": 0.20,  # shorter dark spells shrink storage
    "ice": 0.25,  # haul distance to the ice
    "terrain": 0.10,  # slope for pads and construction
    "comms": 0.15,  # direct-to-Earth link
}


def score(site: Site) -> dict[str, float]:
    """Normalised 0-1 sub-scores and a weighted total."""
    s = {
        "power": site.illumination.value,
        "night": max(0.0, 1.0 - site.longest_dark_days.value / 15.0),
        "ice": math.exp(-site.psr_distance_km.value / 10.0),
        "terrain": max(0.0, 1.0 - site.slope_deg.value / 15.0),
        "comms": site.earth_visibility.value,
    }
    s["total"] = sum(WEIGHTS[k] * s[k] for k in WEIGHTS)
    return s


def rank_sites() -> list[tuple[Site, dict[str, float]]]:
    return sorted(((s, score(s)) for s in SITES), key=lambda t: -t[1]["total"])


# --- Synthetic illumination -------------------------------------------------

def _horizon(az: np.ndarray, roughness_deg: float, seed: int) -> np.ndarray:
    """Smooth random horizon elevation (deg) versus azimuth (rad), zero mean."""
    rng = np.random.default_rng(seed)
    h = np.zeros_like(az)
    for k in range(1, 9):
        amp = rng.normal() / k
        h += amp * np.cos(k * az + rng.uniform(0, 2 * math.pi))
    return roughness_deg * h / np.std(h)


def _lit_fraction_of_disk(elev_minus_horizon: np.ndarray) -> np.ndarray:
    x = np.clip(elev_minus_horizon / SUN_RADIUS_DEG, -1.0, 1.0)
    # Area of a disk above a chord at height x (in radii), normalised.
    return (np.arccos(-x) + x * np.sqrt(1 - x**2)) / math.pi


def illumination_series(
    site: Site,
    hours: float = 2 * 8766.0,
    dt_h: float = 1.0,
    roughness_deg: float = 0.5,
    seed: int = 7,
) -> np.ndarray:
    """Fraction of the solar disk visible, hourly, calibrated to the site's lit fraction."""
    t = np.arange(0.0, hours, dt_h) / 24.0  # days
    hour_angle = 2 * math.pi * t / SYNODIC_DAYS
    decl = SUN_DECL_AMP_DEG * np.sin(2 * math.pi * t / SUN_DECL_PERIOD_DAYS)
    colat = 90.0 - abs(site.lat_deg)
    elev = decl + colat * np.cos(hour_angle)
    az = (hour_angle + math.radians(site.lon_deg)) % (2 * math.pi)
    hz = _horizon(az, roughness_deg, seed)

    target = site.illumination.value

    def lit(offset: float) -> float:
        return float(np.mean(_lit_fraction_of_disk(elev - hz - offset))) - target

    offset = brentq(lit, -10.0, 10.0, xtol=1e-6)
    return _lit_fraction_of_disk(elev - hz - offset)


def dark_spells_days(series: np.ndarray, dt_h: float = 1.0, threshold: float = 0.05) -> np.ndarray:
    """Durations (days) of continuous periods with less than `threshold` of the disk lit."""
    dark = series < threshold
    spells, run = [], 0
    for d in dark:
        if d:
            run += 1
        elif run:
            spells.append(run)
            run = 0
    if run:
        spells.append(run)
    return np.array(spells, dtype=float) * dt_h / 24.0
