"""Phase 4 and 8: finite departure burns (trans-Mars and trans-Earth injection) and the rocket equation helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..constants import G0
from .bodies import MU_EARTH, MU_MARS, R_EARTH, R_MARS
from .flight import Body, Forces, State, rk4_step
from .vehicle import EngineData


def propellant_for(dv: float, m_final: float, isp: float) -> float:
    return m_final * (math.exp(dv / (isp * G0)) - 1)


def dv_from(m0: float, m1: float, isp: float) -> float:
    return isp * G0 * math.log(m0 / m1)


def impulsive_departure(vinf: float, mu: float, r: float) -> float:
    return math.sqrt(vinf**2 + 2 * mu / r) - math.sqrt(mu / r)


@dataclass
class DepartureBurn:
    impulsive_dv: float
    finite_dv: float  # delta-v actually spent
    gravity_loss: float
    burn_time: float
    propellant: float
    initial_twr: float


def finite_departure(planet: str, vinf: float, m0: float, engine: EngineData, n_vac: int, n_sl: int = 0,
                     alt: float = 300e3, isp_factor: float = 1.0) -> DepartureBurn:
    """Prograde (velocity-pointed) burn from a circular orbit until the orbit energy gives the target v-infinity."""
    mu, R = (MU_EARTH, R_EARTH) if planet == "earth" else (MU_MARS, R_MARS)
    body = Body(mu, R, 0.0, lambda h: _VAC)
    r0 = R + alt
    s = State(r0, 0.0, 0.0, math.sqrt(mu / r0), m0)
    e_target = vinf**2 / 2
    eng = engine.scaled(isp_factor)
    thrust = n_vac * eng.rvac_thrust + n_sl * eng.thrust_vac
    mdot = n_vac * eng.rvac_thrust / (eng.rvac_isp * G0) + n_sl * eng.mdot
    dv = 0.0
    dt = 1.0
    while (s.vx**2 + s.vy**2) / 2 - mu / s.r < e_target:
        dv += thrust / s.m * dt
        rk4_step(s, body, Forces(thrust, mdot, None), dt)
        if s.m < 0.05 * m0:
            break
    imp = impulsive_departure(vinf, mu, r0)
    return DepartureBurn(imp, dv, dv - imp, s.t, m0 - s.m, thrust / (m0 * G0))


class _Vac:
    density = 0.0
    pressure = 0.0
    sound_speed = 1.0


_VAC = _Vac()
