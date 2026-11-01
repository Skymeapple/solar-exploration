"""Planet ephemeris, Kepler propagation and a Lambert solver.

Ephemeris: CITED. Keplerian elements and rates from E. M. Standish,
"Keplerian Elements for Approximate Positions of the Major Planets", JPL
Solar System Dynamics, Table 1 (valid 1800 to 2050 AD), J2000 ecliptic frame.
https://ssd.jpl.nasa.gov/planets/approx_pos.html
Accuracy of that table is of order 0.01 deg in longitude for Earth and Mars,
plenty for mission design trades.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from ..mission import AU, MU_SUN

DEG = math.pi / 180
DAY = 86400.0
J2000_JD = 2451545.0

# a [AU], e, I [deg], L [deg], long. perihelion [deg], long. asc. node [deg]; then rates per century
_ELEMENTS = {
    "mercury": ((0.38709927, 0.20563593, 7.00497902, 252.25032350, 77.45779628, 48.33076593),
                (0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081)),
    "venus": ((0.72333566, 0.00677672, 3.39467605, 181.97909950, 131.60246718, 76.67984255),
              (0.00000390, -0.00004107, -0.00078890, 58517.81538729, 0.00268329, -0.27769418)),
    "earth": ((1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
              (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "mars": ((1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
             (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
    "jupiter": ((5.20288700, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909),
                (-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106)),
    "saturn": ((9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448),
               (-0.00125060, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794)),
}


def jd_from_date(d: str | datetime) -> float:
    """Julian date from 'YYYY-MM-DD' or a datetime (UTC; TT-UTC ignored)."""
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp() / DAY + 2440587.5


def date_from_jd(jd: float) -> str:
    return datetime.fromtimestamp((jd - 2440587.5) * DAY, tz=timezone.utc).strftime("%Y-%m-%d")


def solve_kepler(M: float, e: float) -> float:
    E = M if e < 0.8 else math.pi
    for _ in range(50):
        dE = (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
        E -= dE
        if abs(dE) < 1e-13:
            break
    return E


def _rotation(Om: float, inc: float, w: float) -> np.ndarray:
    cO, sO, ci, si, cw, sw = map(lambda f: f, (math.cos(Om), math.sin(Om), math.cos(inc), math.sin(inc), math.cos(w), math.sin(w)))
    return np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci],
        [sw * si, cw * si],
    ])


def planet_state(name: str, jd: float) -> tuple[np.ndarray, np.ndarray]:
    """Heliocentric position (m) and velocity (m/s), J2000 ecliptic."""
    el0, rate = _ELEMENTS[name]
    T = (jd - J2000_JD) / 36525.0
    a, e, inc, L, varpi, Om = (x0 + r * T for x0, r in zip(el0, rate))
    a *= AU
    inc, L, varpi, Om = inc * DEG, L * DEG, varpi * DEG, Om * DEG
    w = varpi - Om
    M = math.remainder(L - varpi, 2 * math.pi)
    E = solve_kepler(M, e)
    n = math.sqrt(MU_SUN / a**3)
    b = a * math.sqrt(1 - e * e)
    x, y = a * (math.cos(E) - e), b * math.sin(E)
    Edot = n / (1 - e * math.cos(E))
    vx, vy = -a * math.sin(E) * Edot, b * math.cos(E) * Edot
    R = _rotation(Om, inc, w)
    return R @ np.array([x, y]), R @ np.array([vx, vy])


def elements_from_state(r: np.ndarray, v: np.ndarray, mu: float = MU_SUN) -> dict:
    rn, vn = np.linalg.norm(r), np.linalg.norm(v)
    h = np.cross(r, v)
    evec = np.cross(v, h) / mu - r / rn
    energy = vn**2 / 2 - mu / rn
    a = -mu / (2 * energy)
    return {"a": a, "e": float(np.linalg.norm(evec)), "h": h, "evec": evec}


def propagate(r0: np.ndarray, v0: np.ndarray, dt: float, mu: float = MU_SUN) -> tuple[np.ndarray, np.ndarray]:
    """Two-body propagation with universal variables (any conic)."""
    r0n = np.linalg.norm(r0)
    vr0 = np.dot(r0, v0) / r0n
    alpha = 2 / r0n - np.dot(v0, v0) / mu
    sq = math.sqrt(mu)
    chi = sq * abs(alpha) * dt if alpha > 1e-12 else sq * dt / r0n
    for _ in range(100):
        z = alpha * chi**2
        C, S = _stumpff_c(z), _stumpff_s(z)
        F = r0n * vr0 / sq * chi**2 * C + (1 - alpha * r0n) * chi**3 * S + r0n * chi - sq * dt
        dF = r0n * vr0 / sq * chi * (1 - z * S) + (1 - alpha * r0n) * chi**2 * C + r0n
        step = F / dF
        chi -= step
        if abs(step) < 1e-9:
            break
    z = alpha * chi**2
    C, S = _stumpff_c(z), _stumpff_s(z)
    f = 1 - chi**2 / r0n * C
    g = dt - chi**3 / sq * S
    r = f * r0 + g * v0
    rn = np.linalg.norm(r)
    fd = sq / (rn * r0n) * (alpha * chi**3 * S - chi)
    gd = 1 - chi**2 / rn * C
    return r, fd * r0 + gd * v0


def _stumpff_c(z: float) -> float:
    if z > 1e-8:
        return (1 - math.cos(math.sqrt(z))) / z
    if z < -1e-8:
        return (math.cosh(math.sqrt(-z)) - 1) / (-z)
    return 0.5 - z / 24


def _stumpff_s(z: float) -> float:
    if z > 1e-8:
        s = math.sqrt(z)
        return (s - math.sin(s)) / s**3
    if z < -1e-8:
        s = math.sqrt(-z)
        return (math.sinh(s) - s) / s**3
    return 1 / 6 - z / 120


def lambert(r1: np.ndarray, r2: np.ndarray, tof: float, mu: float = MU_SUN, prograde: bool = True):
    """Zero-revolution Lambert solution (universal variables, bisection on z).

    Returns (v1, v2) in m/s, or None when no solution is found.
    """
    r1n, r2n = np.linalg.norm(r1), np.linalg.norm(r2)
    cos_dnu = np.clip(np.dot(r1, r2) / (r1n * r2n), -1, 1)
    dnu = math.acos(cos_dnu)
    cz = np.cross(r1, r2)[2]
    if (prograde and cz < 0) or (not prograde and cz >= 0):
        dnu = 2 * math.pi - dnu
    A = math.sin(dnu) * math.sqrt(r1n * r2n / (1 - math.cos(dnu)))
    if abs(A) < 1e-9:
        return None

    def y_of(z):
        return r1n + r2n + A * (z * _stumpff_s(z) - 1) / math.sqrt(_stumpff_c(z))

    def t_of(z):
        y = y_of(z)
        if y < 0:
            return -1.0
        C, S = _stumpff_c(z), _stumpff_s(z)
        return ((y / C) ** 1.5 * S + A * math.sqrt(y)) / math.sqrt(mu)

    lo, hi = -4 * math.pi**2, 4 * math.pi**2 - 1e-6
    # raise lo until y >= 0 (needed when A > 0)
    while y_of(lo) < 0:
        lo = 0.5 * (lo + hi) if lo > -1 else lo / 2 + 0.1
        if lo > hi - 1e-6:
            return None
    if t_of(lo) > tof or t_of(hi) < tof:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_of(mid) < tof:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-11:
            break
    z = 0.5 * (lo + hi)
    y = y_of(z)
    f = 1 - y / r1n
    g = A * math.sqrt(y / mu)
    gd = 1 - y / r2n
    v1 = (r2 - f * r1) / g
    v2 = (gd * r2 - r1) / g
    return v1, v2
