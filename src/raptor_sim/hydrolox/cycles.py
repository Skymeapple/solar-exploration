"""Power balance for the two hydrogen engine cycles (fidelity L1).

Closed expander (RL10, Vinci, BE-7 class)
    Hydrogen from the pump cools the chamber and nozzle, picks up heat, drives
    one turbine (geared to both pumps), then enters the main injector. Turbine
    power is limited by the heat the wall can pass, which grows more slowly than
    pump power as chamber pressure rises. That gives the "expander wall": a
    maximum chamber pressure for each thrust. Heat load is the Bartz correlation
    integrated over a generated chamber and nozzle contour, with one heat-transfer
    factor fitted so the RL10B-2 hydrogen leaves the jacket at the assumed 220 K.

Fuel-rich staged combustion (RS-25 class)
    All hydrogen and a little oxygen burn in fuel-rich preburners at about 1,000 K;
    the gas drives both turbines and then enters the main chamber. Same
    lowest-pressure root search as the methane full-flow cycle in
    `raptor_sim.cycle`, whose pump-power helper is reused.

Hydrogen properties come from CoolProp (parahydrogen), as the methane
component models do.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from scipy.optimize import brentq

from ..constants import RHO_LOX
from ..cycle import _pump_power
from ..engine import EnginePerformance
from . import thermo

RHO_LH2 = 70.8  # kg/m^3 at 20.3 K [cited: CoolProp parahydrogen]
FLUID = "ParaHydrogen"


def _cp():
    import CoolProp.CoolProp as CP

    return CP


@dataclass(frozen=True)
class ExpanderAssumptions:
    """Every value is an estimate unless tagged."""

    contraction_ratio: float = 3.0  # chamber / throat area
    l_star: float = 0.9  # m, characteristic length for LOX/LH2
    converge_half_angle_deg: float = 30.0
    nozzle_half_angle_deg: float = 15.0  # equivalent cone for the bell
    eps_cooled: float = 61.0  # area ratio to which the nozzle is regen-cooled (RL10A-3-3A tube bundle) [mem]
    t_wall: float = 750.0  # K, hot-wall temperature (copper liner / steel tubes)
    recovery: float = 0.9  # adiabatic wall / stagnation temperature
    heat_factor: float = 1.0  # fitted by calibrate() on RL10B-2
    t_jacket_target_rl10: float = 220.0  # K, RL10 turbine inlet temperature [mem, low confidence]
    t_pump_inlet: float = 21.0  # K
    p_pump_inlet: float = 2.5e5  # Pa
    eta_pump_h2: float = 0.60
    eta_pump_ox: float = 0.65
    eta_turbine: float = 0.60  # small partial-admission turbine
    dp_main_injector: float = 0.20  # fraction of Pc
    dp_jacket: float = 0.15  # fraction of Pc
    p_pump_discharge_max: float = 250e5  # Pa
    t_turbine_max: float = 600.0  # K (well above any expander value; checks the heat model)


@dataclass(frozen=True)
class ExpanderResult:
    closed: bool
    heat_load: float  # W into the hydrogen
    t_turbine_inlet: float  # K
    turbine_inlet_pressure: float  # Pa
    turbine_pressure_ratio: float
    h2_pump_discharge: float  # Pa
    pump_power: float  # W, both pumps
    turbine_power: float  # W
    max_turbine_power: float  # W the turbine gives at the pump-limit pressure
    pump_power_at_limit: float  # W the pumps need at that pressure
    message: str = ""
    assumptions: ExpanderAssumptions = field(default_factory=ExpanderAssumptions)

    @property
    def power_margin(self) -> float:
        """Spare turbine power at the highest allowed pump pressure, as a fraction of pump need there.

        Negative means the engine is past the expander wall.
        """
        return self.max_turbine_power / self.pump_power_at_limit - 1.0 if self.pump_power_at_limit else -1.0


def _contour(perf: EnginePerformance, a: ExpanderAssumptions, n: int = 160) -> list[tuple[float, float, float]]:
    """(dx, radius, area ratio) slices from the injector to the end of the cooled nozzle."""
    rt = perf.throat_diameter / 2
    rc = rt * math.sqrt(a.contraction_ratio)
    l_cyl = max(a.l_star / a.contraction_ratio, 0.02)  # volume of the convergent section neglected
    l_conv = (rc - rt) / math.tan(math.radians(a.converge_half_angle_deg))
    re = rt * math.sqrt(min(a.eps_cooled, perf.design.eps))
    l_div = (re - rt) / math.tan(math.radians(a.nozzle_half_angle_deg))
    out = []
    for seg_len, r0, r1 in ((l_cyl, rc, rc), (l_conv, rc, rt), (l_div, rt, re)):
        for i in range(n):
            r = r0 + (r1 - r0) * (i + 0.5) / n
            out.append((seg_len / n, r, (r / rt) ** 2))
    return out


def heat_load(perf: EnginePerformance, a: ExpanderAssumptions) -> float:
    """Integrated Bartz heat load to the regenerative jacket, W."""
    d = perf.design
    tr = thermo.throat_transport(d.pc, d.mixture_ratio)
    gas = perf.chamber
    dt = perf.throat_diameter
    h_throat = (
        0.026 / dt**0.2 * tr["mu"] ** 0.2 * tr["cp"] / tr["pr"] ** 0.6 * (d.pc / perf.cstar) ** 0.8 * (dt / (0.75 * dt)) ** 0.1
    )
    t_aw = a.recovery * gas.temperature
    q = 0.0
    for dx, r, ar in _contour(perf, a):
        q += a.heat_factor * h_throat * ar ** (-0.9) * (t_aw - a.t_wall) * 2 * math.pi * r * dx
    return q


def _h2_out_temperature(q: float, mdot: float, p: float, a: ExpanderAssumptions) -> float:
    cp = _cp()
    h_in = cp.PropsSI("H", "T", a.t_pump_inlet + 4.0, "P", p, FLUID)  # pump work warms it a few K
    return float(cp.PropsSI("T", "H", h_in + q / mdot, "P", p, FLUID))


def _turbine_power(mdot: float, t_in: float, p_in: float, p_out: float, eta: float) -> float:
    cp = _cp()
    h_in = cp.PropsSI("H", "T", t_in, "P", p_in, FLUID)
    s_in = cp.PropsSI("S", "T", t_in, "P", p_in, FLUID)
    h_out_s = cp.PropsSI("H", "S", s_in, "P", p_out, FLUID)
    return mdot * eta * (h_in - h_out_s)


def solve_expander(perf: EnginePerformance, a: ExpanderAssumptions | None = None) -> ExpanderResult:
    a = a or ExpanderAssumptions()
    pc = perf.design.pc
    q = heat_load(perf, a)
    p_te = pc * (1 + a.dp_main_injector)
    p_ox = pc * (1 + a.dp_main_injector) * 1.05
    w_ox = _pump_power(perf.mdot_ox, p_ox, a.p_pump_inlet, RHO_LOX, a.eta_pump_ox)

    def parts(p_ti: float):
        p_d = p_ti + a.dp_jacket * pc
        t_ti = _h2_out_temperature(q, perf.mdot_fuel, 0.5 * (p_d + p_ti), a)
        w_t = _turbine_power(perf.mdot_fuel, t_ti, p_ti, p_te, a.eta_turbine)
        w_p = _pump_power(perf.mdot_fuel, p_d, a.p_pump_inlet, RHO_LH2, a.eta_pump_h2) + w_ox
        return w_t, w_p, t_ti, p_d

    p_ti_max = a.p_pump_discharge_max - a.dp_jacket * pc
    if p_ti_max <= p_te * 1.01:
        return ExpanderResult(False, q, 0, 0, 0, 0, w_ox, 0, 0, 0, "pump limit below turbine exit pressure", a)
    w_t_max, w_p_max, t_max, _ = parts(p_ti_max)

    def resid(p: float) -> float:
        w_t, w_p, _, _ = parts(p)
        return w_t - w_p

    lo = p_te * 1.01
    root = None
    steps = 40
    prev_p, prev_r = lo, resid(lo)
    for i in range(1, steps + 1):
        p = lo + (p_ti_max - lo) * i / steps
        r = resid(p)
        if prev_r < 0 <= r:
            root = brentq(resid, prev_p, p, xtol=100.0)
            break
        prev_p, prev_r = p, r
    if root is None:
        return ExpanderResult(False, q, t_max, p_ti_max, p_ti_max / p_te, a.p_pump_discharge_max, w_p_max, w_t_max,
                              w_t_max, w_p_max, "turbine cannot drive the pumps: past the expander wall", a)
    w_t, w_p, t_ti, p_d = parts(root)
    ok = t_ti <= a.t_turbine_max
    return ExpanderResult(ok, q, t_ti, root, root / p_te, p_d, w_p, w_t, w_t_max, w_p_max,
                          "" if ok else "turbine inlet above limit", a)


def calibrate(perf_rl10b2: EnginePerformance, a: ExpanderAssumptions | None = None) -> ExpanderAssumptions:
    """Fit heat_factor so RL10B-2 hydrogen leaves the jacket at t_jacket_target_rl10.

    Heat load is linear in heat_factor, so the fit is a single ratio.
    """
    from dataclasses import replace

    a = replace(a or ExpanderAssumptions(), heat_factor=1.0)
    cp = _cp()
    p_mid = perf_rl10b2.design.pc * 2.0
    h_in = cp.PropsSI("H", "T", a.t_pump_inlet + 4.0, "P", p_mid, FLUID)
    h_out = cp.PropsSI("H", "T", a.t_jacket_target_rl10, "P", p_mid, FLUID)
    q_target = perf_rl10b2.mdot_fuel * (h_out - h_in)
    return replace(a, heat_factor=q_target / heat_load(perf_rl10b2, a))


# ---------------------------------------------------------------- staged combustion


@dataclass(frozen=True)
class StagedAssumptions:
    t_preburner: float = 1_000.0  # K, fuel-rich turbine inlet (RS-25 runs about 1,000 K) [mem]
    eta_pump_h2: float = 0.75
    eta_pump_ox: float = 0.75
    eta_turbine: float = 0.75
    dp_main_injector: float = 0.20
    dp_pb_injector: float = 0.15
    dp_cooling: float = 0.25  # fraction of Pc, chamber and nozzle jackets
    p_pump_inlet: float = 2.0e6  # Pa, after the low-pressure boost pumps
    p_pump_discharge_max: float = 550e5


@dataclass(frozen=True)
class StagedResult:
    closed: bool
    preburner_mixture_ratio: float
    preburner_pressure: float
    h2_pump_discharge: float
    pump_power: float
    turbine_power: float
    message: str = ""


def solve_staged(perf: EnginePerformance, a: StagedAssumptions | None = None) -> StagedResult:
    a = a or StagedAssumptions()
    pc = perf.design.pc
    p_guess = 1.8 * pc
    mr_pb = brentq(lambda mr: thermo.chamber(p_guess, mr).temperature - a.t_preburner, 0.3, 2.0, xtol=1e-4)
    fuel, ox = perf.mdot_fuel, perf.mdot_ox
    ox_pb = mr_pb * fuel
    gas_flow = fuel + ox_pb
    p_te = pc * (1 + a.dp_main_injector)

    def turbine(p_pb: float) -> float:
        g = thermo.chamber(p_pb, mr_pb)
        r_gas = 8.314462618 / (g.molecular_weight / 1000)
        gam = g.cp_frozen / (g.cp_frozen - r_gas)
        return gas_flow * g.cp_frozen * g.temperature * a.eta_turbine * (1 - (p_te / p_pb) ** ((gam - 1) / gam))

    def pumps(p_pb: float) -> tuple[float, float]:
        p_fuel = p_pb * (1 + a.dp_pb_injector) + a.dp_cooling * pc
        p_ox_pb = p_pb * (1 + a.dp_pb_injector)
        p_ox_main = p_te * 1.05
        w = (
            _pump_power(fuel, p_fuel, a.p_pump_inlet, RHO_LH2, a.eta_pump_h2)
            + _pump_power(ox - ox_pb, p_ox_main, a.p_pump_inlet, RHO_LOX, a.eta_pump_ox)
            + _pump_power(ox_pb, p_ox_pb, a.p_pump_inlet, RHO_LOX, a.eta_pump_ox)
        )
        return w, p_fuel

    def resid(p: float) -> float:
        return turbine(p) - pumps(p)[0]

    lo, hi = p_te * 1.01, a.p_pump_discharge_max
    prev_p, prev_r = lo, resid(lo)
    for i in range(1, 61):
        p = lo + (hi - lo) * i / 60
        r = resid(p)
        if prev_r < 0 <= r:
            root = brentq(resid, prev_p, p, xtol=100.0)
            w, p_fuel = pumps(root)
            ok = p_fuel <= a.p_pump_discharge_max
            return StagedResult(ok, mr_pb, root, p_fuel, w, turbine(root), "" if ok else "fuel pump over limit")
        prev_p, prev_r = p, r
    return StagedResult(False, mr_pb, hi, hi, pumps(hi)[0], turbine(hi), "no power balance below the pump limit")


def heat_margin(perf: EnginePerformance, a: ExpanderAssumptions | None = None, tol: float = 0.005) -> float:
    """Fraction of the wall heat load the engine could lose and still close its power balance.

    This is the expander's design margin: it covers the uncertainty in the
    Bartz heat load (the largest single uncertainty in the cycle). Negative
    values say how much extra heat a non-closing engine would need.
    """
    from dataclasses import replace

    a = a or ExpanderAssumptions()

    def closes(scale: float) -> bool:
        r = solve_expander(perf, replace(a, heat_factor=a.heat_factor * scale))
        return r.closed or r.message == "turbine inlet above limit"  # power balance is what counts here

    if not closes(1.0):
        lo, hi = 1.0, 3.0
        if not closes(hi):
            return -2.0
        while hi - lo > tol:
            mid = 0.5 * (lo + hi)
            lo, hi = (lo, mid) if closes(mid) else (mid, hi)
        return 1.0 - hi
    lo, hi = 0.05, 1.0
    if closes(lo):
        return 1.0 - lo
    while hi - lo > tol:
        mid = 0.5 * (lo + hi)
        lo, hi = (lo, mid) if closes(mid) else (mid, hi)
    return 1.0 - hi
