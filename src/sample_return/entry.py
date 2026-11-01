"""Earth entry vehicle (EEV): ballistic entry, heating, footprint and impact.

Model (fidelity L1): planar point-mass ballistic entry over a spherical,
non-rotating Earth, U.S. Standard Atmosphere 1976 densities (log-linear table)
or a pure exponential atmosphere for the analytic check, Mach-dependent drag
coefficient, Sutton-Graves stagnation-point convective heating
(k = 1.7415e-4 SI for air). Radiative heating is not modelled; above ~12 km/s it
adds roughly 10-20 % for nose radii under 0.5 m [memory], so heat-shield margins
should carry that.

Verification (gate SR-6): peak deceleration and peak convective heat flux from
the simulation are compared with the Allen-Eggers closed-form solution for a
straight-line ballistic entry in an exponential atmosphere. The Stardust capsule
(46 kg, 12.9 km/s, the fastest Earth entry so far) is flown as a reference case.

No-parachute landing on the MSR pattern (passive EEV, crushable structure, soft
ground) is [cited]; EEV dimensions, mass and crush stroke are [estimate]s.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
from scipy.integrate import solve_ivp

from .bodies import EARTH, G0, Body

# U.S. Standard Atmosphere 1976 density, kg/m^3, every 10 km [memory]
_US76_H = np.arange(0, 130e3, 10e3)
_US76_RHO = np.array(
    [1.225, 0.4135, 0.08891, 0.01841, 3.996e-3, 1.027e-3, 3.097e-4, 8.283e-5, 1.846e-5, 3.416e-6, 5.604e-7, 9.708e-8, 2.222e-8]
)
_LN_RHO = np.log(_US76_RHO)
K_SUTTON_GRAVES_EARTH = 1.7415e-4  # kg^0.5 / m (SI), [memory]


def density_us76(h: float) -> float:
    if h >= _US76_H[-1]:
        slope = (_LN_RHO[-1] - _LN_RHO[-2]) / 10e3
        return float(math.exp(_LN_RHO[-1] + slope * (h - _US76_H[-1])))
    return float(math.exp(np.interp(max(h, 0.0), _US76_H, _LN_RHO)))


def speed_of_sound(h: float) -> float:
    # Piecewise approximation to the 1976 standard: troposphere lapse, then about 295-330 m/s.
    if h < 11e3:
        return 340.3 - 4.06e-3 * h
    return 295.1 if h < 47e3 else 329.8


@dataclass(frozen=True)
class EntryVehicle:
    name: str
    mass: float  # kg
    diameter: float  # m
    nose_radius: float  # m
    cd_hypersonic: float = 1.05  # 60 deg sphere-cone [memory]
    cd_subsonic: float = 0.75  # [estimate]
    crush_stroke: float = 0.0  # m of energy-absorbing structure below the payload
    parachute: bool = False

    @property
    def area(self) -> float:
        return math.pi * (self.diameter / 2) ** 2

    def cd(self, mach: float) -> float:
        if mach >= 2.0:
            return self.cd_hypersonic
        if mach <= 0.8:
            return self.cd_subsonic
        f = (mach - 0.8) / 1.2
        return self.cd_subsonic + f * (self.cd_hypersonic - self.cd_subsonic)

    @property
    def ballistic_coefficient(self) -> float:
        return self.mass / (self.cd_hypersonic * self.area)


# Mars Sample Return EEV-like design point [estimate]: passive, no parachute.
MSR_EEV = EntryVehicle("MSR-class EEV", mass=50.0, diameter=1.25, nose_radius=0.35, crush_stroke=0.18)
# Stardust sample return capsule: 46 kg [cited], 0.81 m diameter, 0.22 m nose radius [memory]
STARDUST = EntryVehicle("Stardust SRC", mass=45.8, diameter=0.811, nose_radius=0.2202, parachute=True)
# OSIRIS-REx SRC: 46 kg [cited], 0.81 m (Stardust heritage) [memory]
OSIRIS_REX = EntryVehicle("OSIRIS-REx SRC", mass=46.0, diameter=0.81, nose_radius=0.2202, parachute=True)
# Hayabusa2 capsule: 0.40 m diameter [cited], ~16 kg [memory]
HAYABUSA2 = EntryVehicle("Hayabusa2 capsule", mass=16.0, diameter=0.40, nose_radius=0.20, parachute=True)


@dataclass(frozen=True)
class EntryConditions:
    speed: float  # m/s inertial at interface
    gamma_deg: float  # flight-path angle, negative down
    interface_alt: float = 125e3
    body: Body = EARTH
    exponential: bool = False  # use a pure exponential atmosphere (analytic check)
    scale_height: float = 7_000.0  # m, for the exponential option [estimate, fits 50-80 km]
    density_factor: float = 1.0


@dataclass(frozen=True)
class EntryResult:
    peak_decel_g: float
    peak_heat_flux: float  # W/m^2 convective, stagnation point
    heat_load: float  # J/m^2
    alt_peak_heating: float  # m
    downrange: float  # m from interface to ground
    impact_speed: float  # m/s (terminal velocity if no parachute)
    impact_g: float  # mean deceleration over the crush stroke (0 if parachute)
    duration: float  # s
    trajectory: np.ndarray | None = None  # t, V, gamma, h, s


def simulate_entry(ev: EntryVehicle, cond: EntryConditions, keep_trajectory: bool = False) -> EntryResult:
    body = cond.body
    R, mu = body.radius, body.mu

    def rho(h):
        if cond.exponential:
            return body.rho0 * math.exp(-h / cond.scale_height) * cond.density_factor
        return density_us76(h) * cond.density_factor

    def f(t, s):
        V, g, h, x = s
        r = R + h
        grav = mu / r**2
        cd = ev.cd(V / speed_of_sound(h))
        D = 0.5 * rho(h) * V * V * cd * ev.area / ev.mass
        dV = -D - grav * math.sin(g)
        dg = (V / r - grav / V) * math.cos(g)
        return [dV, dg, V * math.sin(g), V * math.cos(g) * R / r]

    def ground(t, s):
        return s[2]

    ground.terminal = True
    ground.direction = -1
    y0 = [cond.speed, math.radians(cond.gamma_deg), cond.interface_alt, 0.0]
    sol = solve_ivp(f, (0, 3000), y0, events=ground, rtol=1e-8, atol=1e-8, max_step=0.5, dense_output=False)
    t = sol.t
    V, gam, h, x = sol.y
    r_arr = np.array([rho(hh) for hh in h])
    cd_arr = np.array([ev.cd(vv / speed_of_sound(hh)) for vv, hh in zip(V, h)])
    decel = 0.5 * r_arr * V**2 * cd_arr * ev.area / ev.mass / G0
    q = K_SUTTON_GRAVES_EARTH * np.sqrt(r_arr / ev.nose_radius) * V**3
    i_q = int(np.argmax(q))
    impact = float(V[-1])
    impact_g = impact**2 / (2 * ev.crush_stroke * G0) if (ev.crush_stroke > 0 and not ev.parachute) else 0.0
    traj = np.vstack([t, V, gam, h, x]).T if keep_trajectory else None
    return EntryResult(
        peak_decel_g=float(decel.max()),
        peak_heat_flux=float(q[i_q]),
        heat_load=float(np.trapezoid(q, t)),
        alt_peak_heating=float(h[i_q]),
        downrange=float(x[-1]),
        impact_speed=impact,
        impact_g=impact_g,
        duration=float(t[-1]),
        trajectory=traj,
    )


def allen_eggers(ev: EntryVehicle, cond: EntryConditions) -> tuple[float, float]:
    """Closed-form peak deceleration (g) and peak convective heat flux (W/m^2)."""
    H = cond.scale_height
    sg = math.sin(abs(math.radians(cond.gamma_deg)))
    beta = ev.ballistic_coefficient
    n_max = cond.speed**2 * sg / (2 * math.e * H * G0)
    q_max = K_SUTTON_GRAVES_EARTH * math.sqrt(beta * sg / (3 * H * ev.nose_radius)) * cond.speed**3 * math.exp(-0.5)
    return n_max, q_max


@dataclass(frozen=True)
class FootprintResult:
    downrange: np.ndarray
    impact_g: np.ndarray
    peak_heat: np.ndarray

    def summary(self) -> dict:
        d = self.downrange
        return {
            "runs": int(d.size),
            "downrange_3sigma_km": float(3 * d.std() / 1e3),
            "impact_g_p99": float(np.percentile(self.impact_g, 99)),
            "peak_heat_p99_W_cm2": float(np.percentile(self.peak_heat, 99) / 1e4),
        }


def footprint_monte_carlo(ev: EntryVehicle, cond: EntryConditions, n: int = 300, seed: int = 3) -> FootprintResult:
    """Dispersions (1 sigma) [estimate]: flight-path angle 0.04 deg (after the final
    trajectory correction), speed 1 m/s, mass 1 %, drag 3 %, density 8 %."""
    rng = np.random.default_rng(seed)
    dr, ig, ph = [], [], []
    for _ in range(n):
        e = replace(
            ev,
            mass=ev.mass * (1 + 0.01 * rng.standard_normal()),
            cd_hypersonic=ev.cd_hypersonic * (1 + 0.03 * rng.standard_normal()),
            cd_subsonic=ev.cd_subsonic * (1 + 0.03 * rng.standard_normal()),
        )
        c = replace(
            cond,
            gamma_deg=cond.gamma_deg + 0.04 * rng.standard_normal(),
            speed=cond.speed + rng.standard_normal(),
            density_factor=max(0.5, 1 + 0.08 * rng.standard_normal()),
        )
        r = simulate_entry(e, c)
        dr.append(r.downrange)
        ig.append(r.impact_g)
        ph.append(r.peak_heat_flux)
    return FootprintResult(np.array(dr), np.array(ig), np.array(ph))
