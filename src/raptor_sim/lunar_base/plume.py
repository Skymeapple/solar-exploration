"""Landing plume load on the surface, landing pad sizing and ejecta ranges.

The plume of each nozzle follows the Simons far-field model: momentum flux per
steradian falls off as cos^(2/(gamma-1)) of (pi/2 * theta/theta_lim), where the
limiting turning angle theta_lim comes from the Prandtl-Meyer expansion of the
exit flow into vacuum. Exit Mach and velocity come from the project's engine
model (:mod:`raptor_sim.engine`) for the Raptor-class case.

On the ground the plume gives a normal pressure (gas stopped at the surface) and a
radial wall-jet shear. Shear above a threshold strips loose regolith. Thresholds
and the wall shear coefficient are estimates; Apollo landings are the only
calibration and only in a relative sense (:func:`erosion_index`).

Ejecta: on the Moon there is no air to slow particles, so grains launched at 100 to
2,000 m/s (Apollo 12 estimate from Surveyor III damage) and 1 to 3 degrees above
the horizon travel tens to thousands of kilometres. A spaceport therefore needs
hard pads plus berms, or kilometres of separation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq

from .orbits import G_MOON, MU_MOON, R_MOON
from .provenance import Value

METZGER = "Metzger et al., NTRS 20090022233 (Apollo 12 ejecta 100-2,000 m/s from Surveyor III damage)"
IMMER = "Immer, Metzger et al. 2011, Icarus 211 (Apollo ejecta 1-3 deg above horizon; low confidence)"

SPEC: dict[str, Value] = {
    "ejecta_v_min": Value(100.0, "m/s", "cited", METZGER),
    "ejecta_v_max": Value(2000.0, "m/s", "cited", METZGER),
    "ejecta_angle_min": Value(1.0, "deg", "cited", IMMER),
    "ejecta_angle_max": Value(3.0, "deg", "cited", IMMER),
    "wall_cf": Value(0.005, "-", "estimated", "turbulent wall-jet skin friction on the momentum flux"),
    "wall_jet_beta": Value(0.7, "-", "estimated", "share of thrust turned into radial wall-jet momentum"),
    "wall_jet_spread": Value(0.1, "-", "estimated", "wall-jet thickness over radius"),
    "landing_dispersion": Value(10.0, "m", "estimated", "3-sigma touchdown error with pad beacons"),
    "lm_disturbed_radius": Value(75.0, "m", "estimated", "Apollo LM reflectance-altered zone radius; LROC images show zones of order 100-200 m across"),
    "tau_fines": Value(1.0, "Pa", "estimated", "shear that lifts 50-100 um grains with van der Waals cohesion"),
    "tau_gravel": Value(30.0, "Pa", "estimated", "shear that moves cm-size gravel and compacted soil crust"),
    "p_pad": Value(2_000.0, "Pa", "estimated", "normal pressure above which a hard (sintered or paved) pad is needed"),
}


@dataclass(frozen=True)
class Nozzle:
    thrust_n: float
    exit_mach: float
    gamma: float  # exhaust ratio of specific heats near the exit
    exit_half_angle_deg: float = 12.0  # bell nozzle exit lip angle, estimated
    height_m: float = 3.0  # exit plane above the ground
    x_m: float = 0.0  # position in the horizontal plane
    y_m: float = 0.0


def area_ratio_to_mach(eps: float, gamma: float) -> float:
    def f(m: float) -> float:
        return (1 / m) * ((2 / (gamma + 1)) * (1 + 0.5 * (gamma - 1) * m * m)) ** ((gamma + 1) / (2 * (gamma - 1))) - eps
    return brentq(f, 1.0001, 50.0)


def prandtl_meyer(m: float, gamma: float) -> float:
    a = math.sqrt((gamma + 1) / (gamma - 1))
    return a * math.atan(math.sqrt((m * m - 1) / (a * a))) - math.atan(math.sqrt(m * m - 1))


def theta_lim(n: Nozzle) -> float:
    nu_max = 0.5 * math.pi * (math.sqrt((n.gamma + 1) / (n.gamma - 1)) - 1)
    return min(nu_max - prandtl_meyer(n.exit_mach, n.gamma) + math.radians(n.exit_half_angle_deg), 0.5 * math.pi * 0.999)


def _profile(theta: np.ndarray | float, n: Nozzle):
    tl = theta_lim(n)
    k = 2 / (n.gamma - 1)
    x = np.clip(np.asarray(theta) / tl, 0.0, 1.0)
    return np.where(np.asarray(theta) < tl, np.cos(0.5 * math.pi * x) ** k, 0.0)


def _norm(n: Nozzle) -> float:
    """Constant K so that the axial momentum flux integrates to the thrust."""
    tl = theta_lim(n)
    integral = quad(lambda t: float(_profile(t, n)) * math.cos(t) * 2 * math.pi * math.sin(t), 0.0, tl, limit=200)[0]
    return n.thrust_n / integral


def surface_loads(nozzles: list[Nozzle], x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Normal pressure and wall shear (Pa) on the ground at points (x, y), summed over nozzles."""
    p = np.zeros_like(x, dtype=float)
    tau = np.zeros_like(x, dtype=float)
    cf = SPEC["wall_cf"].value
    # Radial wall jet after impingement: momentum beta*T spreads over 2*pi*r*delta,
    # delta = spread*r, so momentum flux falls as 1/r^2 (estimated closure).
    t_total = sum(n.thrust_n for n in nozzles)
    cx = float(np.mean([n.x_m for n in nozzles]))
    cy = float(np.mean([n.y_m for n in nozzles]))
    h = float(np.mean([n.height_m for n in nozzles]))
    r_c2 = (x - cx) ** 2 + (y - cy) ** 2 + h * h
    beta, spread = SPEC["wall_jet_beta"].value, SPEC["wall_jet_spread"].value
    tau += 0.5 * cf * beta * t_total / (2 * math.pi * spread * r_c2)
    for n in nozzles:
        k = _norm(n)
        r = np.hypot(x - n.x_m, y - n.y_m)
        d2 = r * r + n.height_m**2
        th = np.arctan2(r, n.height_m)
        flux = k * _profile(th, n) / d2  # momentum flux density along the ray, Pa
        p += flux * np.cos(th) ** 2
        tau += cf * flux * 2 * np.sin(th) * np.cos(th)  # zero at the stagnation point, peak near 45 deg
    return p, tau


def radial_profile(nozzles: list[Nozzle], r_max: float = 2_000.0, n: int = 4000) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Loads along a ray from the vehicle centre (azimuthally the worst case for a ring is not taken)."""
    r = np.geomspace(0.05, r_max, n)
    p, tau = surface_loads(nozzles, r, np.zeros_like(r))
    return r, p, tau


def radius_where(r: np.ndarray, q: np.ndarray, threshold: float) -> float:
    above = np.nonzero(q > threshold)[0]
    return float(r[above[-1]]) if len(above) else 0.0


@dataclass(frozen=True)
class Lander:
    name: str
    mass_t: float  # at touchdown
    nozzle_count: int
    exit_mach: float
    gamma: float
    exit_height_m: float  # exit plane above ground at touchdown
    ring_radius_m: float  # nozzles on a ring of this radius (0 = one central nozzle)
    descent_rate: float = 1.0  # m/s over the final 30 m, estimated
    hover_s: float = 10.0  # estimated
    thrust_to_weight: float = 1.0  # 1 for landing (hover), above 1 for liftoff


def lander_nozzles(lander: Lander, extra_height: float = 0.0) -> list[Nozzle]:
    t = lander.thrust_to_weight * lander.mass_t * 1e3 * G_MOON / lander.nozzle_count  # shared equally
    out = []
    for i in range(lander.nozzle_count):
        a = 2 * math.pi * i / lander.nozzle_count
        out.append(Nozzle(t, lander.exit_mach, lander.gamma, height_m=lander.exit_height_m + extra_height,
                          x_m=lander.ring_radius_m * math.cos(a), y_m=lander.ring_radius_m * math.sin(a)))
    return out


def raptor_exit_mach(gamma: float = 1.22) -> float:
    from ..engine import EngineDesign

    return area_ratio_to_mach(EngineDesign().eps, gamma)


def landers() -> list[Lander]:
    m_raptor = raptor_exit_mach()
    return [
        Lander("Apollo LM (calibration)", 7.3, 1, area_ratio_to_mach(47.5, 1.22), 1.22, 1.5, 0.0),
        Lander("Starship-class, 1 Raptor deep-throttled", 270.0, 1, m_raptor, 1.22, 3.0, 0.0),
        Lander("Starship-class, 3 Raptors", 270.0, 3, m_raptor, 1.22, 3.0, 1.3),
        Lander("Starship-class, high landing thrusters", 270.0, 24, area_ratio_to_mach(20.0, 1.25), 1.25, 30.0, 4.5),
        Lander("Lunar tanker, 100 t, 4 small engines", 100.0, 4, area_ratio_to_mach(40.0, 1.22), 1.22, 2.0, 1.5),
        Lander("Liftoff: Starship-class tanker, 1,700 t, 3 Raptors, T/W 1.3", 1_700.0, 3, m_raptor, 1.22, 3.0, 1.3,
               thrust_to_weight=1.3, hover_s=0.0),
    ]


@dataclass(frozen=True)
class PadSizing:
    lander: str
    peak_pressure_kpa: float
    hard_pad_radius_m: float  # p > p_pad
    apron_radius_m: float  # gravel moves: stabilised surface needed
    fines_erosion_radius_m: float  # loose dust stripped: unavoidable without a pad, set berms beyond
    erosion_index: float  # relative to Apollo LM
    pad_radius_m: float  # apron plus landing dispersion
    disturbed_radius_m: float  # surface visibly disturbed, scaled from Apollo as sqrt(thrust)


def erosion_index(lander: Lander, tau_c: float | None = None) -> float:
    """Integral of excess shear over area and time for the last 30 m of descent plus hover."""
    tau_c = SPEC["tau_fines"].value if tau_c is None else tau_c
    r = np.geomspace(0.05, 3_000.0, 1500)
    dr = np.gradient(r)
    total = 0.0
    heights = np.arange(30.0, -0.01, -1.0)
    dt = 1.0 / lander.descent_rate
    for h in heights:
        nz = lander_nozzles(lander, extra_height=h)
        _, tau = surface_loads(nz, r, np.zeros_like(r))
        rate = np.sum(np.maximum(tau - tau_c, 0.0) * 2 * math.pi * r * dr)
        total += rate * (dt + (lander.hover_s if h == 0 else 0.0))
    return total


def size_pad(lander: Lander, apollo_index: float | None = None) -> PadSizing:
    r, p, tau = radial_profile(lander_nozzles(lander))
    idx = erosion_index(lander)
    ref = apollo_index if apollo_index is not None else erosion_index(landers()[0])
    return PadSizing(
        lander.name,
        float(p.max() / 1e3),
        radius_where(r, p, SPEC["p_pad"].value),
        radius_where(r, tau, SPEC["tau_gravel"].value),
        radius_where(r, tau, SPEC["tau_fines"].value),
        idx / ref,
        radius_where(r, tau, SPEC["tau_gravel"].value) + SPEC["landing_dispersion"].value,
        disturbed_radius(lander),
    )


def disturbed_radius(lander: Lander) -> float:
    """Wall-jet scaling r ~ sqrt(thrust), anchored on the Apollo LM (estimated anchor)."""
    lm = landers()[0]
    return SPEC["lm_disturbed_radius"].value * math.sqrt(lander.thrust_to_weight * lander.mass_t / lm.mass_t)


def ejecta_range_km(v: float, angle_deg: float) -> float:
    """Ballistic range over a spherical airless Moon; inf if the grain orbits or escapes."""
    g = math.radians(angle_deg)
    nu = v * v * R_MOON / MU_MOON
    denom = 1 - nu * math.cos(g) ** 2
    if denom <= 0:
        return math.inf
    psi = 2 * math.atan2(nu * math.sin(g) * math.cos(g), denom)
    return psi * R_MOON / 1e3


def berm_height_m(distance_from_pad_edge_m: float, angle_deg: float | None = None, margin_m: float = 1.0) -> float:
    """Berm top that intercepts ejecta leaving the pad edge at the steepest cited angle."""
    a = SPEC["ejecta_angle_max"].value if angle_deg is None else angle_deg
    return distance_from_pad_edge_m * math.tan(math.radians(a)) + margin_m


ESCAPE_SPEED = math.sqrt(2 * MU_MOON / R_MOON)
CIRCULAR_SPEED = math.sqrt(MU_MOON / R_MOON)
