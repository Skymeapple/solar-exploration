"""Planar 3-DOF atmospheric entry for crew return: g-load, heating, corridor.

Equations of motion: point mass over a spherical, non-rotating planet.
Atmosphere: exponential (CITED scale parameters):
- Earth: rho0 = 1.225 kg/m^3, H = 7.2 km (US Standard Atmosphere fit near 40-80 km is 6.5-7.5 km).
- Mars: rho0 = 0.020 kg/m^3, H = 11.1 km (NASA Mars Fact Sheet).
Convective stagnation heating: Sutton-Graves, q = k sqrt(rho / rn) V^3,
k = 1.7415e-4 (Earth) and 1.9027e-4 (Mars) in SI (CITED, Sutton & Graves 1971).
Radiative heating: ESTIMATE, a Tauber-Sutton style fit for Earth,
q_r = 4.736e4 * rn^a * rho^1.22 * f(V), f(V) tabulated 9-16 km/s
(Tauber & Sutton 1991, values from the standard textbook table, rounded).

Vehicle presets are ESTIMATES built from public dimensions:
- Orion-class capsule: 5.0 m diameter, ~9,300 kg at entry, Cd ~1.3, L/D ~0.27.
- Starship-class ship: 9 m x 50 m body flying belly-first, ~150 t at Earth entry
  (empty, crew and returned cargo), effective Cd*A ~ 450 m^2 * 1.0, L/D ~0.25 (no public figure).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.integrate import solve_ivp

from ..constants import G0
from ..mission import MU_EARTH, MU_MARS, R_EARTH, R_MARS

PLANETS = {
    "earth": dict(mu=MU_EARTH, R=R_EARTH, rho0=1.225, H=7_200.0, k_sg=1.7415e-4, h_ei=120e3),
    "mars": dict(mu=MU_MARS, R=R_MARS, rho0=0.020, H=11_100.0, k_sg=1.9027e-4, h_ei=125e3),
}

# Tauber-Sutton f(V) for Earth (V in km/s -> f), ESTIMATE (rounded textbook table)
_TS_V = np.array([9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5, 16.0])
_TS_F = np.array([1.5, 4.3, 9.7, 19.5, 35.0, 55.0, 81.0, 115.0, 151.0, 197.0, 230.0, 251.0, 270.0, 285.0, 300.0])


@dataclass(frozen=True)
class EntryVehicle:
    name: str
    mass: float  # kg
    ref_area: float  # m^2
    cd: float
    lift_to_drag: float
    nose_radius: float  # m

    @property
    def ballistic_coeff(self) -> float:
        return self.mass / (self.cd * self.ref_area)


CAPSULE_ORION_CLASS = EntryVehicle("Orion-class capsule", 9_300.0, math.pi * 2.5**2, 1.30, 0.27, 6.0)
SHIP_STARSHIP_CLASS = EntryVehicle("Starship-class ship (Earth)", 150_000.0, 450.0, 1.0, 0.25, 4.5)
SHIP_STARSHIP_CLASS_MARS = EntryVehicle("Starship-class ship (Mars, crew + cargo)", 250_000.0, 450.0, 1.0, 0.25, 4.5)


@dataclass
class EntryResult:
    peak_g: float
    peak_heat_flux: float  # W/m^2, convective + radiative at stagnation point
    peak_convective: float
    peak_radiative: float
    heat_load: float  # J/m^2
    skipped: bool
    final_speed: float
    t: np.ndarray
    h: np.ndarray
    v: np.ndarray
    g: np.ndarray
    duration_above_3g: float  # s


def radiative_flux_earth(rho: float, v: float, rn: float) -> float:
    vk = v / 1000
    if vk < _TS_V[0]:
        return 0.0
    f = float(np.interp(vk, _TS_V, _TS_F))
    a = min(1.072e6 * v**-1.88 * rho**-0.325, 1.0) if rho > 0 else 1.0
    return 4.736e4 * rn**a * rho**1.22 * f * 1e4  # W/m^2 (fit is in W/cm^2)


def simulate_entry(vehicle: EntryVehicle, planet: str, v_entry: float, gamma_deg: float,
                   bank: float | Callable[[float, float, float, float], float] = 0.0,
                   gravity: bool = True, h_end: float = 15e3) -> EntryResult:
    """Integrate from the entry interface (gamma negative = descending).

    bank: constant bank angle in degrees (0 = full lift up, 180 = full lift down),
    or a function bank(t, h, v, gamma_rad) -> degrees for guided/skip profiles.
    """
    p = PLANETS[planet]
    mu, R, rho0, H = p["mu"], p["R"], p["rho0"], p["H"]
    beta = vehicle.ballistic_coeff
    ld = vehicle.lift_to_drag
    bank_fn = bank if callable(bank) else (lambda *_: bank)

    def rhs(t, y):
        v, gam, h, _ = y
        r = R + h
        rho = rho0 * math.exp(-h / H)
        drag = 0.5 * rho * v * v / beta
        lift = ld * drag * math.cos(math.radians(bank_fn(t, h, v, gam)))
        g = mu / r**2 if gravity else 0.0
        dv = -drag - g * math.sin(gam)
        dgam = (lift - (g - v * v / r) * math.cos(gam)) / v if gravity else lift / v
        return [dv, dgam, v * math.sin(gam), v * math.cos(gam) * R / r]

    def ground(t, y):
        return y[2] - h_end
    ground.terminal, ground.direction = True, -1

    def skip(t, y):
        return y[2] - (p["h_ei"] + 1.0)
    skip.terminal, skip.direction = True, 1

    def slow(t, y):
        return y[0] - 300.0
    slow.terminal = True

    y0 = [v_entry, math.radians(gamma_deg), p["h_ei"], 0.0]
    sol = solve_ivp(rhs, (0, 4_000), y0, events=[ground, skip, slow], max_step=0.5, rtol=1e-8, atol=1e-6)
    v, gam, h = sol.y[0], sol.y[1], sol.y[2]
    rho = rho0 * np.exp(-h / H)
    drag = 0.5 * rho * v**2 / beta
    aero = drag * math.sqrt(1 + ld**2) / G0
    qc = p["k_sg"] * np.sqrt(rho / vehicle.nose_radius) * v**3
    qr = np.array([radiative_flux_earth(r_, v_, vehicle.nose_radius) for r_, v_ in zip(rho, v)]) if planet == "earth" else np.zeros_like(v)
    q = qc + qr
    dt = np.diff(sol.t)
    above = float(np.sum(dt[(aero[:-1] > 3.0)]))
    return EntryResult(
        peak_g=float(aero.max()), peak_heat_flux=float(q.max()), peak_convective=float(qc.max()),
        peak_radiative=float(qr.max()), heat_load=float(np.trapezoid(q, sol.t)),
        skipped=len(sol.t_events[1]) > 0, final_speed=float(v[-1]), t=sol.t, h=h, v=v, g=aero,
        duration_above_3g=above,
    )


def allen_eggers_peak_g(v_entry: float, gamma_deg: float, H: float) -> float:
    """Analytic ballistic peak deceleration (no gravity, exponential atmosphere), in g."""
    return v_entry**2 * abs(math.sin(math.radians(gamma_deg))) / (2 * math.e * H) / G0


@dataclass(frozen=True)
class Corridor:
    shallow_deg: float  # overshoot: shallowest FPA that is still captured flying full lift down
    steep_deg: float  # undershoot: steepest FPA that keeps peak g under the limit flying full lift up
    width_deg: float
    g_limit: float


def entry_corridor(vehicle: EntryVehicle, planet: str, v_entry: float, g_limit: float) -> Corridor:
    """Theoretical corridor between overshoot (skip-out) and undershoot (g limit)."""

    def captured(gam):
        r = simulate_entry(vehicle, planet, v_entry, gam, bank=180.0)
        return not r.skipped

    def too_high_g(gam):
        return simulate_entry(vehicle, planet, v_entry, gam, bank=0.0).peak_g > g_limit

    lo, hi = -0.5, -20.0  # shallow ... steep
    a, b = lo, hi
    if captured(a):
        shallow = a
    else:
        for _ in range(30):
            m = 0.5 * (a + b)
            a, b = (a, m) if captured(m) else (m, b)
        shallow = b
    a, b = shallow, hi
    if not too_high_g(a):
        if not too_high_g(b):
            steep = b
        else:
            for _ in range(30):
                m = 0.5 * (a + b)
                a, b = (m, b) if not too_high_g(m) else (a, m)
            steep = a
    else:
        steep = shallow  # no corridor
    return Corridor(shallow, steep, abs(steep - shallow), g_limit)
