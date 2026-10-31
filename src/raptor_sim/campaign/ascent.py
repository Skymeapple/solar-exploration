"""Phase 1 and 2: Earth ascent to LEO and booster return to the launch site.

Booster: vertical rise, pitch kick, then zero-lift gravity turn until it has
used everything but its return reserve. Hot staging (no coast).
Ship: closed-loop guidance that steers to the target radius with zero radial
speed (a linear-acceleration terminal law, the core idea of the Space Shuttle's
powered explicit guidance) and cuts off at circular orbital energy.
Booster return: flip, boostback burn sized by shooting so the ballistic
trajectory ends at the launch site, then a closed-loop landing burn.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from scipy.optimize import brentq, minimize_scalar

from ..constants import G0
from .bodies import MU_EARTH, OMEGA_EARTH, R_EARTH, earth_atmosphere
from .flight import Body, Forces, State, downrange, orbit_apsides, rk4_step, surface_state
from .vehicle import Stack, ascent_cd

LAUNCH_LATITUDE_DEG = 25.99  # Starbase, Texas [public]
EARTH = Body(MU_EARTH, R_EARTH, OMEGA_EARTH * math.cos(math.radians(LAUNCH_LATITUDE_DEG)), earth_atmosphere)
TARGET_ALT = 300e3  # m, circular parking orbit for refilling (same as mission.py)
DT = 0.5  # s


@dataclass
class AscentResult:
    payload: float  # kg carried
    reached_orbit: bool
    ship_residual: float  # kg propellant left in the ship at orbit insertion
    perigee_km: float
    apogee_km: float
    max_q_kpa: float
    max_q_mach: float
    max_q_alt_km: float
    max_q_v_air: float
    max_booster_g: float
    max_ship_g: float
    meco_time: float
    meco_alt_km: float
    meco_speed_air: float
    meco_gamma_deg: float
    seco_time: float
    gravity_loss: float  # m/s
    drag_loss: float  # m/s
    ideal_dv: float  # m/s
    stage_state: State | None = None
    booster_mass_at_meco: float = 0.0
    trace: list | None = None


@dataclass(frozen=True)
class Dispersion:
    """Multiplicative factors applied in Monte Carlo runs (1.0 = nominal)."""

    isp: float = 1.0
    thrust: float = 1.0
    booster_dry: float = 1.0
    ship_dry: float = 1.0
    density: float = 1.0
    cd: float = 1.0
    booster_engine_out_time: float | None = None  # s after liftoff, one booster engine lost
    ship_engine_out_time: float | None = None  # s after staging, one ship sea-level engine lost


def _earth_body(density_factor: float) -> Body:
    if density_factor == 1.0:
        return EARTH

    def atm(h):
        a = earth_atmosphere(h)
        return type(a)(a.density * density_factor, a.pressure, a.sound_speed)

    return Body(EARTH.mu, EARTH.radius, EARTH.omega, atm)


def fly_ascent(
    stack: Stack,
    payload: float,
    kick_deg: float = 2.5,
    disp: Dispersion = Dispersion(),
    keep_trace: bool = False,
    target_alt: float = TARGET_ALT,
) -> AscentResult:
    eng = stack.engine.scaled(disp.isp, disp.thrust)
    body = _earth_body(disp.density)
    booster_dry = stack.booster_dry * disp.booster_dry
    ship_dry = stack.ship_dry * disp.ship_dry
    ship_full = ship_dry + stack.ship_propellant + payload
    m0 = booster_dry + stack.booster_propellant + ship_full
    s = surface_state(body, m0)
    usable_booster = stack.booster_propellant * (1 - stack.booster_reserve_fraction)
    burned_b = 0.0
    max_q = (0.0, 0.0, 0.0, 0.0)
    max_bg = max_sg = 0.0
    g_loss = d_loss = ideal = 0.0
    trace = [] if keep_trace else None
    t_kick0, t_kick1 = 8.0, 18.0
    kick = math.radians(kick_deg)

    # Booster phase
    while burned_b < usable_booster:
        n = stack.booster_engines
        if disp.booster_engine_out_time is not None and s.t >= disp.booster_engine_out_time:
            n -= 1
        p_amb = body.atmosphere(s.r - body.radius).pressure
        thr = 1.0
        if stack.q_limit_throttle > 0 and max_q[0] > 0:
            # Throttle bucket: hold dynamic pressure near the limit.
            q_now = _q(s, body)
            if q_now > 0.9 * stack.q_limit_throttle:
                thr = max(0.6, 1 - 4 * (q_now - 0.9 * stack.q_limit_throttle) / stack.q_limit_throttle)
        thrust = n * eng.thrust(p_amb) * thr
        mdot = n * eng.mdot * thr
        if s.t < t_kick0:
            pitch = math.pi / 2
        elif s.t < t_kick1:
            pitch = math.pi / 2 - kick * (s.t - t_kick0) / (t_kick1 - t_kick0)
        else:
            pitch = None
        mach = _mach(s, body)
        f = Forces(thrust, mdot, pitch, cd_area=ascent_cd(mach) * disp.cd * stack.area)
        tel = rk4_step(s, body, f, DT)
        burned_b += mdot * DT
        if tel.q > max_q[0]:
            max_q = (tel.q, tel.mach, tel.h, tel.v_air)
        max_bg = max(max_bg, tel.accel_g)
        g_loss += body.mu / s.r**2 * math.sin(tel.gamma_air) * DT
        d_loss += tel.q * f.cd_area / s.m * DT
        ideal += thrust / s.m * DT
        if trace is not None:
            trace.append((s.t, tel.h, tel.v_air, tel.q, tel.accel_g, "booster"))
        if s.r < body.radius - 1:
            return _failed(payload, max_q, max_bg)

    meco = s.copy()
    meco_tel_h = s.r - body.radius
    vax, vay = s.vx + body.omega * s.y, s.vy - body.omega * s.x
    meco_va = math.hypot(vax, vay)
    vr_meco, _ = meco.radial_tangential()
    booster_mass = booster_dry + stack.booster_propellant - burned_b
    s = State(s.x, s.y, s.vx, s.vy, ship_full, s.t)
    stage_t = s.t

    # Ship phase
    r_t = body.radius + target_alt
    v_circ = math.sqrt(body.mu / r_t)
    h_target = math.sqrt(body.mu * r_t)
    pitch = None
    seco = None
    while s.m > ship_dry + payload:
        n_sl = stack.ship_sl_engines
        if disp.ship_engine_out_time is not None and s.t - stage_t >= disp.ship_engine_out_time:
            n_sl -= 1
        p_amb = body.atmosphere(s.r - body.radius).pressure
        f_full = n_sl * eng.thrust(p_amb) + stack.ship_vac_engines * eng.rvac_thrust
        mdot_full = n_sl * eng.mdot + stack.ship_vac_engines * eng.rvac_thrust / (eng.rvac_isp * G0)
        thr = min(1.0, stack.max_axial_g * G0 * s.m / f_full)
        thr = max(thr, eng.min_throttle)
        thrust, mdot = f_full * thr, mdot_full * thr
        vr, vt = s.radial_tangential()
        r = s.r
        a_t = thrust / s.m
        ve = thrust / mdot
        dv_go = math.hypot(v_circ - vt, vr)
        tgo = max(dv_go / a_t if thr < 1.0 else s.m / mdot * (1 - math.exp(-dv_go / ve)), 1e-3)
        if tgo > 6.0 or pitch is None:
            A = 6 * (r_t - r) / tgo**2 - 4 * vr / tgo
            a_r = A + body.mu / r**2 - vt**2 / r
            pitch = math.asin(max(-0.6, min(0.95, a_r / a_t)))
        mach = _mach(s, body)
        f = Forces(thrust, mdot, pitch, cd_area=ascent_cd(mach) * disp.cd * stack.area)
        tel = rk4_step(s, body, f, DT)
        max_sg = max(max_sg, tel.accel_g)
        g_loss += body.mu / s.r**2 * math.sin(tel.gamma_air) * DT
        d_loss += tel.q * f.cd_area / s.m * DT
        ideal += thrust / s.m * DT
        if trace is not None:
            trace.append((s.t, tel.h, tel.v_air, tel.q, tel.accel_g, "ship"))
        if s.r < body.radius:
            break
        if s.x * s.vy - s.y * s.vx >= h_target:  # angular momentum of the target circular orbit
            seco = s.t
            break

    rp, ra = orbit_apsides(s, body.mu, body.radius)
    reached = seco is not None and rp > 150e3
    return AscentResult(
        payload=payload,
        reached_orbit=reached,
        ship_residual=s.m - ship_dry - payload,
        perigee_km=rp / 1e3,
        apogee_km=ra / 1e3,
        max_q_kpa=max_q[0] / 1e3,
        max_q_mach=max_q[1],
        max_q_alt_km=max_q[2] / 1e3,
        max_q_v_air=max_q[3],
        max_booster_g=max_bg,
        max_ship_g=max_sg,
        meco_time=stage_t,
        meco_alt_km=meco_tel_h / 1e3,
        meco_speed_air=meco_va,
        meco_gamma_deg=math.degrees(math.asin(max(-1, min(1, vr_meco / math.hypot(meco.vx, meco.vy))))),
        seco_time=seco or s.t,
        gravity_loss=g_loss,
        drag_loss=d_loss,
        ideal_dv=ideal,
        stage_state=State(meco.x, meco.y, meco.vx, meco.vy, booster_mass, meco.t),
        booster_mass_at_meco=booster_mass,
        trace=trace,
    )


def _q(s: State, body: Body) -> float:
    vax, vay = s.vx + body.omega * s.y, s.vy - body.omega * s.x
    return 0.5 * body.atmosphere(s.r - body.radius).density * (vax * vax + vay * vay)


def _mach(s: State, body: Body) -> float:
    vax, vay = s.vx + body.omega * s.y, s.vy - body.omega * s.x
    return math.hypot(vax, vay) / body.atmosphere(s.r - body.radius).sound_speed


def _failed(payload, max_q, max_bg) -> AscentResult:
    return AscentResult(payload, False, -1e9, 0, 0, max_q[0] / 1e3, max_q[1], max_q[2] / 1e3, max_q[3], max_bg, 0,
                        0, 0, 0, 0, 0, 0, 0, 0)


def payload_capability(
    stack: Stack, ship_reserve: float, kick_deg: float = 2.5, disp: Dispersion = Dispersion()
) -> float:
    """Largest payload (kg) that reaches orbit with ship_reserve kg of propellant left."""

    def margin(p):
        res = fly_ascent(stack, p, kick_deg, disp)
        return (res.ship_residual if res.reached_orbit else -1e6 + p) - ship_reserve

    if margin(0.0) < 0:
        return 0.0
    return brentq(margin, 0.0, 600e3, xtol=100.0)


def best_kick(stack: Stack, ship_reserve: float) -> tuple[float, float]:
    """Pitch kick (deg) that maximises payload, and that payload (kg)."""
    r = minimize_scalar(lambda k: -payload_capability(stack, ship_reserve, k), bounds=(1.0, 6.0),
                        method="bounded", options={"xatol": 0.05})
    return r.x, -r.fun


# ---------------------------------------------------------------- booster return


@dataclass
class BoosterReturn:
    boostback_s: float
    propellant_used: float  # kg, boostback + landing
    reserve: float  # kg available
    touchdown_speed: float  # m/s
    miss_distance_m: float
    max_descent_q_kpa: float
    landing_burn_s: float

    @property
    def margin_fraction(self) -> float:
        return 1 - self.propellant_used / self.reserve


def _booster_descent(stack: Stack, start: State, boostback_s: float, disp: Dispersion, flip_s: float = 15.0):
    eng = stack.engine.scaled(disp.isp, disp.thrust)
    body = _earth_body(disp.density)
    s = start.copy()
    dry = stack.booster_dry * disp.booster_dry
    used = 0.0
    max_q = 0.0
    landing_s = 0.0
    # Flip
    t_end = s.t + flip_s
    while s.t < t_end:
        rk4_step(s, body, Forces(cd_area=stack.area * 0.5), DT)
    # Boostback: thrust toward the launch site, horizontally in the rotating frame.
    t_end = s.t + boostback_s
    n = stack.booster_boostback_engines
    while s.t < t_end and s.m > dry:
        p_amb = body.atmosphere(s.r - body.radius).pressure
        thrust, mdot = n * eng.thrust(p_amb), n * eng.mdot
        pitch = math.pi - math.radians(10.0)  # backward, thrust 10 deg above local horizontal
        rk4_step(s, body, Forces(thrust, mdot, pitch, cd_area=stack.area * 0.5), DT)
        used += mdot * DT
    # Coast and landing burn: the inner 13 engines light first, then the centre 3 finish.
    n_hi, n_lo = stack.booster_boostback_engines, stack.booster_landing_engines
    lit = False
    while True:
        h = s.r - body.radius
        vax, vay = s.vx + body.omega * s.y, s.vy - body.omega * s.x
        v = math.hypot(vax, vay)
        p_amb = body.atmosphere(h).pressure
        f_eng = eng.thrust(p_amb)
        a_req = v * v / (2 * max(h - 1.0, 0.5)) + G0  # aim to stop 1 m above the pad
        if not lit and h < 20e3 and a_req > 0.85 * n_hi * f_eng / s.m:
            lit = True
        dt = DT if h > 3e3 else (0.1 if h > 200 else 0.02)
        if lit:
            n = n_hi if a_req * s.m > n_lo * f_eng else n_lo
            thr = max(eng.min_throttle, min(1.0, a_req * s.m / (n * f_eng)))
            f = Forces(n * f_eng * thr, n * eng.mdot * thr, None, retro=True,
                       cd_area=stack.booster_cd_descent * disp.cd * stack.area)
            used += f.mdot * dt
            landing_s += dt
        else:
            f = Forces(cd_area=stack.booster_cd_descent * disp.cd * stack.area)
        tel = rk4_step(s, body, f, dt)
        max_q = max(max_q, tel.q)
        if s.r - body.radius <= 0 or (lit and v < 1.0) or s.m <= dry:
            vax, vay = s.vx + body.omega * s.y, s.vy - body.omega * s.x
            return s, used, math.hypot(vax, vay), max_q, landing_s


def booster_return(stack: Stack, ascent: AscentResult, disp: Dispersion = Dispersion()) -> BoosterReturn:
    start = ascent.stage_state
    reserve = start.m - stack.booster_dry * disp.booster_dry

    def miss(tb):
        s, *_ = _booster_descent(stack, start, tb, disp)
        return downrange(s, EARTH)

    # Scan for the first sign change of the miss distance, then refine.
    lo, m_lo = 0.0, miss(0.0)
    tb = None
    for hi in [5.0 * k for k in range(1, 41)]:
        m_hi = miss(hi)
        if m_lo * m_hi <= 0:
            tb = brentq(miss, lo, hi, xtol=0.05)
            break
        lo, m_lo = hi, m_hi
    if tb is None:  # cannot reach the site: report the best it can do
        tb = min((5.0 * k for k in range(0, 41)), key=lambda t: abs(miss(t)))
    s, used, v_td, max_q, landing_s = _booster_descent(stack, start, tb, disp)
    return BoosterReturn(tb, used, reserve, v_td, abs(downrange(s, EARTH)), max_q / 1e3, landing_s)


# ---------------------------------------------------------------- control authority


@dataclass
class TrimCheck:
    wind_ms: float
    alpha_deg: float
    gimbal_required_deg: float
    gimbal_limit_deg: float

    @property
    def passed(self) -> bool:
        return self.gimbal_required_deg <= self.gimbal_limit_deg


def max_q_trim(stack: Stack, ascent: AscentResult, wind_ms: float = 60.0, cn_alpha: float = 2.5,
               cp_ahead_of_cg_m: float = 20.0, gimbal_limit_deg: float = 15.0) -> TrimCheck:
    """Static pitch-plane trim at max-Q in a crosswind (aerodynamic stability / control check).

    The stack is aerodynamically unstable (centre of pressure ahead of the centre of
    mass), so the engines must gimbal to hold the nose into the wind.
    wind 60 m/s is about the 95th percentile upper-level wind (estimate), CN_alpha 2.5/rad
    and a 20 m CP-CG offset are estimates for a 9 m x 124 m body with flaps.
    The gimbal lever arm is taken as half the stack length.
    """
    alpha = math.atan2(wind_ms, ascent.max_q_v_air)
    normal = ascent.max_q_kpa * 1e3 * stack.area * cn_alpha * alpha
    moment = normal * cp_ahead_of_cg_m
    n_gimbal = 13  # inner engines gimbal [public]
    thrust_gimbal = n_gimbal * stack.engine.thrust(earth_atmosphere(ascent.max_q_alt_km * 1e3).pressure)
    lever = stack.stack_length / 2
    s = moment / (thrust_gimbal * lever)
    req = math.degrees(math.asin(min(1.0, s)))
    return TrimCheck(wind_ms, math.degrees(alpha), req, gimbal_limit_deg)
