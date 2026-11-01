"""Phases 6 and 10: atmospheric entry at Mars (with propulsive landing) and at Earth.

Planar 3-DOF entry of a belly-first Starship-class ship, lift modulated by bank
angle. Guidance: fly lift-up until drag builds, then command cos(bank) to hold a
reference drag acceleration while damping climb rate (a simplified version of
Apollo / Mars Science Laboratory drag-tracking entry guidance).
Heating: Sutton-Graves stagnation-point convective correlation (public,
Sutton & Graves 1971, NASA TR R-376). Radiative heating is not modelled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..constants import G0
from .bodies import (G_MARS, MU_EARTH, MU_MARS, OMEGA_EARTH, OMEGA_MARS, R_EARTH, R_MARS, earth_atmosphere,
                     mars_atmosphere)
from .flight import Body, Forces, State, rk4_step
from .vehicle import EngineData

SUTTON_GRAVES_K = {"mars": 1.9027e-4, "earth": 1.7415e-4}  # SI (W/m^2 with rho kg/m^3, rn m, v m/s)
ENTRY_INTERFACE = {"mars": 125e3, "earth": 120e3}


@dataclass(frozen=True)
class EntryVehicle:
    mass: float  # kg at entry interface
    area: float = 9.0 * 50.0  # m^2 planform, belly first [est from public 9 m x ~50 m ship]
    cd: float = 1.2  # [est] at 60-70 deg angle of attack
    lift_over_drag: float = 0.25  # [est]
    nose_radius: float = 4.5  # m, windward body radius [est]

    @property
    def ballistic_coefficient(self) -> float:
        return self.mass / (self.cd * self.area)


@dataclass(frozen=True)
class EntryGuidance:
    drag_ref_g: float = 2.0  # reference drag acceleration (Earth g)
    k_drag: float = 0.5
    k_hdot: float = 1 / 40.0
    v_full_lift: float = 2_500.0  # m/s; below this fly full lift-up to stay high and bleed speed
    v_srp: float = 1_000.0  # m/s; light the engines (supersonic retropropulsion) below this speed
    initial_cos_bank: float = 1.0  # lift direction before drag builds (1 = lift up, -1 = lift down)


@dataclass
class EntryResult:
    planet: str
    v_entry: float
    fpa_deg: float
    peak_g: float
    peak_heat_w_cm2: float
    heat_load_mj_m2: float
    skipped: bool
    landing_propellant: float  # kg used in the landing burn (Mars only)
    touchdown_speed: float
    crashed: bool
    v_at_ignition: float
    alt_at_ignition_km: float
    trace: list | None = None
    passes: int = 0  # atmospheric passes after the first (aerocapture then final entry)


def entry_speed(vinf: float, planet: str) -> float:
    mu, R = (MU_MARS, R_MARS) if planet == "mars" else (MU_EARTH, R_EARTH)
    return math.sqrt(vinf**2 + 2 * mu / (R + ENTRY_INTERFACE[planet]))


def fly_entry(
    planet: str,
    vinf: float,
    fpa_deg: float,
    veh: EntryVehicle,
    guid: EntryGuidance = EntryGuidance(),
    density_factor: float = 1.0,
    ld_factor: float = 1.0,
    engine: EngineData | None = None,
    landing_engines: int = 3,
    landing_propellant: float = 0.0,
    flip_dv: float = 40.0,
    keep_trace: bool = False,
    v_entry_override: float | None = None,
) -> EntryResult:
    """Fly from entry interface to touchdown (Mars, propulsive) or to 2 km altitude (Earth hand-over)."""
    if planet == "mars":
        body = Body(MU_MARS, R_MARS, 0.0, lambda h: mars_atmosphere(h, density_factor))
        k = SUTTON_GRAVES_K["mars"]
    else:
        def atm(h):
            a = earth_atmosphere(h)
            return type(a)(a.density * density_factor, a.pressure, a.sound_speed)
        body = Body(MU_EARTH, R_EARTH, 0.0, atm)
        k = SUTTON_GRAVES_K["earth"]
    r0 = body.radius + ENTRY_INTERFACE[planet]
    v0 = v_entry_override or entry_speed(vinf, planet)
    g = math.radians(fpa_deg)
    s = State(r0, 0.0, v0 * math.sin(g), v0 * math.cos(g), veh.mass)
    ld = veh.lift_over_drag * ld_factor
    cda = veh.cd * veh.area
    peak_g = peak_q = heat = 0.0
    skipped = crashed = False
    dt = 0.5
    trace = [] if keep_trace else None
    min_h = ENTRY_INTERFACE[planet]
    cos_bank = guid.initial_cos_bank
    passes = 0
    # Aerodynamic phase
    while True:
        h = s.r - body.radius
        vr, vt = s.radial_tangential()
        v = math.hypot(vr, vt)
        rho = body.atmosphere(h).density
        drag_g = 0.5 * rho * v * v * cda / s.m / G0
        if v < guid.v_full_lift and vr < 0:
            cos_bank = 1.0
        elif drag_g > 0.5 * guid.drag_ref_g:
            # Feed-forward: the lift that holds a level glide (gravity minus centrifugal), plus
            # feedback on drag error (clipped) and on climb rate.
            lift_acc = max(ld * drag_g * G0, 1e-6)
            ff = (body.mu / s.r**2 - vt * vt / s.r) / lift_acc
            fb = max(-0.5, min(0.5, guid.k_drag * (drag_g - guid.drag_ref_g) / guid.drag_ref_g))
            cos_bank = max(-1.0, min(1.0, ff + fb - guid.k_hdot * vr))
        tel = rk4_step(s, body, Forces(cd_area=cda, lift_over_drag=ld, lift_up_fraction=cos_bank), dt)
        qdot = k * math.sqrt(rho / veh.nose_radius) * v**3
        peak_q = max(peak_q, qdot)
        heat += qdot * dt
        peak_g = max(peak_g, tel.accel_g)
        min_h = min(min_h, h)
        if trace is not None:
            trace.append((s.t, h, v, tel.accel_g, qdot / 1e4, cos_bank))
        if h > ENTRY_INTERFACE[planet] and vr > 0 and min_h < ENTRY_INTERFACE[planet] - 10e3:
            energy = v * v / 2 - body.mu / s.r
            if energy >= 0 or passes >= 5:
                skipped = True  # left on a hyperbola: the ship is lost to space
                break
            # Captured into an elliptical orbit (aerocapture / skip entry). In this planar, non-rotating
            # model the next perigee pass is the mirror image of the exit: same speed, opposite climb rate.
            a = -body.mu / (2 * energy)
            s.t += 2 * math.pi * math.sqrt(a**3 / body.mu)
            rx, ry = s.x / s.r, s.y / s.r
            s.vx -= 2 * vr * rx
            s.vy -= 2 * vr * ry
            passes += 1
            min_h = ENTRY_INTERFACE[planet]
            continue
        if s.t > 4000 and passes == 0:
            skipped = True
            break
        if planet == "earth" and h < 2e3:
            break
        if planet == "mars" and engine is not None:
            # Start the landing burn when the stopping distance at full thrust reaches the altitude.
            # Light the engines below v_srp, or earlier (below 2 km/s) if the landing law already
            # asks for more than 85% of full thrust.
            if v < guid.v_srp or (v < 2_000.0 and _landing_accel(s, body, G_MARS)[0] * s.m
                                  > 0.85 * landing_engines * engine.thrust(body.atmosphere(h).pressure)):
                break
        if h <= 0:
            crashed = True
            break
    v_ign = math.hypot(*s.radial_tangential())
    h_ign = s.r - body.radius
    used = 0.0
    v_td = v_ign
    if planet == "mars" and engine is not None and not (skipped or crashed):
        dry_at_landing = s.m - landing_propellant
        # Flip from belly-first to engines-first: modelled as a fixed delta-v cost [est].
        used += s.m * (1 - math.exp(-flip_dv / (engine.isp_vac * G0)))
        s.m -= used
        dt = 0.1
        while True:
            h = s.r - body.radius
            vr, vt = s.radial_tangential()
            v = math.hypot(vr, vt)
            f_max = landing_engines * engine.thrust(body.atmosphere(h).pressure)
            a_mag, pitch = _landing_accel(s, body, G_MARS)
            thr = max(engine.min_throttle, min(1.0, a_mag * s.m / f_max))
            if s.m <= dry_at_landing:
                f = Forces(cd_area=0.8 * 63.6)
            else:
                f = Forces(f_max * thr, landing_engines * engine.mdot * thr, None, retro=True, cd_area=0.8 * 63.6)
            m_before = s.m
            rk4_step(s, body, f, dt)
            used += m_before - s.m
            h = s.r - body.radius
            if h <= 0 or v < 0.5:
                v_td = math.hypot(*s.radial_tangential())
                crashed = h <= 0 and v_td > 3.0
                break
    return EntryResult(planet, v0, fpa_deg, peak_g, peak_q / 1e4, heat / 1e6, skipped, used, v_td, crashed,
                       v_ign, h_ign / 1e3, trace, passes)


def _landing_accel(s: State, body: Body, g: float) -> tuple[float, None]:
    """Retrograde landing law. Thrust acts against the velocity; the throttle must both stop the
    ship within the remaining path length and, through the vertical share of thrust (sin of the
    flight-path angle), stop the sink rate before the ground. Returns the larger requirement."""
    h = max(s.r - body.radius, 0.5)
    vr, vt = s.radial_tangential()
    v = max(math.hypot(vr, vt), 1e-3)
    sin_g = max(-vr / v, 0.0)
    a_path = v * v * max(sin_g, 1e-3) / (2 * h) + g
    a_sink = (vr * vr / (2 * h) + g) / max(sin_g, 0.25) if vr < 0 else 0.0
    return max(a_path, a_sink), None


def corridor(planet: str, vinf: float, veh: EntryVehicle, peak_g_limit: float, heat_limit: float,
             guid: EntryGuidance = EntryGuidance(), **kw) -> tuple[float, float] | None:
    """Range of entry flight-path angles (deg) that avoid skip-out and stay under g and heating limits."""
    ok = []
    start = -9.0 if planet == "mars" else -4.5
    for i in range(0, 81 if planet == "mars" else 41):
        fpa = start - 0.1 * i
        r = fly_entry(planet, vinf, fpa, veh, guid, **kw)
        good = (not r.skipped and not r.crashed and r.peak_g <= peak_g_limit and r.peak_heat_w_cm2 <= heat_limit
                and (r.landing_propellant <= kw.get("landing_propellant", math.inf)))
        ok.append((fpa, good))
    good = [f for f, g in ok if g]
    if not good:
        return None
    return min(good), max(good)
