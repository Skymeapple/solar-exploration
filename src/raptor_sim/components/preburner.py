"""Preburners: fuel-rich and oxygen-rich gas generators feeding the two turbines.

Volume from a residence time (stay time) long enough to finish combustion and
mix out temperature streaks before the turbine: 2 to 5 ms is typical for
staged-combustion preburners (Huzel & Huang sec. 4.3; NASA SP-8081). The
shell is a cylinder with hemispherical heads sized for hoop stress.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..cycle import CycleResult, ShaftResult
from .materials import MATERIALS, allowable
from .turbopump import gas_properties


@dataclass(frozen=True)
class PreburnerInputs:
    residence_time: float = 3.0e-3  # s
    length_to_diameter: float = 1.5
    fuel_rich_material: str = "IN718"
    ox_rich_material: str = "OXSA"
    temperature_streak_factor: float = 1.10  # local peak / mean gas temperature at the wall, estimate
    injector_plate_thickness_factor: float = 2.0  # injector plate = factor * shell thickness
    # A propellant-cooled inner liner (incoming liquid flows behind a thin liner before the
    # injector) keeps the structural wall below the gas temperature. Off in the first guess.
    fuel_rich_liner_cooled: bool = False
    ox_rich_liner_cooled: bool = False
    liner_cooling_factor: float = 0.80  # structural wall temperature / gas temperature with a cooled liner, estimate


@dataclass(frozen=True)
class PreburnerDesign:
    name: str
    pressure: float
    temperature: float
    mixture_ratio: float
    flow: float
    gas_density: float
    volume: float
    diameter: float
    length: float
    wall_thickness: float
    wall_temperature: float
    hoop_stress: float
    allowable: float
    material: str
    mass: float


def _one(name: str, s: ShaftResult, material: str, pi: PreburnerInputs, cooled: bool) -> PreburnerDesign:
    _t, _cp, _g, r_gas = gas_properties(s.preburner_pressure, s.preburner_mixture_ratio)
    t_gas = s.turbine_inlet_temperature
    rho = s.preburner_pressure / (r_gas * t_gas)
    vol = s.turbine_flow * pi.residence_time / rho
    # cylinder of L/D with two hemispherical heads: V = pi D^2/4 L + pi D^3/6
    d = (vol / (math.pi / 4 * pi.length_to_diameter + math.pi / 6)) ** (1 / 3)
    length = pi.length_to_diameter * d
    mat = MATERIALS[material]
    # An uncooled wall sees the gas, and temperature streaks add 10%.
    t_wall = pi.temperature_streak_factor * t_gas * (pi.liner_cooling_factor if cooled else 1.0)
    sig = allowable(mat, t_wall)
    t = max(s.preburner_pressure * d / 2 / sig, 3e-3)
    hoop = s.preburner_pressure * d / 2 / t
    shell = math.pi * d * length * t + math.pi * d**2 * t / 2  # cylinder + two hemispherical heads (thinner, kept equal)
    plate = math.pi / 4 * d**2 * pi.injector_plate_thickness_factor * t
    mass = mat.density * (shell + plate) * 1.25  # flanges, igniter port, instrumentation bosses
    if cooled:
        mass *= 1.15  # liner and coolant passages
    return PreburnerDesign(name, s.preburner_pressure, t_gas, s.preburner_mixture_ratio, s.turbine_flow, rho, vol, d,
                           length, t, t_wall, hoop, sig, material, mass)


def design_preburners(cycle: CycleResult, pi: PreburnerInputs | None = None) -> tuple[PreburnerDesign, PreburnerDesign]:
    pi = pi or PreburnerInputs()
    return (
        _one("fuel-rich preburner", cycle.fuel_shaft, pi.fuel_rich_material, pi, pi.fuel_rich_liner_cooled),
        _one("oxygen-rich preburner", cycle.ox_shaft, pi.ox_rich_material, pi, pi.ox_rich_liner_cooled),
    )
