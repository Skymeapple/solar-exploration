"""Verification gates for the hydrogen/oxygen engine model (H-series, mirrors G1-G7).

H1 Thermochemistry  CEA and Cantera agree on chamber T and MW within 1% (RS-25, RL10B-2 points)
H2 Cycle balance    RS-25 staged combustion: predicted fuel pump discharge within 10% of 45 MPa;
                    RL10 engines close at their published chamber pressure;
                    predicted Vinci expander wall within 10% of its 60 bar
H3 Performance      vacuum Isp within 3% for every reference engine except the RS-25 vacuum
                    figure (the single calibration point); RS-25 sea-level Isp within 3%
H4 Design margins   each design point closes with at least 15% less wall heat (expanders),
                    turbine inlet below its limit, nozzle inside its packaging limit
H5 Turbopumps       not modelled at component level (methane only, PR #2); reported as not run
H6 Engine mass      estimate from the thrust-to-weight of the nearest flown engine; not a check
H7 Benchmark        each design point's Isp within 5% of the nearest flown engine of its class
"""

from __future__ import annotations

from dataclasses import dataclass

from ..gates import GateResult, _rel
from . import cycles, design, thermo
from .benchmarks import ALL, BE_7_ISP_VAC, H3_ISP_TOLERANCE, H7_TOLERANCE, RL10B_2, RS_25, RS_25_HPFTP_DISCHARGE, VINCI
from .engine import reference_design, sea_level_isp, size


def gate_h1() -> GateResult:
    worst, parts = 0.0, []
    for ref in (RS_25, RL10B_2):
        cea = thermo.chamber(ref.pc, ref.mixture_ratio)
        t_ct, mw_ct = thermo.cantera_chamber(ref.pc, ref.mixture_ratio)
        dt, dmw = _rel(t_ct, cea.temperature), _rel(mw_ct, cea.molecular_weight)
        worst = max(worst, dt, dmw)
        parts.append(f"{ref.name}: Tc {cea.temperature:.0f} vs {t_ct:.0f} K ({dt:.2%}), MW {dmw:.2%}")
    return GateResult("H1 Thermochemistry", worst <= 0.01, "; ".join(parts))


def gate_h2() -> GateResult:
    problems, parts = [], []
    sc = cycles.solve_staged(size(reference_design(RS_25)))
    d_sc = _rel(sc.h2_pump_discharge, RS_25_HPFTP_DISCHARGE) if sc.closed else 1.0
    parts.append(
        f"RS-25 fuel pump discharge {sc.h2_pump_discharge / 1e6:.1f} MPa vs 45.0 ({d_sc:.1%}), "
        f"preburner {sc.preburner_pressure / 1e5:.0f} bar, pumps {sc.pump_power / 1e6:.0f} MW"
    )
    if not sc.closed or d_sc > 0.10:
        problems.append("RS-25 pump discharge")
    a = design.expander_assumptions()
    for ref in ALL:
        if ref.cycle != "expander" or ref is VINCI:
            continue
        r = cycles.solve_expander(size(reference_design(ref)), a)
        parts.append(f"{ref.name} closes {r.closed} (turbine {r.t_turbine_inlet:.0f} K, PR {r.turbine_pressure_ratio:.2f})")
        if not r.closed:
            problems.append(f"{ref.name} does not close")
    wall = design.expander_wall(VINCI.thrust_vac, VINCI.mixture_ratio, VINCI.eps)
    d_w = _rel(wall, VINCI.pc / 1e5)
    parts.append(f"Vinci expander wall {wall:.1f} bar vs flown 60 bar ({d_w:.1%})")
    if d_w > 0.10:
        problems.append("Vinci wall")
    return GateResult("H2 Cycle balance", not problems, "; ".join(parts) + (" | " + ", ".join(problems) if problems else ""))


def gate_h3() -> GateResult:
    worst, parts = 0.0, []
    for ref in ALL:
        p = size(reference_design(ref))
        if ref is not RS_25:
            e = _rel(p.isp_vac, ref.isp_vac)
            worst = max(worst, e)
            parts.append(f"{ref.name} {p.isp_vac:.1f} vs {ref.isp_vac} s ({e:+.1%})".replace("+", ""))
        else:
            e = _rel(sea_level_isp(p), ref.isp_sl)
            worst = max(worst, e)
            parts.append(f"RS-25 sea level {sea_level_isp(p):.1f} vs {ref.isp_sl} s ({e:.1%}); vacuum is the calibration point")
    return GateResult("H3 Performance", worst <= H3_ISP_TOLERANCE, "; ".join(parts))


def gate_h4(points: dict[str, dict]) -> GateResult:
    problems, parts = [], []
    for name, s in points.items():
        t = s["trial"]
        spec = next(sp for sp in design.SPECS if sp.name == name)
        if spec.cycle == "expander":
            parts.append(f"{name} heat margin {t['power_margin']:.0%}, turbine {t['turbine_inlet_K']:.0f} K")
            if t["power_margin"] < design.EXPANDER_HEAT_MARGIN:
                problems.append(name)
        else:
            parts.append(f"{name} fuel pump {t['pump_discharge_bar']:.0f} bar")
        if s["exit_diameter_m"] > spec.max_exit_diameter:
            problems.append(f"{name} nozzle")
    return GateResult("H4 Design margins", not problems, "; ".join(parts))


def gate_h7(points: dict[str, dict]) -> GateResult:
    parts, worst = [], 0.0
    refs = {"expander": [("BE-7", BE_7_ISP_VAC), ("Vinci", VINCI.isp_vac), ("RL10B-2", RL10B_2.isp_vac)], "staged": [("RS-25", RS_25.isp_vac)]}
    for name, s in points.items():
        ref_name, ref_isp = refs[s["cycle"]][0] if s["thrust_vac_kN"] < 100 else refs[s["cycle"]][-1 if s["cycle"] == "staged" else 1]
        e = _rel(s["isp_vac_s"], ref_isp)
        worst = max(worst, e)
        parts.append(f"{name} {s['isp_vac_s']:.1f} s vs {ref_name} {ref_isp} s ({e:.1%})")
    return GateResult("H7 Benchmark", worst <= H7_TOLERANCE, "; ".join(parts))


@dataclass
class HydroloxReport:
    gates: list[GateResult]
    points: dict[str, dict]
    logs: dict[str, list]


def run_all(n_trials: int = 80) -> HydroloxReport:
    points, logs = {}, {}
    for spec in design.SPECS:
        best, log = design.optimise(spec, n_trials=n_trials)
        points[spec.name] = design.summary(spec, best)
        logs[spec.name] = log
    gates = [
        gate_h1(),
        gate_h2(),
        gate_h3(),
        gate_h4(points),
        GateResult("H5 Turbopumps", None, "component-level pump model exists for methane only (PR #2); not run"),
        GateResult("H6 Engine mass", None, "estimate only: thrust-to-weight of RL10C-1 (expander) or RS-25 (staged)"),
        gate_h7(points),
    ]
    return HydroloxReport(gates, points, logs)
