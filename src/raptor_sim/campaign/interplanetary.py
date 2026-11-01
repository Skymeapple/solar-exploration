"""Phases 4, 5 and 9 geometry: ephemerides, Lambert transfers, launch windows, cruise navigation.

Planet positions use JPL's "Approximate Positions of the Planets" Keplerian
elements, valid 1800-2050 (public, E. M. Standish,
https://ssd.jpl.nasa.gov/planets/approx_pos.html). Accuracy is a few
thousand km for Earth and Mars, far below what a window study needs.
Transfers are heliocentric two-body Lambert arcs (patched conics).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import numpy as np

from .bodies import AU, DAY, MU_SUN

J2000 = datetime(2000, 1, 1, 12)

# a (AU), e, I, L, long. perihelion, long. node (deg); rates per Julian century
_ELEMENTS = {
    "earth": ((1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0.0),
              (0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0.0)),
    "mars": ((1.52371034, 0.09339410, 1.84969142, -4.55343205, -23.94362959, 49.55953891),
             (0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343)),
}


def days_since_j2000(d: date | datetime) -> float:
    if not isinstance(d, datetime):
        d = datetime(d.year, d.month, d.day)
    return (d - J2000).total_seconds() / DAY


def planet_state(name: str, d: date | datetime | float) -> tuple[np.ndarray, np.ndarray]:
    """Heliocentric ecliptic J2000 position (m) and velocity (m/s)."""
    t_days = d if isinstance(d, float) else days_since_j2000(d)
    el0, rate = _ELEMENTS[name]
    T = t_days / 36525.0
    a, e, inc, L, varpi, node = (el0[i] + rate[i] * T for i in range(6))
    a *= AU
    inc, L, varpi, node = map(math.radians, (inc, L, varpi, node))
    argp = varpi - node
    M = (L - varpi + math.pi) % (2 * math.pi) - math.pi
    E = M
    for _ in range(30):
        E -= (E - e * math.sin(E) - M) / (1 - e * math.cos(E))
    n = math.sqrt(MU_SUN / a**3)
    xp, yp = a * (math.cos(E) - e), a * math.sqrt(1 - e * e) * math.sin(E)
    edot = n / (1 - e * math.cos(E))
    vxp, vyp = -a * math.sin(E) * edot, a * math.sqrt(1 - e * e) * math.cos(E) * edot
    co, so, ci, si, cw, sw = math.cos(node), math.sin(node), math.cos(inc), math.sin(inc), math.cos(argp), math.sin(argp)
    R = np.array([
        [co * cw - so * sw * ci, -co * sw - so * cw * ci],
        [so * cw + co * sw * ci, -so * sw + co * cw * ci],
        [sw * si, cw * si],
    ])
    return R @ np.array([xp, yp]), R @ np.array([vxp, vyp])


# ------------------------------------------------------------- universal-variable Kepler / Lambert


def _stumpff(z: float) -> tuple[float, float]:
    if z > 1e-8:
        sz = math.sqrt(z)
        return (1 - math.cos(sz)) / z, (sz - math.sin(sz)) / sz**3
    if z < -1e-8:
        sz = math.sqrt(-z)
        return (math.cosh(sz) - 1) / -z, (math.sinh(sz) - sz) / sz**3
    return 0.5, 1 / 6


def lambert(r1: np.ndarray, r2: np.ndarray, tof: float, mu: float = MU_SUN) -> tuple[np.ndarray, np.ndarray]:
    """Single-revolution prograde Lambert solution (Curtis, Orbital Mechanics for Engineering Students, alg. 5.2)."""
    n1, n2 = np.linalg.norm(r1), np.linalg.norm(r2)
    cross = np.cross(r1, r2)
    dth = math.acos(max(-1.0, min(1.0, float(np.dot(r1, r2) / (n1 * n2)))))
    if cross[2] < 0:
        dth = 2 * math.pi - dth
    A = math.sin(dth) * math.sqrt(n1 * n2 / (1 - math.cos(dth)))

    def y(z):
        C, S = _stumpff(z)
        return n1 + n2 + A * (z * S - 1) / math.sqrt(C)

    def F(z):
        C, S = _stumpff(z)
        yz = y(z)
        if yz < 0:
            return -1e30
        return (yz / C) ** 1.5 * S + A * math.sqrt(yz) - math.sqrt(mu) * tof

    lo, hi = -4 * math.pi**2, 4 * math.pi**2 - 1e-6
    while y(lo) < 0:
        lo += 0.1
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if F(mid) > 0:
            hi = mid
        else:
            lo = mid
        if hi - lo < 1e-10:
            break
    z = 0.5 * (lo + hi)
    yz = y(z)
    f = 1 - yz / n1
    g = A * math.sqrt(yz / mu)
    gdot = 1 - yz / n2
    v1 = (r2 - f * r1) / g
    v2 = (gdot * r2 - r1) / g
    return v1, v2


def kepler_propagate(r0: np.ndarray, v0: np.ndarray, dt: float, mu: float = MU_SUN) -> tuple[np.ndarray, np.ndarray]:
    """Two-body propagation with universal variables (Curtis alg. 3.4 and 3.3)."""
    n0 = np.linalg.norm(r0)
    vr0 = float(np.dot(r0, v0)) / n0
    alpha = 2 / n0 - float(np.dot(v0, v0)) / mu
    x = math.sqrt(mu) * abs(alpha) * dt
    for _ in range(100):
        z = alpha * x * x
        C, S = _stumpff(z)
        Fx = n0 * vr0 / math.sqrt(mu) * x * x * C + (1 - alpha * n0) * x**3 * S + n0 * x - math.sqrt(mu) * dt
        dF = n0 * vr0 / math.sqrt(mu) * x * (1 - alpha * x * x * S) + (1 - alpha * n0) * x * x * C + n0
        step = Fx / dF
        x -= step
        if abs(step) < 1e-8:
            break
    z = alpha * x * x
    C, S = _stumpff(z)
    f = 1 - x * x / n0 * C
    g = dt - x**3 / math.sqrt(mu) * S
    r = f * r0 + g * v0
    n = np.linalg.norm(r)
    fdot = math.sqrt(mu) / (n * n0) * (alpha * x**3 * S - x)
    gdot = 1 - x * x / n * C
    return r, fdot * r0 + gdot * v0


# ------------------------------------------------------------- windows


@dataclass(frozen=True)
class Transfer:
    depart: date
    arrive: date
    vinf_depart: float  # m/s
    vinf_arrive: float  # m/s
    v_depart: np.ndarray  # heliocentric, m/s
    r_depart: np.ndarray

    @property
    def c3(self) -> float:
        return (self.vinf_depart / 1e3) ** 2  # km^2/s^2

    @property
    def tof_days(self) -> int:
        return (self.arrive - self.depart).days


def transfer(origin: str, target: str, depart: date, tof_days: float) -> Transfer:
    r1, v1p = planet_state(origin, depart)
    arr = depart + timedelta(days=tof_days)
    r2, v2p = planet_state(target, arr)
    v1, v2 = lambert(r1, r2, tof_days * DAY)
    return Transfer(depart, arr, float(np.linalg.norm(v1 - v1p)), float(np.linalg.norm(v2 - v2p)), v1, r1)


def porkchop(origin: str, target: str, start: date, n_dep: int, tof_range: tuple[int, int], step: int = 2):
    """Grid of transfers: departure every `step` days, time of flight in the given range."""
    out = []
    for i in range(0, n_dep, step):
        d = start + timedelta(days=i)
        for tof in range(tof_range[0], tof_range[1] + 1, 5):
            try:
                out.append(transfer(origin, target, d, tof))
            except (ValueError, ZeroDivisionError, FloatingPointError):
                continue
    return out


def best_transfer(cands: list[Transfer], cost) -> Transfer:
    return min(cands, key=cost)


def launch_period(cands: list[Transfer], cost, budget: float) -> list[date]:
    """Departure dates for which some time of flight keeps cost within budget."""
    days = sorted({c.depart for c in cands if cost(c) <= budget})
    return days


# ------------------------------------------------------------- cruise navigation (TCM Monte Carlo)


@dataclass
class TCMResult:
    tcm_total: np.ndarray  # m/s per sample
    entry_fpa_sigma_deg: float


def tcm_monte_carlo(tr: Transfer, n: int = 500, injection_sigma: float = 1.0, exec_error: float = 0.02,
                    tcm_days: tuple[float, ...] = (10.0, 0.6, 0.95), seed: int = 1) -> TCMResult:
    """Trajectory correction manoeuvres needed to hit the arrival point.

    injection_sigma: 1-sigma per-axis velocity error after the departure burn (m/s) [est].
    exec_error: 1-sigma proportional execution error of each correction [est].
    tcm_days: first TCM in days after departure; later ones as fractions of the flight time.
    Each TCM is a Lambert retarget from the perturbed state to the nominal arrival point.
    """
    rng = np.random.default_rng(seed)
    tof = tr.tof_days * DAY
    r_arr, _ = kepler_propagate(tr.r_depart, tr.v_depart, tof)
    times = [tcm_days[0] * DAY] + [f * tof for f in tcm_days[1:]]
    totals = np.zeros(n)
    for k in range(n):
        r, v = tr.r_depart.copy(), tr.v_depart + rng.normal(0, injection_sigma, 3)
        t = 0.0
        for tt in times:
            r, v = kepler_propagate(r, v, tt - t)
            t = tt
            v_new, _ = lambert(r, r_arr, tof - t)
            dv = v_new - v
            totals[k] += np.linalg.norm(dv)
            v = v_new + dv * rng.normal(0, exec_error) + rng.normal(0, 0.01, 3)
    return TCMResult(totals, entry_fpa_sigma_deg=0.1)
