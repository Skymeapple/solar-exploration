"""Full-flow staged combustion power balance (fidelity level L0/L1).

Two shafts, each balanced on its own:

* Fuel shaft: a fuel-rich preburner burns all the fuel that is not sent to the
  oxidizer-rich preburner, plus a little oxygen, and its turbine drives the
  methane pump.
* Oxidizer shaft: an oxygen-rich preburner burns the rest of the oxygen with a
  little methane, and its turbine drives the LOX pump.

Both turbine exhausts enter the main chamber as gas, so each turbine exit
pressure is the chamber pressure plus the main injector drop. For each shaft we
find the lowest preburner pressure at which turbine power equals pump power.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from scipy.optimize import brentq

from . import thermo
from .constants import R_UNIVERSAL, RHO_LCH4, RHO_LOX
from .engine import EnginePerformance


@dataclass(frozen=True)
class CycleAssumptions:
    """Inputs SpaceX has not published. Every value here is an assumption."""

    t_fuel_rich_pb: float = 1000.0  # K, fuel-rich turbine inlet temperature
    t_ox_rich_pb: float = 800.0  # K, oxygen-rich turbine inlet temperature
    t_limit_fuel_turbine: float = 1100.0  # K, material limit for G2
    t_limit_ox_turbine: float = 850.0  # K, material limit for G2 (oxidizing gas)
    eta_pump_fuel: float = 0.75
    eta_pump_ox: float = 0.75
    eta_turbine_fuel: float = 0.75
    eta_turbine_ox: float = 0.75
    dp_main_injector: float = 0.20  # fraction of Pc
    dp_pb_injector: float = 0.15  # fraction of preburner pressure
    dp_cooling: float = 0.20  # fraction of Pc, fuel side only
    p_pump_inlet: float = 4e5  # Pa
    p_pump_discharge_max: float = 1000e5  # Pa, design limit for G2
    # Fuel for the oxygen-rich preburner bypasses the cooling jacket. When the oxygen-rich
    # preburner runs above the fuel pump discharge, a small kick stage on the fuel shaft
    # raises that flow to the preburner injector pressure (added by the component iteration).
    fuel_kick_stage: bool = False
    ox_kick_stage: bool = False  # same idea for the fuel-rich preburner's oxygen
    # Line, valve and duct losses as fractions of Pc. Zero in the L1 model; the component
    # iteration sets them from the sized lines so the pressure ladder closes.
    dp_liquid_lines: float = 0.0  # added to every pump discharge
    dp_hot_gas_ducts: float = 0.0  # added to every turbine exit pressure


@dataclass(frozen=True)
class ShaftResult:
    name: str
    preburner_mixture_ratio: float
    turbine_inlet_temperature: float
    turbine_flow: float  # kg/s
    preburner_pressure: float  # Pa
    turbine_pressure_ratio: float
    pump_discharge_pressure: float  # Pa
    pump_power: float  # W
    turbine_power: float  # W
    pump_flow: float = 0.0  # kg/s through the main pump
    kick_power: float = 0.0  # W, kick stage on this shaft

    @property
    def power_error(self) -> float:
        return abs(self.turbine_power - self.pump_power) / self.pump_power


@dataclass(frozen=True)
class CycleResult:
    closed: bool
    fuel_shaft: ShaftResult | None
    ox_shaft: ShaftResult | None
    message: str = ""
    assumptions: CycleAssumptions = field(default_factory=CycleAssumptions)


def _preburner_mr(p: float, t_target: float, ox_rich: bool) -> float:
    """Mixture ratio that gives the target preburner temperature."""
    lo, hi = (15.0, 200.0) if ox_rich else (0.05, 1.0)
    return brentq(lambda mr: thermo.chamber(p, mr).temperature - t_target, lo, hi, xtol=1e-4)


def _turbine_power(mdot: float, p_in: float, p_out: float, mr: float, eta: float) -> float:
    gas = thermo.chamber(p_in, mr)
    r_gas = R_UNIVERSAL / (gas.molecular_weight / 1000.0)
    gamma_frozen = gas.cp_frozen / (gas.cp_frozen - r_gas)
    expo = (gamma_frozen - 1.0) / gamma_frozen
    return mdot * gas.cp_frozen * gas.temperature * eta * (1.0 - (p_out / p_in) ** expo)


def _pump_power(mdot: float, p_out: float, p_in: float, rho: float, eta: float) -> float:
    return mdot * (p_out - p_in) / (rho * eta)


def _solve_shaft(
    name: str,
    *,
    pc: float,
    turbine_flow: float,
    pb_mr: float,
    t_in: float,
    pump_flow: float,
    rho: float,
    eta_pump: float,
    eta_turbine: float,
    extra_dp: float,
    a: CycleAssumptions,
    kick_power: float = 0.0,
) -> ShaftResult | None:
    p_turbine_exit = pc * (1.0 + a.dp_main_injector + a.dp_hot_gas_ducts)

    def discharge(p_pb: float) -> float:
        return p_pb * (1.0 + a.dp_pb_injector) + extra_dp + a.dp_liquid_lines * pc

    def residual(p_pb: float) -> float:
        w_t = _turbine_power(turbine_flow, p_pb, p_turbine_exit, pb_mr, eta_turbine)
        w_p = _pump_power(pump_flow, discharge(p_pb), a.p_pump_inlet, rho, eta_pump) + kick_power
        return w_t - w_p

    # Scan upward for the first preburner pressure where the turbine catches up
    # with the pump; that is the lowest-pressure (and lightest) design.
    p_max = a.p_pump_discharge_max * 1.5
    p_prev = p_turbine_exit * 1.01
    r_prev = residual(p_prev)
    p_root = None
    steps = 60
    for i in range(1, steps + 1):
        p = p_turbine_exit * 1.01 + (p_max - p_turbine_exit * 1.01) * i / steps
        r = residual(p)
        if r_prev < 0 <= r:
            p_root = brentq(residual, p_prev, p, xtol=1.0)
            break
        p_prev, r_prev = p, r
    if p_root is None:
        return None

    p_d = discharge(p_root)
    return ShaftResult(
        name=name,
        preburner_mixture_ratio=pb_mr,
        turbine_inlet_temperature=t_in,
        turbine_flow=turbine_flow,
        preburner_pressure=p_root,
        turbine_pressure_ratio=p_root / p_turbine_exit,
        pump_discharge_pressure=p_d,
        pump_power=_pump_power(pump_flow, p_d, a.p_pump_inlet, rho, eta_pump) + kick_power,
        turbine_power=_turbine_power(turbine_flow, p_root, p_turbine_exit, pb_mr, eta_turbine),
        pump_flow=pump_flow,
        kick_power=kick_power,
    )


def solve_cycle(perf: EnginePerformance, a: CycleAssumptions | None = None) -> CycleResult:
    a = a or CycleAssumptions()
    pc = perf.design.pc
    p_guess = 2.0 * pc  # preburner pressure used for the gas properties

    mr_f = _preburner_mr(p_guess, a.t_fuel_rich_pb, ox_rich=False)
    mr_o = _preburner_mr(p_guess, a.t_ox_rich_pb, ox_rich=True)

    # Split the propellants between the two preburners:
    # f1 + f2 = fuel, o1 + o2 = ox, o1 = mr_f * f1, o2 = mr_o * f2.
    fuel_total, ox = perf.mdot_fuel, perf.mdot_ox
    f1 = (ox - mr_o * fuel_total) / (mr_f - mr_o)
    f2 = fuel_total - f1
    if f1 <= 0 or f2 <= 0:
        return CycleResult(False, None, None, "Preburner temperatures cannot be met at this mixture ratio", a)
    o1, o2 = mr_f * f1, mr_o * f2

    def ox_solve(kick: float) -> ShaftResult | None:
        return _solve_shaft(
            "oxidizer",
            pc=pc,
            turbine_flow=f2 + o2,
            pb_mr=mr_o,
            t_in=a.t_ox_rich_pb,
            pump_flow=ox,
            rho=RHO_LOX,
            eta_pump=a.eta_pump_ox,
            eta_turbine=a.eta_turbine_ox,
            extra_dp=0.0,
            a=a,
            kick_power=kick,
        )

    def fuel_solve(kick: float) -> ShaftResult | None:
        return _solve_shaft(
            "fuel",
            pc=pc,
            turbine_flow=f1 + o1,
            pb_mr=mr_f,
            t_in=a.t_fuel_rich_pb,
            pump_flow=fuel_total,
            rho=RHO_LCH4,
            eta_pump=a.eta_pump_fuel,
            eta_turbine=a.eta_turbine_fuel,
            extra_dp=a.dp_cooling * pc,
            a=a,
            kick_power=kick,
        )

    # Kick stages: the fuel kick lifts the oxygen-rich preburner's fuel (f2) above the main
    # fuel pump discharge; the oxidizer kick lifts the fuel-rich preburner's oxygen (o1)
    # above the main oxidizer pump discharge. Each kick's power depends on the other
    # shaft's preburner pressure, so the two shafts are solved together by fixed-point
    # iteration.
    ox_kick = fuel_kick = 0.0
    ox_shaft = fuel_shaft = None
    for _ in range(15):
        ox_shaft = ox_solve(ox_kick)
        fuel_shaft = fuel_solve(fuel_kick)
        if ox_shaft is None or fuel_shaft is None:
            break
        new_fuel_kick = new_ox_kick = 0.0
        if a.fuel_kick_stage:
            need = ox_shaft.preburner_pressure * (1.0 + a.dp_pb_injector) + a.dp_liquid_lines * pc
            dp_kick = max(need - fuel_shaft.pump_discharge_pressure, 0.0)
            new_fuel_kick = f2 * dp_kick / (RHO_LCH4 * a.eta_pump_fuel)
        if a.ox_kick_stage:
            need = fuel_shaft.preburner_pressure * (1.0 + a.dp_pb_injector) + a.dp_liquid_lines * pc
            dp_kick = max(need - ox_shaft.pump_discharge_pressure, 0.0)
            new_ox_kick = o1 * dp_kick / (RHO_LOX * a.eta_pump_ox)
        if abs(new_fuel_kick - fuel_kick) < 1e3 and abs(new_ox_kick - ox_kick) < 1e3:
            break
        fuel_kick, ox_kick = new_fuel_kick, new_ox_kick
    if fuel_shaft is None or ox_shaft is None:
        missing = [n for n, s in (("fuel", fuel_shaft), ("oxidizer", ox_shaft)) if s is None]
        return CycleResult(False, fuel_shaft, ox_shaft, f"No power balance on the {' and '.join(missing)} shaft", a)
    return CycleResult(True, fuel_shaft, ox_shaft, "", a)
