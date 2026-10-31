"""Interplanetary transfer windows: Lambert solver, two-body propagation, window search.

The Lambert solver uses universal variables with Stumpff functions (Bate, Mueller
and White, ch. 5; Curtis, Orbital Mechanics for Engineering Students, alg. 5.2).
It is verified two ways (gate SR-1): the solved arc is propagated with an
independent universal-Kepler propagator and must land on the target position,
and in the circular-coplanar limit it must reproduce the Hohmann transfer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .bodies import DAY, MU_SUN, Body, date_from_jd, jd_from_date, planet_state


def stumpff_c(z: float) -> float:
    if z > 1e-6:
        s = math.sqrt(z)
        return (1 - math.cos(s)) / z
    if z < -1e-6:
        s = math.sqrt(-z)
        return (math.cosh(s) - 1) / (-z)
    return 0.5 - z / 24 + z * z / 720


def stumpff_s(z: float) -> float:
    if z > 1e-6:
        s = math.sqrt(z)
        return (s - math.sin(s)) / s**3
    if z < -1e-6:
        s = math.sqrt(-z)
        return (math.sinh(s) - s) / s**3
    return 1 / 6 - z / 120 + z * z / 5040


def lambert(r1, r2, tof: float, mu: float = MU_SUN, prograde: bool = True):
    """Velocities (v1, v2) on the single-revolution conic from r1 to r2 in time tof."""
    r1 = np.asarray(r1, float)
    r2 = np.asarray(r2, float)
    n1, n2 = np.linalg.norm(r1), np.linalg.norm(r2)
    cross_z = np.cross(r1, r2)[2]
    cos_dnu = np.clip(np.dot(r1, r2) / (n1 * n2), -1.0, 1.0)
    dnu = math.acos(cos_dnu)
    if (prograde and cross_z < 0) or (not prograde and cross_z >= 0):
        dnu = 2 * math.pi - dnu
    A = math.sin(dnu) * math.sqrt(n1 * n2 / (1 - math.cos(dnu)))

    def y(z: float) -> float:
        return n1 + n2 + A * (z * stumpff_s(z) - 1) / math.sqrt(stumpff_c(z))

    def F(z: float) -> float:
        yz = y(z)
        return (yz / stumpff_c(z)) ** 1.5 * stumpff_s(z) + A * math.sqrt(yz) - math.sqrt(mu) * tof

    # Bracket: start low enough that y(z) > 0, then step up until F changes sign.
    z_lo = -4 * math.pi**2
    while y(z_lo) < 0:
        z_lo += 0.1
    z_hi = 4 * math.pi**2 - 1e-6
    if F(z_lo) * F(z_hi) > 0:
        raise ValueError("Lambert: no single-revolution solution in bracket")
    for _ in range(200):  # bisection then secant refinement is robust enough here
        z_mid = 0.5 * (z_lo + z_hi)
        if y(z_mid) < 0 or F(z_lo) * F(z_mid) <= 0:
            z_hi = z_mid
        else:
            z_lo = z_mid
        if z_hi - z_lo < 1e-12:
            break
    z = 0.5 * (z_lo + z_hi)
    yz = y(z)
    f = 1 - yz / n1
    g = A * math.sqrt(yz / mu)
    gdot = 1 - yz / n2
    v1 = (r2 - f * r1) / g
    v2 = (gdot * r2 - r1) / g
    return v1, v2


def propagate(r0, v0, dt: float, mu: float = MU_SUN):
    """Two-body propagation by universal Kepler's equation (independent of lambert())."""
    r0 = np.asarray(r0, float)
    v0 = np.asarray(v0, float)
    nr0 = np.linalg.norm(r0)
    vr0 = np.dot(r0, v0) / nr0
    alpha = 2 / nr0 - np.dot(v0, v0) / mu
    sqmu = math.sqrt(mu)
    chi = sqmu * abs(alpha) * dt
    for _ in range(100):
        z = alpha * chi**2
        C, S = stumpff_c(z), stumpff_s(z)
        Fv = nr0 * vr0 / sqmu * chi**2 * C + (1 - alpha * nr0) * chi**3 * S + nr0 * chi - sqmu * dt
        dF = nr0 * vr0 / sqmu * chi * (1 - alpha * chi**2 * S) + (1 - alpha * nr0) * chi**2 * C + nr0
        step = Fv / dF
        chi -= step
        if abs(step) < 1e-9:
            break
    z = alpha * chi**2
    C, S = stumpff_c(z), stumpff_s(z)
    f = 1 - chi**2 / nr0 * C
    g = dt - chi**3 / sqmu * S
    r = f * r0 + g * v0
    nr = np.linalg.norm(r)
    fdot = sqmu / (nr * nr0) * (alpha * chi**3 * S - chi)
    gdot = 1 - chi**2 / nr * C
    v = fdot * r0 + gdot * v0
    return r, v


def hohmann_vinf(r1: float, r2: float, mu: float = MU_SUN) -> tuple[float, float, float]:
    """Departure and arrival hyperbolic excess speeds (m/s) and time of flight (s)."""
    a_t = 0.5 * (r1 + r2)
    v1, v2 = math.sqrt(mu / r1), math.sqrt(mu / r2)
    vp = math.sqrt(mu * (2 / r1 - 1 / a_t))
    va = math.sqrt(mu * (2 / r2 - 1 / a_t))
    return abs(vp - v1), abs(v2 - va), math.pi * math.sqrt(a_t**3 / mu)


def burn_from_orbit(vinf: float, body: Body, altitude: float) -> float:
    """Impulsive delta-v between a circular orbit and a hyperbola with excess speed vinf."""
    r = body.radius + altitude
    return math.sqrt(vinf**2 + 2 * body.mu / r) - math.sqrt(body.mu / r)


def entry_speed(vinf: float, body: Body, interface_altitude: float) -> float:
    """Inertial speed at atmospheric interface for a direct hyperbolic approach."""
    return math.sqrt(vinf**2 + 2 * body.mu / (body.radius + interface_altitude))


@dataclass(frozen=True)
class Window:
    depart_jd: float
    arrive_jd: float
    vinf_depart: float  # m/s
    vinf_arrive: float  # m/s
    c3_depart: float  # km^2/s^2

    @property
    def tof_days(self) -> float:
        return self.arrive_jd - self.depart_jd

    @property
    def depart_date(self) -> str:
        return date_from_jd(self.depart_jd)

    @property
    def arrive_date(self) -> str:
        return date_from_jd(self.arrive_jd)


def transfer(dep: str, arr: str, jd_dep: float, jd_arr: float) -> Window:
    r1, vp1 = planet_state(dep, jd_dep)
    r2, vp2 = planet_state(arr, jd_arr)
    v1, v2 = lambert(r1, r2, (jd_arr - jd_dep) * DAY)
    vinf_d = float(np.linalg.norm(v1 - np.asarray(vp1)))
    vinf_a = float(np.linalg.norm(v2 - np.asarray(vp2)))
    return Window(jd_dep, jd_arr, vinf_d, vinf_a, (vinf_d / 1e3) ** 2)


def search_window(
    dep: str,
    arr: str,
    start: tuple[int, int, int],
    span_days: float,
    tof_range: tuple[float, float],
    weight_arrival: float = 1.0,
    step_days: float = 2.0,
) -> tuple[Window, list[Window]]:
    """Grid search (porkchop) minimising vinf_depart + weight * vinf_arrive."""
    jd0 = jd_from_date(*start)
    best = None
    grid: list[Window] = []
    for dd in np.arange(0.0, span_days, step_days):
        for tof in np.arange(tof_range[0], tof_range[1], step_days):
            try:
                w = transfer(dep, arr, jd0 + dd, jd0 + dd + tof)
            except ValueError:
                continue
            grid.append(w)
            cost = w.vinf_depart + weight_arrival * w.vinf_arrive
            if best is None or cost < best[0]:
                best = (cost, w)
    assert best is not None
    return best[1], grid
