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
) -> ShaftResult | None:
    p_turbine_exit = pc * (1.0 + a.dp_main_injector)

    def discharge(p_pb: float) -> float:
        return p_pb * (1.0 + a.dp_pb_injector) + extra_dp

    def residual(p_pb: float) -> float:
        w_t = _turbine_power(turbine_flow, p_pb, p_turbine_exit, pb_mr, eta_turbine)
        w_p = _pump_power(pump_flow, discharge(p_pb), a.p_pump_inlet, rho, eta_pump)
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
        pump_power=_pump_power(pump_flow, p_d, a.p_pump_inlet, rho, eta_pump),
        turbine_power=_turbine_power(turbine_flow, p_root, p_turbine_exit, pb_mr, eta_turbine),
    )


def solve_cycle(perf: EnginePerformance, a: CycleAssumptions | None = None) -> CycleResult:
    a = a or CycleAssumptions()
    pc = perf.design.pc
    p_guess = 2.0 * pc  # preburner pressure used for the gas properties

    mr_f = _preburner_mr(p_guess, a.t_fuel_rich_pb, ox_rich=False)
    mr_o = _preburner_mr(p_guess, a.t_ox_rich_pb, ox_rich=True)

    # Split the propellants between the two preburners:
    # f1 + f2 = fuel, o1 + o2 = ox, o1 = mr_f * f1, o2 = mr_o * f2.
    fuel, ox = perf.mdot_fuel, perf.mdot_ox
    f1 = (ox - mr_o * fuel) / (mr_f - mr_o)
    f2 = fuel - f1
    if f1 <= 0 or f2 <= 0:
        return CycleResult(False, None, None, "Preburner temperatures cannot be met at this mixture ratio", a)
    o1, o2 = mr_f * f1, mr_o * f2

    fuel_shaft = _solve_shaft(
        "fuel",
        pc=pc,
        turbine_flow=f1 + o1,
        pb_mr=mr_f,
        t_in=a.t_fuel_rich_pb,
        pump_flow=fuel,
        rho=RHO_LCH4,
        eta_pump=a.eta_pump_fuel,
        eta_turbine=a.eta_turbine_fuel,
        extra_dp=a.dp_cooling * pc,
        a=a,
    )
    ox_shaft = _solve_shaft(
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
    )
    if fuel_shaft is None or ox_shaft is None:
        missing = [n for n, s in (("fuel", fuel_shaft), ("oxidizer", ox_shaft)) if s is None]
        return CycleResult(False, fuel_shaft, ox_shaft, f"No power balance on the {' and '.join(missing)} shaft", a)
    return CycleResult(True, fuel_shaft, ox_shaft, "", a)
