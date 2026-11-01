"""Planar point-mass flight integrator shared by every powered and atmospheric phase.

Fidelity level L1 (procedure document): 3 degrees of freedom in the orbit plane
around a spherical, rotating planet with a rotating atmosphere, fixed-step RK4.
Out-of-plane motion, winds and attitude dynamics are left out; wind and
attitude enter only through the separate trim check in ascent.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable


@dataclass
class State:
    x: float
    y: float
    vx: float
    vy: float
    m: float
    t: float = 0.0

    @property
    def r(self) -> float:
        return math.hypot(self.x, self.y)

    def radial_tangential(self) -> tuple[float, float]:
        r = self.r
        ex, ey = self.x / r, self.y / r
        return self.vx * ex + self.vy * ey, -self.vx * ey + self.vy * ex

    def copy(self) -> "State":
        return State(self.x, self.y, self.vx, self.vy, self.m, self.t)


@dataclass(frozen=True)
class Body:
    mu: float
    radius: float
    omega: float  # effective rotation rate in the flight plane (rad/s), includes cos(latitude)
    atmosphere: Callable  # h -> AtmState


@dataclass
class Forces:
    """What a controller returns each step."""

    thrust: float = 0.0  # N
    mdot: float = 0.0  # kg/s
    pitch: float | None = None  # rad above local horizontal; None = along air-relative velocity
    retro: bool = False  # with pitch None: thrust against the air-relative velocity
    cd_area: float = 0.0  # Cd * A, m^2
    lift_over_drag: float = 0.0  # lift as a fraction of drag
    lift_up_fraction: float = 1.0  # cos(bank): share of lift in the vertical plane


@dataclass
class Telemetry:
    q: float
    mach: float
    accel_g: float  # non-gravitational acceleration magnitude in Earth g
    v_air: float
    h: float
    gamma_air: float


def air_velocity(s: State, body: Body) -> tuple[float, float]:
    return s.vx + body.omega * s.y, s.vy - body.omega * s.x


def derivatives(s: State, body: Body, f: Forces) -> tuple[tuple[float, ...], Telemetry]:
    r = s.r
    ex, ey = s.x / r, s.y / r
    hx, hy = -ey, ex  # local horizontal, prograde
    h = r - body.radius
    atm = body.atmosphere(h)
    vax, vay = air_velocity(s, body)
    va = math.hypot(vax, vay)
    q = 0.5 * atm.density * va * va
    ax = -body.mu * s.x / r**3
    ay = -body.mu * s.y / r**3
    ngx = ngy = 0.0
    if va > 1e-6:
        ux, uy = vax / va, vay / va
    else:
        ux, uy = ex, ey
    if f.cd_area > 0 and va > 1e-6:
        drag = q * f.cd_area
        ngx -= drag * ux / s.m
        ngy -= drag * uy / s.m
        if f.lift_over_drag:
            # Lift is perpendicular to the air velocity, pointing away from the planet when lift-up.
            nx, ny = -uy, ux
            if nx * ex + ny * ey < 0:
                nx, ny = -nx, -ny
            lift = drag * f.lift_over_drag * f.lift_up_fraction
            ngx += lift * nx / s.m
            ngy += lift * ny / s.m
    if f.thrust > 0:
        if f.pitch is None:
            dx, dy = (-ux, -uy) if f.retro else (ux, uy)
        else:
            c, sn = math.cos(f.pitch), math.sin(f.pitch)
            dx, dy = c * hx + sn * ex, c * hy + sn * ey
        ngx += f.thrust * dx / s.m
        ngy += f.thrust * dy / s.m
    gamma_air = math.asin(max(-1.0, min(1.0, (vax * ex + vay * ey) / va))) if va > 1e-6 else math.pi / 2
    tel = Telemetry(q, va / atm.sound_speed, math.hypot(ngx, ngy) / 9.80665, va, h, gamma_air)
    return (s.vx, s.vy, ax + ngx, ay + ngy, -f.mdot), tel


def rk4_step(s: State, body: Body, f: Forces, dt: float) -> Telemetry:
    """Advance s in place by dt with the controls f held constant. Returns telemetry at the start."""
    k1, tel = derivatives(s, body, f)

    def shifted(k, a):
        return State(s.x + a * k[0], s.y + a * k[1], s.vx + a * k[2], s.vy + a * k[3], s.m + a * k[4], s.t)

    k2, _ = derivatives(shifted(k1, dt / 2), body, f)
    k3, _ = derivatives(shifted(k2, dt / 2), body, f)
    k4, _ = derivatives(shifted(k3, dt), body, f)
    s.x += dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0])
    s.y += dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])
    s.vx += dt / 6 * (k1[2] + 2 * k2[2] + 2 * k3[2] + k4[2])
    s.vy += dt / 6 * (k1[3] + 2 * k2[3] + 2 * k3[3] + k4[3])
    s.m += dt / 6 * (k1[4] + 2 * k2[4] + 2 * k3[4] + k4[4])
    s.t += dt
    return tel


def orbit_apsides(s: State, mu: float, radius: float) -> tuple[float, float]:
    """Perigee and apogee altitude (m) of the osculating orbit."""
    r = s.r
    v2 = s.vx**2 + s.vy**2
    energy = v2 / 2 - mu / r
    hmom = s.x * s.vy - s.y * s.vx
    if energy >= 0:
        a = math.inf
    else:
        a = -mu / (2 * energy)
    e = math.sqrt(max(0.0, 1 + 2 * energy * hmom**2 / mu**2))
    rp = hmom**2 / (mu * (1 + e))
    ra = a * (1 + e) if energy < 0 else math.inf
    return rp - radius, ra - radius


def surface_state(body: Body, mass: float) -> State:
    """At rest on the surface at angle 0."""
    return State(body.radius, 0.0, 0.0, body.omega * body.radius, mass)


def downrange(s: State, body: Body, site_angle0: float = 0.0) -> float:
    """Surface distance (m) from a launch site that rotates with the planet; positive = east."""
    site = site_angle0 + body.omega * s.t
    ang = math.atan2(s.y, s.x) - site
    ang = (ang + math.pi) % (2 * math.pi) - math.pi
    return ang * body.radius
