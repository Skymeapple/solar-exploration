"""Orbiting-sample rendezvous and capture.

Three parts:

1. Orbit matching: the orbiter waits in the target orbit; the delta-v to match a
   dispersed sample-container orbit (from the ascent Monte Carlo) uses the
   near-circular first-order expressions dv = v/2 |da|/a + v/2 |de| + v |di|.
2. Terminal approach: a chain of two-impulse Clohessy-Wiltshire (CW) transfers
   along V-bar (10 km -> 1 km -> 100 m -> 10 m -> capture), with navigation and
   burn-execution errors, run as a Monte Carlo.
3. Verification: the CW-designed transfer is flown in the full nonlinear two-body
   problem (both spacecraft propagated by the universal-Kepler propagator) and
   the arrival miss is compared with the CW prediction (gate SR-4).

Frames: LVLH with x radial (up), y along track, z orbit normal.
Error levels and the capture envelope are [estimate]s; the MSR plan to capture
a passive container with the Earth Return Orbiter's capture system is [cited].
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from .bodies import MARS, Body
from .transfer import propagate


def cw_stm(n: float, t: float) -> np.ndarray:
    """6x6 Clohessy-Wiltshire state-transition matrix (x radial, y along-track, z normal)."""
    s, c = math.sin(n * t), math.cos(n * t)
    return np.array(
        [
            [4 - 3 * c, 0, 0, s / n, 2 * (1 - c) / n, 0],
            [6 * (s - n * t), 1, 0, -2 * (1 - c) / n, (4 * s - 3 * n * t) / n, 0],
            [0, 0, c, 0, 0, s / n],
            [3 * n * s, 0, 0, c, 2 * s, 0],
            [-6 * n * (1 - c), 0, 0, -2 * s, 4 * c - 3, 0],
            [0, 0, -n * s, 0, 0, c],
        ]
    )


def cw_two_impulse(n: float, r0: np.ndarray, v0: np.ndarray, rf: np.ndarray, t: float):
    """Velocity needed at the start (v0+) and the burn to null at the end, for a CW hop."""
    phi = cw_stm(n, t)
    prr, prv = phi[:3, :3], phi[:3, 3:]
    pvr, pvv = phi[3:, :3], phi[3:, 3:]
    v0_plus = np.linalg.solve(prv, rf - prr @ r0)
    vf_minus = pvr @ r0 + pvv @ v0_plus
    return v0_plus, vf_minus


# --- Orbit matching ---------------------------------------------------------------


def matching_dv(body: Body, a_ref: float, a: float, e: float, di_rad: float = 0.0) -> float:
    """Delta-v to move from a circular orbit of radius a_ref to (a, e, di), first-order."""
    v = math.sqrt(body.mu / a_ref)
    return v / 2 * abs(a - a_ref) / a_ref + v / 2 * abs(e) + v * abs(di_rad)


# --- Terminal approach Monte Carlo --------------------------------------------------


@dataclass(frozen=True)
class ApproachPlan:
    waypoints_m: tuple[float, ...] = (-10_000.0, -1_000.0, -100.0, -10.0, 0.0)  # along-track (V-bar)
    hop_fraction_of_orbit: tuple[float, ...] = (0.45, 0.3, 0.15)  # hop durations [estimate]; not 0.5 (cross-track singular)
    nav_pos_frac: float = 0.005  # 1-sigma relative position error, fraction of range [estimate]
    nav_vel_floor: float = 0.002  # m/s 1-sigma velocity knowledge floor [estimate]
    exec_mag_frac: float = 0.02  # 1-sigma burn magnitude error [estimate]
    exec_dir_deg: float = 1.0  # 1-sigma burn pointing error [estimate]
    capture_radius: float = 0.25  # m, lateral capture envelope around the axis [estimate]
    capture_speed_max: float = 0.10  # m/s closing speed limit for the capture lid [estimate]
    final_closing_speed: float = 0.03  # m/s planned terminal closing speed [estimate]
    correction_interval: float = 20.0  # s between closing-phase corrections [estimate]


@dataclass(frozen=True)
class ApproachResult:
    success: np.ndarray
    dv: np.ndarray
    miss: np.ndarray
    closing_speed: np.ndarray

    @property
    def p_success(self) -> float:
        return float(self.success.mean())

    def summary(self) -> dict:
        return {
            "runs": int(self.success.size),
            "p_capture": self.p_success,
            "dv_mean_m_s": float(self.dv.mean()),
            "dv_p99_m_s": float(np.percentile(self.dv, 99)),
            "final_miss_p99_m": float(np.percentile(self.miss, 99)),
        }


def _perturb_burn(dv: np.ndarray, plan: ApproachPlan, rng) -> np.ndarray:
    mag = np.linalg.norm(dv)
    if mag == 0:
        return dv
    out = dv * (1 + plan.exec_mag_frac * rng.standard_normal())
    # small rotation about a random axis perpendicular to the burn
    axis = np.cross(dv, rng.standard_normal(3))
    axis /= np.linalg.norm(axis)
    ang = math.radians(plan.exec_dir_deg) * rng.standard_normal()
    return out * math.cos(ang) + np.cross(axis, out) * math.sin(ang)


def approach_monte_carlo(
    body: Body = MARS, altitude: float = 380e3, plan: ApproachPlan | None = None, n: int = 2000, seed: int = 2
) -> ApproachResult:
    """Fly the V-bar hop chain with errors. The last leg is a V-bar closing in
    forced motion at final_closing_speed, ending inside the capture envelope."""
    plan = plan or ApproachPlan()
    rng = np.random.default_rng(seed)
    a = body.radius + altitude
    nmo = math.sqrt(body.mu / a**3)
    period = 2 * math.pi / nmo
    succ, dvs, misses, speeds = [], [], [], []
    for _ in range(n):
        r = np.array([0.0, plan.waypoints_m[0], 0.0]) + rng.standard_normal(3) * abs(plan.waypoints_m[0]) * plan.nav_pos_frac
        v = rng.standard_normal(3) * plan.nav_vel_floor
        dv_tot = 0.0
        for k, frac in enumerate(plan.hop_fraction_of_orbit):
            target = np.array([0.0, plan.waypoints_m[k + 1], 0.0])
            T = frac * period
            rng_est = np.linalg.norm(r)
            r_est = r + rng.standard_normal(3) * max(rng_est * plan.nav_pos_frac, 0.05)
            v_est = v + rng.standard_normal(3) * plan.nav_vel_floor
            v0p, _ = cw_two_impulse(nmo, r_est, v_est, target, T)
            burn = _perturb_burn(v0p - v_est, plan, rng)
            v = v + burn
            dv_tot += np.linalg.norm(burn)
            state = cw_stm(nmo, T) @ np.concatenate([r, v])
            r, v = state[:3], state[3:]
            # Null relative velocity at the waypoint (station keeping hold).
            v_est = v + rng.standard_normal(3) * plan.nav_vel_floor
            stop = _perturb_burn(-v_est, plan, rng)
            v = v + stop
            dv_tot += np.linalg.norm(stop)
        # Final closing (forced motion): re-aim at the container every
        # correction_interval seconds from a fresh relative-navigation fix.
        dist = np.linalg.norm(r)
        while dist > plan.final_closing_speed * plan.correction_interval:
            r_est = r + rng.standard_normal(3) * max(dist * plan.nav_pos_frac, 0.01)
            v_est = v + rng.standard_normal(3) * plan.nav_vel_floor * 0.2
            u = -r_est / np.linalg.norm(r_est)
            burn = _perturb_burn(u * plan.final_closing_speed - v_est, plan, rng)
            v = v + burn
            dv_tot += np.linalg.norm(burn)
            state = cw_stm(nmo, plan.correction_interval) @ np.concatenate([r, v])
            r, v = state[:3], state[3:]
            dist = np.linalg.norm(r)
        T = dist / max(np.linalg.norm(v), 1e-6)
        state = cw_stm(nmo, T) @ np.concatenate([r, v])
        rf, vf = state[:3], state[3:]
        # Miss is the lateral offset from the capture axis (along-track line through the target).
        lateral = math.hypot(rf[0], rf[2])
        speed = float(np.linalg.norm(vf))
        ok = lateral <= plan.capture_radius and speed <= plan.capture_speed_max
        succ.append(ok)
        dvs.append(dv_tot)
        misses.append(lateral)
        speeds.append(speed)
    return ApproachResult(np.array(succ), np.array(dvs), np.array(misses), np.array(speeds))


# --- Verification: CW vs nonlinear two-body -----------------------------------------


def lvlh_basis(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    xh = r / np.linalg.norm(r)
    zh = np.cross(r, v)
    zh /= np.linalg.norm(zh)
    yh = np.cross(zh, xh)
    return np.vstack([xh, yh, zh])


def cw_vs_nonlinear(body: Body = MARS, altitude: float = 380e3, start_m: float = -10_000.0, frac: float = 0.45):
    """Design a CW hop from start_m on V-bar to the target, then fly it nonlinearly.

    The CW coordinates are read as curvilinear (y is arc length along the target
    orbit, x is the change in radius), which is the standard way to avoid the
    rectilinear start-point error. Returns (miss_m, hop_range_m)."""
    a = body.radius + altitude
    n = math.sqrt(body.mu / a**3)
    T = frac * 2 * math.pi / n
    r_rel = np.array([0.0, start_m, 0.0])
    v0p, _ = cw_two_impulse(n, r_rel, np.zeros(3), np.zeros(3), T)
    # Chief on a circular equatorial orbit starting at theta = 0.
    r_c = np.array([a, 0.0, 0.0])
    v_c = np.array([0.0, a * n, 0.0])
    # Deputy from curvilinear relative state (x, y, z, xdot, ydot, zdot).
    x, y, z = r_rel
    xd, yd, zd = v0p
    th = y / a
    rad = a + x
    er = np.array([math.cos(th), math.sin(th), 0.0])
    et = np.array([-math.sin(th), math.cos(th), 0.0])
    ez = np.array([0.0, 0.0, 1.0])
    r_d = rad * er + z * ez
    v_d = xd * er + rad * (n + yd / a) * et + zd * ez
    rc_f, _ = propagate(r_c, v_c, T, body.mu)
    rd_f, _ = propagate(r_d, v_d, T, body.mu)
    # Arrival error in curvilinear terms: radius difference, arc offset, normal offset.
    th_c = math.atan2(rc_f[1], rc_f[0])
    th_d = math.atan2(rd_f[1], rd_f[0])
    dth = (th_d - th_c + math.pi) % (2 * math.pi) - math.pi
    err = np.array([np.linalg.norm(rd_f[:2]) - np.linalg.norm(rc_f[:2]), a * dth, rd_f[2] - rc_f[2]])
    return float(np.linalg.norm(err)), abs(start_m)
