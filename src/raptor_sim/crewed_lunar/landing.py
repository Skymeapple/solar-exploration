"""Powered descent and ascent simulation for lunar landers (planar, point mass).

The Moon is a sphere with central gravity; the lander moves in the orbit
plane. State is (r, theta, vr, vt, m) in an inertial frame; lunar rotation
(4.6 m/s at the equator, near zero at the poles) is ignored.

Descent, Apollo-style:
  1. Braking: from the perilune of the 100 x 15 km descent orbit, constant
     thrust with linear tangent steering (thrust angle above retrograde,
     tan(phi) = tan0 + k t), solved so horizontal speed reaches zero exactly at
     the gate altitude and descent rate. Constant full thrust with linear
     tangent steering is the fuel-optimal form in a flat gravity field.
  2. Terminal: vertical descent from the gate at a fixed rate plus a hover
     allowance for landing site redesignation. If the smallest thrust the
     terminal engines can give exceeds the lander's lunar weight, it cannot
     hover and the result says so.

Ascent: vertical rise, then linear tangent steering (the optimal steering law
in a flat gravity field) solved so that engine cutoff puts the lander at the
perilune of a 15 x 100 km orbit, then a circularization burn at apolune.

The point of the simulation is the real delta-v: the ideal (impulsive) value
is the 1.69 km/s orbital speed; gravity losses come on top and depend on
thrust-to-weight. Those integrated values replace the placeholders in the
shared delta-v table.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import fsolve

from ..constants import G0
from .legs import G_MOON, MU_MOON, R_MOON, circular_speed, perilune_speed


@dataclass(frozen=True)
class Lander:
    """A lander at the start of powered descent (or at liftoff, for ascent)."""

    name: str
    mass: float  # kg at powered descent start / liftoff
    thrust_max: float  # N, main engines used for braking or ascent
    isp: float  # s, main engines in vacuum
    throttle_min: float  # fraction of thrust_max
    # Terminal-phase engines (landing thrusters). None means use the main engines.
    terminal_thrust_max: float | None = None
    terminal_isp: float | None = None
    terminal_throttle_min: float | None = None


@dataclass(frozen=True)
class DescentProfile:
    perilune_alt: float = 15.24e3  # m, cited NASA descent orbit
    apolune_alt: float = 100e3  # m
    gate_alt: float = 150.0  # m, start of the vertical terminal phase (estimated)
    gate_speed: float = 3.0  # m/s descent rate at the gate, horizontal speed zero (estimated)
    terminal_rate: float = 1.5  # m/s vertical descent rate (estimated)
    hover_time: float = 30.0  # s, landing site redesignation allowance (estimated)


@dataclass(frozen=True)
class DescentResult:
    lander: str
    mode: str  # "full thrust" or "throttled"
    perilune_alt: float
    throttle: float
    braking_dv: float
    braking_time: float
    braking_range_km: float
    terminal_dv: float
    terminal_time: float
    total_dv: float
    ideal_dv: float  # orbital speed at the braking start
    gravity_loss: float
    propellant: float
    landed_mass: float
    hover_capable: bool
    terminal_twr_min: float  # smallest terminal thrust / lunar weight at touchdown
    trajectory: dict  # time, altitude, downrange, speed, mass arrays


@dataclass(frozen=True)
class AscentResult:
    lander: str
    dv_to_insertion: float
    circularization_dv: float
    total_dv: float
    ideal_dv: float
    gravity_loss: float
    burn_time: float
    propellant: float
    burnout_mass: float
    pitch0_deg: float
    pitch_rate: float
    trajectory: dict


def _rhs(thrust_fn, isp):
    ve = isp * G0

    def f(t, y):
        r, th, vr, vt, m = y
        tr, tt = thrust_fn(t, y)
        tmag = math.hypot(tr, tt)
        return [
            vr,
            vt / r,
            -MU_MOON / r**2 + vt**2 / r + tr / m,
            -vr * vt / r + tt / m,
            -tmag / ve,
        ]

    return f


def _braking_run(lander: Lander, p: "DescentProfile", throttle: float, params, max_step=2.0):
    """Linear tangent braking: thrust angle above retrograde-horizontal, tan(phi) = tan0 + k t."""
    tan0, k = params
    r0 = R_MOON + p.perilune_alt
    r_a = R_MOON + p.apolune_alt
    a = 0.5 * (r0 + r_a)
    v0 = math.sqrt(MU_MOON * (2 / r0 - 1 / a))
    thrust = throttle * lander.thrust_max

    def tfn(t, y):
        phi = math.atan(tan0 + k * t)
        return (thrust * math.sin(phi), -thrust * math.cos(phi))

    def ev_stop(t, y):  # horizontal speed nulled
        return y[3]

    def ev_ground(t, y):
        return y[0] - R_MOON

    ev_stop.terminal = True
    ev_stop.direction = -1
    ev_ground.terminal = True
    ev_ground.direction = -1
    sol = solve_ivp(
        _rhs(tfn, lander.isp), (0, 5_000), [r0, 0.0, 0.0, v0, lander.mass],
        events=(ev_stop, ev_ground), rtol=1e-9, atol=1e-6, max_step=max_step,
    )
    return sol, v0


def simulate_descent(lander: Lander, profile: DescentProfile | None = None, throttle: float = 1.0) -> DescentResult:
    """Braking phase by integration with steering solved to reach the gate, then the terminal phase."""
    p = profile or DescentProfile()
    if not lander.throttle_min <= throttle <= 1.0:
        raise ValueError(f"{lander.name}: throttle {throttle:.2f} outside {lander.throttle_min:.2f} to 1")

    def resid(params):
        sol, _ = _braking_run(lander, p, throttle, params)
        return [((sol.y[0, -1] - R_MOON) - p.gate_alt) / 1e3, (sol.y[2, -1] + p.gate_speed) / 10.0]

    # Initial guess: burn time from the ideal delta-v; start near retrograde, pitch up toward the end.
    v0 = perilune_speed(p.apolune_alt, p.perilune_alt)
    ve = lander.isp * G0
    tb = lander.mass * (1 - math.exp(-v0 / ve)) * ve / (throttle * lander.thrust_max)
    best = None
    for tan0 in (0.0, -0.2, 0.2, -0.5, 0.5):
        for kk in (0.5, 1.0, 2.0):
            x, info, ier, msg = fsolve(resid, [tan0, kk / tb], full_output=True, xtol=1e-9)
            err = max(abs(e) for e in resid(x))
            if best is None or err < best[1]:
                best = (x, err)
            if err < 1e-3:
                break
        if best[1] < 1e-3:
            break
    if best[1] > 1e-2:
        raise ValueError(f"{lander.name}: descent targeting did not converge (residual {best[1]:.3g})")
    sol, v0 = _braking_run(lander, p, throttle, best[0], max_step=1.0)
    if len(sol.t_events[1]) or len(sol.t_events[0]) == 0:
        raise ValueError(f"{lander.name}: hits the surface before braking completes")
    mode = "throttled" if throttle < 1.0 else "full thrust"
    start_alt = p.perilune_alt
    m_gate = sol.y[4, -1]
    braking_dv = lander.isp * G0 * math.log(lander.mass / m_gate)

    # Terminal phase: vertical, thrust about equal to weight for the descent and hover.
    t_term = max(sol.y[0, -1] - R_MOON, 0.0) / p.terminal_rate + p.hover_time
    t_isp = lander.terminal_isp or lander.isp
    terminal_dv = G_MOON * t_term + p.gate_speed  # weight held for t_term, plus killing gate speed
    m_land = m_gate / math.exp(terminal_dv / (t_isp * G0))
    t_max = lander.terminal_thrust_max or lander.thrust_max
    t_min_frac = lander.terminal_throttle_min if lander.terminal_throttle_min is not None else lander.throttle_min
    twr_min = t_min_frac * t_max / (m_land * G_MOON)

    alt = sol.y[0] - R_MOON
    traj = {
        "t": sol.t.tolist(),
        "alt_m": alt.tolist(),
        "downrange_km": (sol.y[1] * R_MOON / 1e3).tolist(),
        "speed_m_s": np.hypot(sol.y[2], sol.y[3]).tolist(),
        "mass_kg": sol.y[4].tolist(),
    }
    total = braking_dv + terminal_dv
    return DescentResult(
        lander=lander.name, mode=mode, perilune_alt=start_alt, throttle=throttle,
        braking_dv=braking_dv, braking_time=sol.t[-1], braking_range_km=sol.y[1, -1] * R_MOON / 1e3,
        terminal_dv=terminal_dv, terminal_time=t_term, total_dv=total, ideal_dv=v0,
        gravity_loss=total - v0, propellant=lander.mass - m_land, landed_mass=m_land,
        hover_capable=twr_min < 1.0, terminal_twr_min=twr_min, trajectory=traj,
    )


def simulate_ascent(
    lander: Lander,
    throttle: float = 1.0,
    perilune_alt: float = 15.24e3,
    apolune_alt: float = 100e3,
    vertical_rise: float = 8.0,  # s, clear the surface before pitching (estimated)
) -> AscentResult:
    """Surface to a perilune x apolune orbit with linear tangent steering, then circularize."""
    thrust = throttle * lander.thrust_max
    r_p = R_MOON + perilune_alt
    r_a = R_MOON + apolune_alt
    a_t = 0.5 * (r_p + r_a)
    vt_target = math.sqrt(MU_MOON * (2 / r_p - 1 / a_t))

    def run(params, dense=False):
        tan0, k = params

        def tfn(t, y):
            if t < vertical_rise:
                return (thrust, 0.0)
            phi = math.atan(tan0 - k * (t - vertical_rise))
            return (thrust * math.sin(phi), thrust * math.cos(phi))

        def ev_cut(t, y):  # horizontal speed reaches insertion speed
            return y[3] - vt_target

        def ev_crash(t, y):
            return y[0] - R_MOON + 1.0

        ev_cut.terminal = True
        ev_cut.direction = 1
        ev_crash.terminal = True
        ev_crash.direction = -1
        return solve_ivp(
            _rhs(tfn, lander.isp), (0, 3_000), [R_MOON, 0.0, 0.0, 0.0, lander.mass],
            events=(ev_cut, ev_crash), rtol=1e-9, atol=1e-6, max_step=1.0 if dense else 2.0,
        )

    def resid(params):
        s = run(params)
        return [(s.y[0, -1] - r_p) / 1e3, s.y[2, -1] / 10.0]

    # Initial guesses from the burn time of an ideal ascent; several starts for robustness.
    ve = lander.isp * G0
    tb = lander.mass * (1 - math.exp(-1.85e3 / ve)) * ve / thrust
    best = None
    for deg0 in (30.0, 45.0, 60.0, 20.0, 75.0):
        for frac in (1.0, 1.5, 0.7, 2.0):
            t0 = math.tan(math.radians(deg0))
            x, info, ier, msg = fsolve(resid, [t0, frac * t0 / tb], full_output=True, xtol=1e-9)
            err = max(abs(e) for e in resid(x))
            if best is None or err < best[1]:
                best = (x, err)
            if err < 1e-3:
                break
        if best[1] < 1e-3:
            break
    if best[1] > 1e-2:
        raise ValueError(f"{lander.name}: ascent targeting did not converge (residual {best[1]:.3g})")
    sol_p = best[0]
    s = run(sol_p, dense=True)
    m_bo = s.y[4, -1]
    dv_ins = lander.isp * G0 * math.log(lander.mass / m_bo)
    v_apo = math.sqrt(MU_MOON * (2 / r_a - 1 / a_t))
    circ = circular_speed(MU_MOON, r_a) - v_apo
    m_final = m_bo / math.exp(circ / (lander.isp * G0))
    ideal = vt_target  # impulsive: from rest to insertion speed
    traj = {
        "t": s.t.tolist(),
        "alt_m": (s.y[0] - R_MOON).tolist(),
        "downrange_km": (s.y[1] * R_MOON / 1e3).tolist(),
        "speed_m_s": np.hypot(s.y[2], s.y[3]).tolist(),
        "mass_kg": s.y[4].tolist(),
    }
    return AscentResult(
        lander=lander.name, dv_to_insertion=dv_ins, circularization_dv=circ, total_dv=dv_ins + circ,
        ideal_dv=ideal, gravity_loss=dv_ins - ideal, burn_time=s.t[-1], propellant=lander.mass - m_final,
        burnout_mass=m_final, pitch0_deg=math.degrees(math.atan(sol_p[0])), pitch_rate=sol_p[1],
        trajectory=traj,
    )


def perilune_ideal_dv(profile: DescentProfile | None = None) -> float:
    p = profile or DescentProfile()
    return perilune_speed(p.apolune_alt, p.perilune_alt)
