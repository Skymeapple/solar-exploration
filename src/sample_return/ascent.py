"""Mars ascent vehicle (MAV): 2D point-mass trajectory, design closure and Monte Carlo.

Model (fidelity L1):
  * planar flight in an inertial frame centred on Mars, eastward launch, the
    planet's rotation speed scaled by cos(latitude) and a co-rotating atmosphere;
  * exponential atmosphere, constant drag coefficient;
  * stage 1 (steered by thrust vector control): vertical rise, then a linear
    pitch program (pitch from local vertical grows at a constant rate, capped at
    horizontal) until burnout;
  * coast to near apoapsis, then stage 2 (spin stabilised, so fixed inertial
    attitude) burns horizontally, centred on apoapsis.

Design closure picks two free parameters so the orbit lands on the target:
the pitch rate (sets coast apoapsis) and the stage-2 propellant load
(sets periapsis; solid motors are offloaded at manufacture).

Vehicle data: overall size, the two solid stages and their burn times (75 s and
20 s), total mass of 350-450 kg and the 380 km target orbit are [cited]
(see references.py, MSR). The split of mass between stages, Isp and drag are
[estimate]s chosen to sit inside those public totals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from .bodies import G0, MARS, Body


@dataclass(frozen=True)
class SolidStage:
    propellant: float  # kg
    inert: float  # kg (case, nozzle, avionics share)
    isp: float  # s (vacuum; Mars ambient back-pressure is negligible)
    burn_time: float  # s

    @property
    def mdot(self) -> float:
        return self.propellant / self.burn_time

    @property
    def thrust(self) -> float:
        return self.mdot * self.isp * G0


@dataclass(frozen=True)
class MAV:
    stage1: SolidStage = field(default_factory=lambda: SolidStage(200.0, 45.0, 290.0, 75.0))
    stage2: SolidStage = field(default_factory=lambda: SolidStage(60.0, 35.0, 290.0, 20.0))
    payload: float = 16.0  # kg, orbiting sample container with 30 tubes [cited 2020 study: 14-16 kg]
    diameter: float = 0.5  # m [cited]
    cd: float = 0.5  # [estimate]
    vertical_time: float = 6.0  # s of vertical rise before pitch-over [estimate]
    pitch_rate: float = 1.0  # deg/s, free parameter solved by design_mav()

    @property
    def gross_mass(self) -> float:
        return self.stage1.propellant + self.stage1.inert + self.stage2.propellant + self.stage2.inert + self.payload


@dataclass(frozen=True)
class AscentConditions:
    body: Body = MARS
    latitude_deg: float = 18.4  # Jezero crater [memory]
    target_altitude: float = 380e3  # m, MSR baseline OS orbit [cited]
    stage2_pointing_err_deg: float = 0.0  # in-plane attitude error of stage 2
    pitch_rate_err: float = 0.0  # deg/s
    coast_timing_err: float = 0.0  # s
    density_factor: float = 1.0


@dataclass(frozen=True)
class AscentResult:
    periapsis_alt: float  # m
    apoapsis_alt: float  # m
    sma: float  # m
    ecc: float
    burnout1_alt: float  # m
    coast_apoapsis_alt: float  # m, after stage 1 alone
    coast_time: float  # s between stage-1 burnout and stage-2 ignition
    ideal_dv: float  # m/s, rocket equation sum
    delivered_dv: float  # m/s, orbital speed gained relative to the launch pad
    max_q: float  # Pa
    max_accel_g: float
    final_mass: float  # kg in orbit (payload + stage-2 inert)
    trajectory: np.ndarray = field(repr=False, default=None)  # columns t, x, y, vx, vy, m

    @property
    def losses(self) -> float:
        return self.ideal_dv - self.delivered_dv


def _orbit(mu: float, r: np.ndarray, v: np.ndarray):
    rn = np.linalg.norm(r)
    energy = 0.5 * v @ v - mu / rn
    a = -mu / (2 * energy)
    h = r[0] * v[1] - r[1] * v[0]
    e_vec = np.array([v[1] * h, -v[0] * h]) / mu - r / rn
    e = float(np.linalg.norm(e_vec))
    return a, e, h, e_vec


def _time_to_apoapsis(mu: float, r: np.ndarray, v: np.ndarray) -> tuple[float, np.ndarray]:
    a, e, h, e_vec = _orbit(mu, r, v)
    if a <= 0 or e >= 1:
        raise ValueError("not elliptic")
    rn = np.linalg.norm(r)
    cos_nu = np.clip((e_vec @ r) / (e * rn), -1, 1)
    nu = math.acos(cos_nu)
    if r @ v < 0:
        nu = 2 * math.pi - nu
    E = 2 * math.atan(math.sqrt((1 - e) / (1 + e)) * math.tan(nu / 2))
    M = E - e * math.sin(E)
    n = math.sqrt(mu / a**3)
    t = (math.pi - M % (2 * math.pi)) / n
    apo_dir = -e_vec / e
    return t, apo_dir


def simulate_ascent(mav: MAV, cond: AscentConditions | None = None, keep_trajectory: bool = False) -> AscentResult:
    cond = cond or AscentConditions()
    body = cond.body
    mu, R = body.mu, body.radius
    omega = body.rotation_rate * math.cos(math.radians(cond.latitude_deg))
    area = math.pi * (mav.diameter / 2) ** 2
    s1, s2 = mav.stage1, mav.stage2
    m_stage2_stack = s2.propellant + s2.inert + mav.payload
    rate = math.radians(mav.pitch_rate + cond.pitch_rate_err)
    stats = {"max_q": 0.0, "max_a": 0.0}

    def air_vel(x, y, vx, vy):
        return vx + omega * y, vy - omega * x

    def dyn(t, s, phase, thrust_dir):
        x, y, vx, vy, m = s
        r = math.hypot(x, y)
        h = r - R
        rho = body.rho0 * cond.density_factor * math.exp(-max(h, 0.0) / body.scale_height) if body.rho0 else 0.0
        ux, uy = air_vel(x, y, vx, vy)
        va = math.hypot(ux, uy)
        q = 0.5 * rho * va * va
        drag = q * mav.cd * area
        ax = -mu * x / r**3 - (drag / m) * (ux / va if va > 0 else 0)
        ay = -mu * y / r**3 - (drag / m) * (uy / va if va > 0 else 0)
        mdot = 0.0
        if phase == 1:
            stage = s1
            pitch = min(max(t - mav.vertical_time, 0.0) * rate, math.pi / 2)
            ex, ey = -y / r, x / r  # local east (prograde)
            dx = math.cos(pitch) * x / r + math.sin(pitch) * ex
            dy = math.cos(pitch) * y / r + math.sin(pitch) * ey
            T = stage.thrust
            mdot = stage.mdot
        elif phase == 2:
            dx, dy = thrust_dir
            T = s2.thrust
            mdot = s2.mdot
        else:
            T = 0.0
            dx = dy = 0.0
        ax += T / m * dx
        ay += T / m * dy
        if T > 0:
            stats["max_a"] = max(stats["max_a"], T / m / G0)
        stats["max_q"] = max(stats["max_q"], q)
        return [vx, vy, ax, ay, -mdot]

    opts = dict(rtol=1e-8, atol=1e-6, max_step=1.0)
    m0 = mav.gross_mass
    y0 = [R, 0.0, 0.0, omega * R, m0]
    seg1 = solve_ivp(dyn, (0, s1.burn_time), y0, args=(1, None), **opts)
    st = seg1.y[:, -1].copy()
    burnout1_alt = math.hypot(st[0], st[1]) - R
    st[4] = m_stage2_stack  # drop stage 1
    r_b, v_b = st[:2], st[2:4]
    t_apo, apo_dir = _time_to_apoapsis(mu, r_b, v_b)
    a1, e1, _, _ = _orbit(mu, r_b, v_b)
    coast_apo = a1 * (1 + e1) - R
    t_coast = max(t_apo - s2.burn_time / 2 + cond.coast_timing_err, 0.0)
    t1 = s1.burn_time
    seg2 = solve_ivp(dyn, (t1, t1 + t_coast), st, args=(0, None), **opts)
    st = seg2.y[:, -1]
    # Spin-stabilised: hold the local-horizontal direction at the predicted apoapsis.
    horiz = np.array([-apo_dir[1], apo_dir[0]])  # prograde (counter-clockwise)
    pe = math.radians(cond.stage2_pointing_err_deg)
    d = (math.cos(pe) * horiz[0] - math.sin(pe) * horiz[1], math.sin(pe) * horiz[0] + math.cos(pe) * horiz[1])
    t2 = t1 + t_coast
    seg3 = solve_ivp(dyn, (t2, t2 + s2.burn_time), st, args=(2, d), **opts)
    st = seg3.y[:, -1]
    r_f, v_f = st[:2], st[2:4]
    a, e, _, _ = _orbit(mu, r_f, v_f)
    ideal = s1.isp * G0 * math.log(m0 / (m0 - s1.propellant)) + s2.isp * G0 * math.log(
        m_stage2_stack / (m_stage2_stack - s2.propellant)
    )
    v_orbit_now = float(np.linalg.norm(v_f))
    # Speed gained: compare orbital energy, expressed as an equivalent speed at the
    # final radius, against the pad's rotation speed (removes the potential-energy term).
    delivered = math.sqrt(max(v_orbit_now**2 + 2 * mu * (1 / R - 1 / np.linalg.norm(r_f)), 0)) - omega * R
    traj = None
    if keep_trajectory:
        t = np.concatenate([seg1.t, seg2.t, seg3.t])
        Y = np.concatenate([seg1.y, seg2.y, seg3.y], axis=1)
        traj = np.vstack([t, Y]).T
    return AscentResult(
        periapsis_alt=a * (1 - e) - R,
        apoapsis_alt=a * (1 + e) - R if e < 1 else math.inf,
        sma=a,
        ecc=e,
        burnout1_alt=burnout1_alt,
        coast_apoapsis_alt=coast_apo,
        coast_time=t_coast,
        ideal_dv=ideal,
        delivered_dv=delivered,
        max_q=stats["max_q"],
        max_accel_g=stats["max_a"],
        final_mass=st[4],
        trajectory=traj,
    )


def design_mav(mav: MAV | None = None, cond: AscentConditions | None = None) -> tuple[MAV, AscentResult]:
    """Solve pitch rate and stage-2 propellant load so the MAV reaches a circular target orbit."""
    mav = mav or MAV()
    cond = cond or AscentConditions()
    target = cond.target_altitude

    def solve_pitch(m: MAV) -> MAV:
        def f(k):
            return simulate_ascent(replace(m, pitch_rate=k), cond).coast_apoapsis_alt - target

        k = brentq(f, 0.3, 5.0, xtol=1e-5)
        return replace(m, pitch_rate=k)

    def sma_err(p2: float) -> float:
        m = solve_pitch(replace(mav, stage2=replace(mav.stage2, propellant=p2)))
        return simulate_ascent(m, cond).sma - (cond.body.radius + target)

    # Semi-major axis grows monotonically with the stage-2 load; with apoapsis on
    # target, matching it makes the orbit circular.
    p2 = brentq(sma_err, 5.0, mav.stage2.propellant * 2.0, xtol=1e-3)
    final = solve_pitch(replace(mav, stage2=replace(mav.stage2, propellant=p2)))
    return final, simulate_ascent(final, cond, keep_trajectory=True)


@dataclass(frozen=True)
class AscentMonteCarlo:
    n: int
    periapsis_alt: np.ndarray
    apoapsis_alt: np.ndarray
    sma: np.ndarray
    min_periapsis_req: float

    @property
    def success_fraction(self) -> float:
        return float(np.mean(self.periapsis_alt >= self.min_periapsis_req))

    def summary(self) -> dict:
        return {
            "runs": self.n,
            "periapsis_mean_km": float(self.periapsis_alt.mean() / 1e3),
            "periapsis_3sigma_low_km": float((self.periapsis_alt.mean() - 3 * self.periapsis_alt.std()) / 1e3),
            "apoapsis_mean_km": float(self.apoapsis_alt.mean() / 1e3),
            "sma_sigma_km": float(self.sma.std() / 1e3),
            "fraction_above_requirement": self.success_fraction,
        }


def monte_carlo_ascent(
    mav: MAV,
    n: int = 300,
    seed: int = 1,
    min_periapsis: float = 250e3,
    cond: AscentConditions | None = None,
    isp_sigma: float = 0.005,
) -> AscentMonteCarlo:
    """Dispersions (1 sigma) [estimate]: Isp 0.5% (isp_sigma), propellant 0.3%, inert 1%,
    pitch rate 0.01 deg/s, stage-2 pointing 0.5 deg, coast timing 1 s, density 15%.

    Isp is the largest driver: solid motors cannot be shut down, so an Isp error
    turns straight into an orbit-energy error. Motor-lot acceptance firing can
    narrow it, which is the mitigation the campaign tests when SR-3 fails."""
    cond = cond or AscentConditions()
    rng = np.random.default_rng(seed)
    hp, ha, sma = [], [], []
    for _ in range(n):
        def disp(st: SolidStage) -> SolidStage:
            return replace(
                st,
                isp=st.isp * (1 + isp_sigma * rng.standard_normal()),
                propellant=st.propellant * (1 + 0.003 * rng.standard_normal()),
                inert=st.inert * (1 + 0.01 * rng.standard_normal()),
            )

        m = replace(mav, stage1=disp(mav.stage1), stage2=disp(mav.stage2))
        c = replace(
            cond,
            pitch_rate_err=0.01 * rng.standard_normal(),
            stage2_pointing_err_deg=0.5 * rng.standard_normal(),
            coast_timing_err=1.0 * rng.standard_normal(),
            density_factor=max(0.3, 1 + 0.15 * rng.standard_normal()),
        )
        r = simulate_ascent(m, c)
        hp.append(r.periapsis_alt)
        ha.append(r.apoapsis_alt)
        sma.append(r.sma)
    return AscentMonteCarlo(n, np.array(hp), np.array(ha), np.array(sma), min_periapsis)
