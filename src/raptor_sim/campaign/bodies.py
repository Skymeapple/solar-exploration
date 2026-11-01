"""Planet constants and atmosphere models.

Earth: US Standard Atmosphere 1976 (public, NOAA/NASA/USAF 1976) to 86 km,
then an exponential tail with a 7 km scale height (estimate).
Mars: NASA Glenn Research Center simple Mars atmosphere model (public,
https://www.grc.nasa.gov/www/k-12/airplane/atmosmrm.html), fitted to Mars
Global Surveyor data. Density is scaled by a dispersion factor in Monte Carlo
runs to cover seasons and dust storms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Public constants (IAU / JPL)
MU_SUN = 1.32712440018e20
MU_EARTH = 3.986004418e14
MU_MARS = 4.282837e13
R_EARTH = 6.371e6
R_MARS = 3.3895e6
OMEGA_EARTH = 7.2921159e-5  # rad/s
OMEGA_MARS = 7.088218e-5  # rad/s
G_EARTH = 9.80665
G_MARS = 3.721
AU = 1.495978707e11
DAY = 86400.0

# US 1976 layers: base geopotential altitude (m), base temperature (K), lapse rate (K/m)
_US76 = [
    (0.0, 288.15, -0.0065),
    (11_000.0, 216.65, 0.0),
    (20_000.0, 216.65, 0.001),
    (32_000.0, 228.65, 0.0028),
    (47_000.0, 270.65, 0.0),
    (51_000.0, 270.65, -0.0028),
    (71_000.0, 214.65, -0.002),
    (84_852.0, 186.946, 0.0),
]
_R_AIR = 287.053
_GAMMA_AIR = 1.4


def _us76_base_pressures() -> list[float]:
    p = [101_325.0]
    for i in range(1, len(_US76)):
        h0, t0, lr = _US76[i - 1]
        h1 = _US76[i][0]
        if lr == 0.0:
            p.append(p[-1] * math.exp(-G_EARTH * (h1 - h0) / (_R_AIR * t0)))
        else:
            t1 = t0 + lr * (h1 - h0)
            p.append(p[-1] * (t1 / t0) ** (-G_EARTH / (lr * _R_AIR)))
    return p


_US76_P = _us76_base_pressures()


@dataclass(frozen=True)
class AtmState:
    density: float  # kg/m^3
    pressure: float  # Pa
    sound_speed: float  # m/s


def earth_atmosphere(h: float) -> AtmState:
    """Geometric altitude h (m) -> density, pressure, speed of sound."""
    if h < 0:
        h = 0.0
    hg = R_EARTH * h / (R_EARTH + h)  # geopotential altitude
    if hg > 86_000.0:
        t = 186.946
        p86 = earth_atmosphere(86_000.0 * R_EARTH / (R_EARTH - 86_000.0)).pressure
        p = p86 * math.exp(-(hg - 86_000.0) / 7_000.0)
    else:
        i = max(k for k in range(len(_US76)) if _US76[k][0] <= hg)
        h0, t0, lr = _US76[i]
        t = t0 + lr * (hg - h0)
        if lr == 0.0:
            p = _US76_P[i] * math.exp(-G_EARTH * (hg - h0) / (_R_AIR * t0))
        else:
            p = _US76_P[i] * (t / t0) ** (-G_EARTH / (lr * _R_AIR))
    rho = p / (_R_AIR * t)
    return AtmState(rho, p, math.sqrt(_GAMMA_AIR * _R_AIR * t))


def mars_atmosphere(h: float, density_factor: float = 1.0) -> AtmState:
    """NASA Glenn Mars model. h in metres above the reference radius."""
    if h < 0:
        h = 0.0
    t_c = -31.0 - 0.000998 * h if h < 7_000.0 else -23.4 - 0.00222 * h
    t = max(t_c + 273.15, 130.0)
    p = 699.0 * math.exp(-0.00009 * h)  # Pa
    rho = density_factor * p / (192.1 * t)  # Glenn model gas constant
    return AtmState(rho, p, math.sqrt(1.29 * 188.92 * t))
