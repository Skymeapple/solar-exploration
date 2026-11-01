"""Propellant lines, hot-gas ducts and valves.

Each line is sized for a velocity limit (liquid) or a Mach limit (gas), given a
wall from hoop stress, and its pressure drop is found from the Darcy equation.
Lengths come from the engine layout and are estimates.

Valve masses use an estimated correlation, m = 4 kg + 800 * D^2 * sqrt(p / 100 bar)
(D in m), set so a 150 mm valve at 300 bar comes out near 35 kg. It is not fitted to
published data; treat it as +-50%.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..constants import RHO_LCH4, RHO_LOX
from ..cycle import CycleResult
from ..engine import EnginePerformance
from .cooling import CoolingResult, methane_h, methane_props
from .injector import InjectorDesign
from .materials import MATERIALS, allowable
from .turbopump import gas_properties


@dataclass(frozen=True)
class FeedInputs:
    v_suction_max: float = 10.0  # m/s, pump inlet lines
    v_liquid_max: float = 25.0  # m/s, high-pressure liquid
    mach_gas_max: float = 0.12  # hot-gas ducts; low speed also limits ignition risk in oxygen-rich gas
    min_wall: float = 1.5e-3  # m
    roughness: float = 5e-6  # m


@dataclass(frozen=True)
class Line:
    tag: str
    description: str
    fluid: str  # "LOX", "LCH4", "CH4 (supercritical)", "ox-rich gas", "fuel-rich gas"
    flow: float  # kg/s
    pressure: float  # Pa
    temperature: float  # K
    density: float
    length: float  # m, estimate
    inner_diameter: float
    wall_thickness: float
    velocity: float
    pressure_drop: float  # Pa
    material: str
    mass: float


@dataclass(frozen=True)
class Valve:
    tag: str
    description: str
    line: str
    kind: str
    pressure: float
    diameter: float
    material: str
    mass: float


def _friction(re: float, rel: float) -> float:
    return (-1.8 * math.log10((rel / 3.7) ** 1.11 + 6.9 / re)) ** -2


def _line(tag, desc, fluid, flow, p, t, rho, mu, length, v_max, material, fi: FeedInputs,
          sound_speed: float | None = None) -> Line:
    v = v_max if sound_speed is None else fi.mach_gas_max * sound_speed
    d = math.sqrt(4 * flow / (math.pi * rho * v))
    v = flow / (rho * math.pi * d**2 / 4)
    mat = MATERIALS[material]
    t_wall = max(p * d / (2 * allowable(mat, t)), fi.min_wall)
    re = rho * v * d / mu
    dp = _friction(re, fi.roughness / d) * (length / d) * 0.5 * rho * v**2
    # Bends and fittings: about 3 velocity heads per line.
    dp += 3.0 * 0.5 * rho * v**2
    mass = mat.density * math.pi * (d + t_wall) * t_wall * length * 1.3  # flanges and supports
    return Line(tag, desc, fluid, flow, p, t, rho, length, d, t_wall, v, dp, material, mass)


def _valve(tag, desc, line: Line, kind: str, material: str) -> Valve:
    m = 4.0 + 800.0 * line.inner_diameter**2 * math.sqrt(line.pressure / 100e5)
    return Valve(tag, desc, line.tag, kind, line.pressure, line.inner_diameter, material, m)


def design_feed(perf: EnginePerformance, cycle: CycleResult, cooling: CoolingResult, inj: InjectorDesign,
                fi: FeedInputs | None = None) -> tuple[list[Line], list[Valve]]:
    fi = fi or FeedInputs()
    a = cycle.assumptions
    fu, ox = cycle.fuel_shaft, cycle.ox_shaft
    f2 = ox.turbine_flow / (1 + ox.preburner_mixture_ratio)
    o2 = ox.turbine_flow - f2
    f1 = fu.turbine_flow / (1 + fu.preburner_mixture_ratio)
    o1 = fu.turbine_flow - f1
    mu_lox, mu_lch4 = 1.9e-4, 1.2e-4  # Pa s near the boiling points
    out = cooling.stations[0]
    cp_props = methane_props(out.p_coolant, methane_h(out.p_coolant, out.t_coolant))

    def gas(p, mr, t):
        _t, cp, g, r = gas_properties(p, mr)
        rho = p / (r * t)
        return rho, math.sqrt(g * r * t)

    rho_ox_gas, a_ox_gas = gas(inj.manifold_pressure, ox.preburner_mixture_ratio, inj.ox_temperature)
    rho_fu_gas, a_fu_gas = gas(inj.manifold_pressure, fu.preburner_mixture_ratio, inj.fuel_temperature)
    lines = [
        _line("L01", "LOX inlet duct, vehicle interface to oxidizer pump", "LOX", ox.pump_flow, a.p_pump_inlet, 90.0,
              RHO_LOX, mu_lox, 0.6, fi.v_suction_max, "SS316L", fi),
        _line("L02", "Methane inlet duct, vehicle interface to fuel pump", "LCH4", fu.pump_flow, a.p_pump_inlet, 111.6,
              RHO_LCH4, mu_lch4, 0.6, fi.v_suction_max, "SS316L", fi),
        _line("L03", "Oxidizer pump discharge to oxygen-rich preburner", "LOX", o2, ox.pump_discharge_pressure, 100.0,
              RHO_LOX, mu_lox, 0.5, fi.v_liquid_max, "A286", fi),
        _line("L04", "Oxidizer pump discharge to fuel-rich preburner", "LOX", o1,
              max(ox.pump_discharge_pressure, fu.preburner_pressure * (1 + a.dp_pb_injector)), 100.0,
              RHO_LOX, mu_lox, 1.2, fi.v_liquid_max, "A286", fi),
        _line("L05", "Fuel pump discharge to cooling-jacket inlet manifold", "LCH4", f1, fu.pump_discharge_pressure,
              120.0, RHO_LCH4, mu_lch4, 2.2, fi.v_liquid_max, "IN718", fi),
        _line("L06", "Cooling-jacket outlet to fuel-rich preburner", "CH4 (supercritical)", f1, out.p_coolant,
              out.t_coolant, cp_props["rho"], cp_props["mu"], 0.8, fi.v_liquid_max * 2, "IN718", fi),
        _line("L07", "Fuel pump kick stage to oxygen-rich preburner", "LCH4", f2, ox.preburner_pressure * (1 + a.dp_pb_injector),
              120.0, RHO_LCH4, mu_lch4, 1.2, fi.v_liquid_max, "IN718", fi),
        _line("L08", "Oxidizer turbine exhaust to main injector (oxygen-rich gas)", "ox-rich gas", ox.turbine_flow,
              inj.manifold_pressure, inj.ox_temperature, rho_ox_gas, 4e-5, 0.35, 0, "OXSA", fi, sound_speed=a_ox_gas),
        _line("L09", "Fuel turbine exhaust to main injector (fuel-rich gas)", "fuel-rich gas", fu.turbine_flow,
              inj.manifold_pressure, inj.fuel_temperature, rho_fu_gas, 3e-5, 0.6, 0, "IN718", fi, sound_speed=a_fu_gas),
    ]
    by = {ln.tag: ln for ln in lines}
    valves = [
        _valve("V01", "Main oxidizer valve (MOV), oxygen-rich preburner LOX supply", by["L03"], "ball valve, electric actuator", "MonelK500"),
        _valve("V02", "Fuel-rich preburner oxidizer valve (FPOV)", by["L04"], "poppet / throttling valve", "MonelK500"),
        _valve("V03", "Main fuel valve (MFV), cooling-jacket supply", by["L05"], "ball valve, electric actuator", "IN718"),
        _valve("V04", "Oxygen-rich preburner fuel valve (OPFV)", by["L07"], "poppet / throttling valve", "IN718"),
        _valve("V05", "Coolant control valve (CCV), jacket outlet", by["L06"], "throttling valve", "IN718"),
        _valve("V06", "LOX inlet isolation / prevalve (vehicle side, listed for interface)", by["L01"], "butterfly", "SS316L"),
        _valve("V07", "Methane inlet isolation / prevalve (vehicle side)", by["L02"], "butterfly", "SS316L"),
    ]
    return lines, valves
