"""Propulsion trades for crewed missions: chemical CH4/LOX, nuclear thermal
(NTP), and nuclear electric (NEP).

CITED
- Raptor Vacuum Isp ~380 s (SpaceX public figure; this repo's model gives 363 s).
- NTP Isp ~900 s for a hydrogen NERVA-derived engine, as used in NASA Mars
  Design Reference Architecture 5.0 (Drake ed., NASA-SP-2009-566). NERVA
  tests demonstrated ~825-850 s class performance.
- NEP specific mass targets 10-20 kg/kWe in NASA studies; today's
  demonstrated systems are far heavier (ESTIMATE range kept wide).
ESTIMATES
- Stage dry-mass fractions (tanks, structure, engines) below.
- Low-thrust delta-v: Edelbaum coplanar circle-to-circle |v1 - v2| (exact for
  continuous tangential thrust between circular orbits), verified here by
  numerical integration of a spiral.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.integrate import solve_ivp

from ..constants import G0
from ..mission import AU, MU_SUN


@dataclass(frozen=True)
class ImpulsiveSystem:
    name: str
    isp: float  # s
    tank_fraction: float  # tank + structure mass per kg propellant (ESTIMATE)
    engine_mass_t: float  # engines, shielding (ESTIMATE)


CHEM_CH4 = ImpulsiveSystem("CH4/LOX (Raptor Vac class)", 380.0, 0.06, 6.0)
CHEM_CH4_MODEL = ImpulsiveSystem("CH4/LOX (this repo's RVac model)", 363.0, 0.06, 6.0)
NTP_LH2 = ImpulsiveSystem("Nuclear thermal LH2", 900.0, 0.15, 3 * 3.5 + 5.0)  # 3 engines + shadow shield


def stage_mass(system: ImpulsiveSystem, payload_t: float, dv: float) -> tuple[float, float]:
    """(propellant t, initial mass t) for a single stage carrying payload_t through dv."""
    R = math.exp(dv / (system.isp * G0))
    # m0 = payload + engine + prop*(1+tank); m0/mf = R, mf = payload + engine + tank*prop
    k = system.tank_fraction
    denom = 1 - (R - 1) * k
    if denom <= 0:
        return math.inf, math.inf
    prop = (R - 1) * (payload_t + system.engine_mass_t) / denom
    return prop, payload_t + system.engine_mass_t + prop * (1 + k)


@dataclass(frozen=True)
class NEPSystem:
    name: str
    power_mwe: float
    specific_mass: float  # kg/kWe
    isp: float  # s
    efficiency: float  # jet power / electric power (ESTIMATE 0.6)

    @property
    def power_plant_t(self) -> float:
        return self.power_mwe * 1e3 * self.specific_mass / 1e3

    def thrust(self) -> float:
        return 2 * self.efficiency * self.power_mwe * 1e6 / (self.isp * G0)


def edelbaum_dv(r1: float, r2: float, mu: float = MU_SUN) -> float:
    return abs(math.sqrt(mu / r1) - math.sqrt(mu / r2))


def spiral(r0: float, r_target: float, accel0: float, isp: float, mu: float = MU_SUN) -> tuple[float, float]:
    """Integrate a planar tangential-thrust spiral with mass flow; returns (dv used, time s)."""
    ve = isp * G0

    def rhs(t, y):
        x, yy, vx, vy, m = y
        r = math.hypot(x, yy)
        v = math.hypot(vx, vy)
        a = accel0 / m
        return [vx, vy, -mu * x / r**3 + a * vx / v, -mu * yy / r**3 + a * vy / v, -accel0 / ve]

    # mass normalised to 1 at start; accel0 = F/m0, mdot/m0 = accel0/ve
    def reach(t, y):
        return math.hypot(y[0], y[1]) - r_target
    reach.terminal = True
    v0 = math.sqrt(mu / r0)
    sol = solve_ivp(rhs, (0, 20 * 365.25 * 86400), [r0, 0, 0, v0, 1.0], events=reach, rtol=1e-9, atol=1e-3,
                    max_step=86400 * 2)
    m_end = sol.y[4, -1]
    return ve * math.log(1 / m_end), sol.t[-1]


@dataclass(frozen=True)
class NEPTrip:
    system: NEPSystem
    payload_t: float
    dv: float
    propellant_t: float
    initial_mass_t: float
    trip_days: float
    burn_days: float


def nep_trip(system: NEPSystem, payload_t: float, r1: float = AU, r2: float = 1.524 * AU,
             tofs=range(60, 1500, 10), penalty: float = 1.2, burn_fraction: float = 0.7,
             tank_fraction: float = 0.05) -> NEPTrip | None:
    """L0 heliocentric NEP trip estimate: the shortest flight time the system can fly.

    For each flight time the impulsive transfer between circular coplanar orbits
    gives v-infinity at both ends; the low-thrust delta-v is ``penalty`` times
    their sum (ESTIMATE, finite-burn losses). The trip is feasible when the
    propellant can be expelled within ``burn_fraction`` of the flight time.
    Crew joins at a high Earth orbit; planet spirals are not included.
    """
    from .transfers import circular_transfer

    ve = system.isp * G0
    mdot = system.thrust() / ve
    dry = payload_t + system.power_plant_t + 5.0  # +5 t thrusters/PPU (ESTIMATE)
    for tof in tofs:
        vv = circular_transfer(r1, r2, tof)
        if vv is None:
            continue
        dv = penalty * (vv[0] + vv[1])
        R = math.exp(dv / ve)
        denom = 1 - (R - 1) * tank_fraction
        if denom <= 0:
            continue
        prop = (R - 1) * dry / denom
        burn = prop * 1e3 / mdot / 86400
        if burn <= burn_fraction * tof:
            return NEPTrip(system, payload_t, dv, prop, dry + prop * (1 + tank_fraction), float(tof), burn)
    return None


def staged_stack(system: ImpulsiveSystem, payload_t: float, burns: list[float]) -> float:
    """Initial mass (t) when each burn uses its own drop stage (last burn sized first).

    Engines are carried once by the core (ESTIMATE: engines stay with the payload).
    """
    core = payload_t + system.engine_mass_t
    m = core
    for dv in reversed(burns):
        R = math.exp(dv / (system.isp * G0))
        k = system.tank_fraction
        denom = 1 - (R - 1) * k
        if denom <= 0:
            return math.inf
        prop = (R - 1) * m / denom
        m = m + prop * (1 + k)
    return m
