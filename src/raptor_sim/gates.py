"""Verification gates G0 to G7 from the design procedure.

G4 (cooling), G5 (turbopumps) and G6 (engine system) come from the component
models in `raptor_sim.components`. They run for the selected engine design, whose
converged component design point is saved in `components/design_point.json`
(295 bar after the chamber-pressure sweep: at 300 bar the cooling jacket and the
methane pump do not close). Other engine designs (for example from the optimizer)
report them as not run until their components have been designed.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import thermo
from .benchmarks import G7_KEYS, G7_TOLERANCE, RAPTOR_2_SEA_LEVEL
from .cycle import CycleAssumptions, CycleResult, solve_cycle
from .engine import EngineDesign, EnginePerformance, size_engine

G1_TOLERANCE = 0.01
G2_POWER_TOLERANCE = 0.005
G3_ISP_TOLERANCE = 0.03


@dataclass(frozen=True)
class GateResult:
    gate: str
    passed: bool | None  # None means not run yet
    detail: str


def _rel(a: float, b: float) -> float:
    return abs(a - b) / abs(b)


def gate_g1(design: EngineDesign) -> GateResult:
    """CEA and an independent Cantera equilibrium agree on T and MW within 1%."""
    cea = thermo.chamber(design.pc, design.mixture_ratio)
    t_ct, mw_ct = thermo.cantera_chamber(design.pc, design.mixture_ratio)
    dt, dmw = _rel(t_ct, cea.temperature), _rel(mw_ct, cea.molecular_weight)
    ok = dt <= G1_TOLERANCE and dmw <= G1_TOLERANCE
    return GateResult(
        "G1 Thermochemistry",
        ok,
        f"Tc CEA {cea.temperature:.0f} K vs Cantera {t_ct:.0f} K ({dt:.2%}); "
        f"MW {cea.molecular_weight:.2f} vs {mw_ct:.2f} g/mol ({dmw:.2%})",
    )


def gate_g2(cycle: CycleResult) -> GateResult:
    """Both shafts balance within 0.5%, turbines below temperature limits, pumps below discharge limit."""
    if not cycle.closed:
        return GateResult("G2 Cycle balance", False, cycle.message)
    a: CycleAssumptions = cycle.assumptions
    f, o = cycle.fuel_shaft, cycle.ox_shaft
    problems = []
    for s in (f, o):
        if s.power_error > G2_POWER_TOLERANCE:
            problems.append(f"{s.name} shaft power error {s.power_error:.2%}")
        if s.pump_discharge_pressure > a.p_pump_discharge_max:
            problems.append(f"{s.name} pump discharge {s.pump_discharge_pressure / 1e5:.0f} bar over limit")
    if f.turbine_inlet_temperature > a.t_limit_fuel_turbine:
        problems.append("fuel turbine too hot")
    if o.turbine_inlet_temperature > a.t_limit_ox_turbine:
        problems.append("oxidizer turbine too hot")
    detail = (
        f"fuel preburner {f.preburner_pressure / 1e5:.0f} bar, pump {f.pump_power / 1e6:.1f} MW; "
        f"ox preburner {o.preburner_pressure / 1e5:.0f} bar, pump {o.pump_power / 1e6:.1f} MW"
    )
    if problems:
        detail += "; " + "; ".join(problems)
    return GateResult("G2 Cycle balance", not problems, detail)


def gate_g3(perf: EnginePerformance) -> GateResult:
    """Isp within 3% of the benchmark and no flow separation at sea level."""
    b = RAPTOR_2_SEA_LEVEL
    d_sl = _rel(perf.isp_sl, b["isp_sl"].value)
    d_vac = _rel(perf.isp_vac, b["isp_vac"].value)
    attached = perf.separation_margin > 1.0
    ok = d_sl <= G3_ISP_TOLERANCE and d_vac <= G3_ISP_TOLERANCE and attached
    return GateResult(
        "G3 Performance",
        ok,
        f"Isp SL {perf.isp_sl:.1f} s ({d_sl:.2%}), vac {perf.isp_vac:.1f} s ({d_vac:.2%}); "
        f"exit pressure {perf.exit_pressure / 1e5:.2f} bar, separation margin {perf.separation_margin:.2f}",
    )


def gate_g7(perf: EnginePerformance) -> GateResult:
    """Thrust, Isp and chamber pressure within 5% of public Raptor 2 figures."""
    model = {
        "thrust_sl": perf.design.thrust_sl,
        "isp_sl": perf.isp_sl,
        "isp_vac": perf.isp_vac,
        "pc": perf.design.pc,
    }
    errors = {k: _rel(model[k], RAPTOR_2_SEA_LEVEL[k].value) for k in G7_KEYS}
    ok = all(e <= G7_TOLERANCE for e in errors.values())
    worst = max(errors, key=errors.get)
    mdot_note = _rel(perf.mdot, RAPTOR_2_SEA_LEVEL["mdot"].value)
    return GateResult(
        "G7 Benchmark",
        ok,
        f"largest error {RAPTOR_2_SEA_LEVEL[worst].name} {errors[worst]:.2%}; "
        f"sanity check: flow {perf.mdot:.0f} kg/s vs quoted 650 ({mdot_note:.0%})",
    )


def gate_g0(design: EngineDesign) -> GateResult:
    """The Mars cargo requirement closes with this engine on a Starship-class vehicle."""
    from .mission import MissionAssumptions, Vehicle, mars_mission

    m = MissionAssumptions()
    r = mars_mission(Vehicle(engine=design), m)
    return GateResult(
        "G0 Requirements",
        r.meets_requirement,
        f"{m.mars_cargo_requirement_t:.0f} t to Mars needs {r.propellant_needed_t:.0f} t of propellant in LEO "
        f"({r.tanker_flights} tanker launches); return with {r.return_payload_t:.0f} t needs "
        f"{r.isru_propellant_t:.0f} t made on Mars",
    )


_COMPONENT_GATES = (("G4", "G4 Cooling"), ("G5", "G5 Turbopumps"), ("G6", "G6 Engine system"))


def component_gates(design: EngineDesign) -> list[GateResult]:
    """G4 to G6 from the saved component design point, if it belongs to this engine design."""
    from .components import design_io

    if not design_io.DESIGN_POINT.exists():
        return [GateResult(name, None, "no component design point saved") for _g, name in _COMPONENT_GATES]
    ci = design_io.load()
    if ci.engine != design:
        return [GateResult(name, None, "components designed for the selected design point only") for _g, name in _COMPONENT_GATES]
    from .components.assembly import build_engine
    from .components.verification import all_checks

    b = build_engine(ci)
    checks = all_checks(b)
    out = []
    for g, name in _COMPONENT_GATES:
        mine = [c for c in checks if c.gate == g]
        bad = [c for c in mine if not c.passed]
        detail = f"{len(mine) - len(bad)}/{len(mine)} checks pass"
        if g == "G6":
            detail += f"; dry mass {b.mass:,.0f} kg, sea-level thrust-to-weight {b.thrust_to_weight:.0f}"
        if bad:
            detail += "; failing: " + ", ".join(f"{c.id} {c.description}" for c in bad)
        out.append(GateResult(name, not bad, detail))
    return out


def selected_design() -> EngineDesign:
    """The engine design the components were built for, or the 300 bar reference if none is saved."""
    from .components import design_io

    return design_io.load().engine if design_io.DESIGN_POINT.exists() else EngineDesign()


def run_all_gates(design: EngineDesign | None = None, assumptions: CycleAssumptions | None = None,
                  components: bool = True):
    """All gates for `design`; by default the selected design from the component design point."""
    design = design or selected_design()
    perf = size_engine(design)
    cycle = solve_cycle(perf, assumptions)
    comp = component_gates(design) if components else [
        GateResult(name, None, "component gates skipped") for _g, name in _COMPONENT_GATES
    ]
    results = [gate_g0(design), gate_g1(design), gate_g2(cycle), gate_g3(perf), *comp, gate_g7(perf)]
    return perf, cycle, results
