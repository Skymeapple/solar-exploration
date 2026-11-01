"""Phases 7 and 8: propellant production on Mars (ISRU) and ascent from the Martian surface.

ISRU chemistry (public, the Sabatier / electrolysis route used in NASA design
reference architectures and SpaceX's stated plan):
    CO2 + 4 H2 -> CH4 + 2 H2O       (Sabatier, exothermic)
    2 H2O -> 2 H2 + O2              (electrolysis)
  net: CO2 + 2 H2O -> CH4 + 2 O2, giving O/F = 4.0 by mass; the engine uses 3.6, the rest is vented.
Energy per kilogram is an estimate built up from the steps below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..constants import G0
from .bodies import MU_MARS, OMEGA_MARS, R_MARS, mars_atmosphere
from .flight import Body, Forces, State, orbit_apsides, rk4_step, surface_state
from .vehicle import Stack

SOL_DAYS = 1.02749


@dataclass(frozen=True)
class IsruPlant:
    electrolysis_kwh_per_kg_h2o: float = 4.41 / 0.70  # 15.9 MJ/kg ideal (public HHV) at 70% efficiency [est]
    water_mining_kwh_per_kg: float = 1.0  # excavate, heat and melt subsurface ice [est]
    co2_capture_kwh_per_kg: float = 0.2  # compress Martian air [est]
    liquefaction_kwh_per_kg: float = 0.8  # cryocooling CH4 and O2 [est, ~30% of Carnot]
    mixture_ratio: float = 3.6
    solar_array_m2: float = 20_000.0
    solar_efficiency: float = 0.20  # [est] flexible arrays
    insolation_kwh_m2_sol: float = 2.5  # mean at 40 deg N, clear sky [est from Mars Pathfinder / MER data]
    storage_efficiency: float = 0.90  # night operation through batteries [est]
    dust_degradation_per_sol: float = 0.0005  # with periodic cleaning [est]
    nuclear_kwe: float = 0.0  # fission power units (Kilopower-class, 10 kWe each) [public concept]
    availability: float = 0.90  # plant uptime [est]
    commissioning_sols: int = 60  # set-up before production starts [est]

    def kwh_per_kg_propellant(self) -> float:
        # Per kg CH4: 4.5 kg H2O through electrolysis (2.25 net + 2.25 recycled from Sabatier),
        # 2.25 kg H2O mined, 2.75 kg CO2 captured. Propellant per kg CH4 = 1 + MR.
        per_ch4 = 4.5 * self.electrolysis_kwh_per_kg_h2o + 2.25 * self.water_mining_kwh_per_kg + 2.75 * self.co2_capture_kwh_per_kg
        prop_per_ch4 = 1 + self.mixture_ratio
        return per_ch4 / prop_per_ch4 + self.liquefaction_kwh_per_kg


@dataclass
class IsruResult:
    produced_kg: np.ndarray  # per sample, at the departure date
    required_kg: float
    sols_available: int
    mean_power_kw: float

    @property
    def p_success(self) -> float:
        return float(np.mean(self.produced_kg >= self.required_kg))


def isru_monte_carlo(plant: IsruPlant, required_kg: float, stay_days: float, n: int = 1000, seed: int = 3,
                     global_storm_per_year: float = 1 / 3, global_storm_factor: float = 0.3,
                     storm_override: bool | None = None) -> IsruResult:
    """Sol-by-sol production with random regional and global dust storms.

    Global storms: about one Mars year in three (public: 2001, 2007, 2018 events),
    lasting 60-120 sols with surface sunlight cut to ~30% [est from the 2018 storm that ended Opportunity].
    Regional storms: 2% chance per sol of a 5-20 sol storm at 60% sunlight [est].
    """
    rng = np.random.default_rng(seed)
    sols = int(stay_days / SOL_DAYS)
    e_per_kg = plant.kwh_per_kg_propellant()
    produced = np.zeros(n)
    for k in range(n):
        factor = np.ones(sols)
        has_global = rng.random() < 1 - (1 - global_storm_per_year) ** (sols / 668.6) if storm_override is None else storm_override
        if has_global:
            start = rng.integers(0, max(1, sols - 60))
            dur = rng.integers(60, 121)
            factor[start:start + dur] = global_storm_factor
        i = 0
        while i < sols:
            if rng.random() < 0.02:
                dur = rng.integers(5, 21)
                factor[i:i + dur] = np.minimum(factor[i:i + dur], 0.6)
                i += dur
            i += 1
        days = np.arange(sols)
        solar = plant.solar_array_m2 * plant.insolation_kwh_m2_sol * plant.solar_efficiency * plant.storage_efficiency
        solar = solar * factor * (1 - plant.dust_degradation_per_sol) ** days
        energy = solar + plant.nuclear_kwe * 24.66
        up = rng.random(sols) < plant.availability
        energy = np.where((days >= plant.commissioning_sols) & up, energy, 0.0)
        produced[k] = energy.sum() / e_per_kg
    mean_kw = (plant.solar_array_m2 * plant.insolation_kwh_m2_sol * plant.solar_efficiency + plant.nuclear_kwe * 24.66) / 24.66
    return IsruResult(produced, required_kg, sols, mean_kw)


# --------------------------------------------------------------------- Mars ascent

LANDING_LATITUDE_DEG = 40.0  # Arcadia Planitia region, a candidate with shallow ice [public, SpaceX/NASA studies]
MARS = Body(MU_MARS, R_MARS, OMEGA_MARS * math.cos(math.radians(LANDING_LATITUDE_DEG)), mars_atmosphere)


@dataclass
class MarsAscentResult:
    reached_orbit: bool
    residual: float  # kg propellant left in the 300 km departure orbit
    dv_spent: float  # m/s, powered ascent plus circularisation
    gravity_loss: float
    max_g: float
    meco_alt_km: float
    circularise_dv: float
    kick_deg: float


def _gravity_turn(stack, payload, propellant, isp_factor, kick_deg, target_alt, n_sl):
    """Vertical rise, pitch kick, then thrust along the surface-relative velocity (gravity turn)
    until the apoapsis reaches the departure altitude; coast; circularise on the vacuum engines."""
    eng = stack.engine.scaled(isp_factor)
    dry = stack.ship_dry
    s = surface_state(MARS, dry + payload + propellant)
    dt = 0.5
    dv = g_loss = max_g = 0.0
    reached = False
    while s.m > dry + payload:
        p_amb = MARS.atmosphere(s.r - MARS.radius).pressure
        f_full = n_sl * eng.thrust(p_amb) + stack.ship_vac_engines * eng.rvac_thrust
        mdot_full = n_sl * eng.mdot + stack.ship_vac_engines * eng.rvac_thrust / (eng.rvac_isp * G0)
        thr = max(eng.min_throttle, min(1.0, stack.max_axial_g * G0 * s.m / f_full))
        vr, vt = s.radial_tangential()
        if s.t < 4.0:
            pitch = math.pi / 2
        elif s.t < 14.0:
            pitch = math.pi / 2 - math.radians(kick_deg) * (s.t - 4.0) / 10.0
        else:
            pitch = None  # along the surface-relative velocity (gravity turn)
        tel = rk4_step(s, MARS, Forces(f_full * thr, mdot_full * thr, pitch, cd_area=0.4 * stack.area), dt)
        dv += f_full * thr / s.m * dt
        g_loss += MARS.mu / s.r**2 * math.sin(tel.gamma_air) * dt
        max_g = max(max_g, tel.accel_g)
        if s.r < MARS.radius - 1:
            break
        if orbit_apsides(s, MARS.mu, MARS.radius)[1] >= target_alt:
            reached = True
            break
    rp, ra = orbit_apsides(s, MARS.mu, MARS.radius)
    r2 = MARS.radius + target_alt
    a = (rp + ra) / 2 + MARS.radius
    dvc = math.sqrt(MARS.mu / r2) - math.sqrt(max(0.0, MARS.mu * (2 / r2 - 1 / a)))
    m_end = s.m / math.exp(dvc / (eng.rvac_isp * G0))
    residual = m_end - dry - payload if reached else -1e9
    return MarsAscentResult(reached and residual > 0, residual, dv + dvc, g_loss, max_g,
                            (s.r - MARS.radius) / 1e3, dvc, kick_deg)


def mars_ascent(stack: Stack, payload: float, propellant: float, isp_factor: float = 1.0,
                target_alt: float = 300e3, n_sl: int | None = None, kick_deg: float | None = None) -> MarsAscentResult:
    """Single-stage ascent from the surface to the 300 km departure orbit on all six engines.

    The kick angle is optimised for the most propellant left in orbit unless given.
    """
    from scipy.optimize import minimize_scalar

    n_sl = stack.ship_sl_engines if n_sl is None else n_sl
    if kick_deg is None:
        f = lambda k: -_gravity_turn(stack, payload, propellant, isp_factor, k, target_alt, n_sl).residual
        grid = [10.0 + 6.0 * i for i in range(14)]
        k0 = min(grid, key=f)
        r = minimize_scalar(f, bounds=(max(5.0, k0 - 6.0), min(89.0, k0 + 6.0)), method="bounded", options={"xatol": 0.2})
        kick_deg = float(r.x) if r.fun <= f(k0) else k0
    return _gravity_turn(stack, payload, propellant, isp_factor, kick_deg, target_alt, n_sl)
