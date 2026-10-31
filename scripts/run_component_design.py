"""Component design, drawings, BOM and verification for the reference engine.

    python scripts/run_component_design.py            # rebuild from the saved design point
    python scripts/run_component_design.py --iterate  # re-run the iteration from the first guess (about 15-30 min)

Writes everything to results/components/:
  verification.md       component, subsystem and system checks, pressure ladder, iteration log,
                        sensitivity study and vehicle impact
  bom.csv, bom.md       bill of materials with masses and basis (sized or estimated)
  design_data.json      key numbers for every component
  drawings/             SVG and DXF drawings, contour table
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from dataclasses import asdict, replace
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

from raptor_sim.benchmarks import RAPTOR_2_SEA_LEVEL  # noqa: E402
from raptor_sim.components import design_io  # noqa: E402
from raptor_sim.components.assembly import ComponentInputs, build_engine, with_changes  # noqa: E402
from raptor_sim.components.cooling import solve_cooling  # noqa: E402
from raptor_sim.components.drawings import make_all  # noqa: E402
from raptor_sim.components.iterate import iterate  # noqa: E402
from raptor_sim.components.verification import all_checks, delivered_isp, film_flow, pressure_ladder  # noqa: E402
from raptor_sim.cycle import solve_cycle  # noqa: E402
from raptor_sim.mission import MissionAssumptions, Vehicle, mars_mission, vehicle_performance  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / "components"


def fmt(v: float) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    a = abs(v)
    if a == 0:
        return "0"
    if a >= 1000:
        return f"{v:,.0f}"
    if a >= 10:
        return f"{v:.1f}"
    if a >= 1:
        return f"{v:.2f}"
    return f"{v:.3f}"


def write_bom(b, out: Path) -> list[str]:
    with (out / "bom.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["part_number", "name", "assembly", "material", "quantity", "unit_mass_kg", "mass_kg", "basis", "note"])
        for i in b.bom:
            w.writerow([i.part_number, i.name, i.assembly, i.material, i.quantity, f"{i.unit_mass:.3f}", f"{i.mass:.2f}", i.basis, i.note])
    md = ["# Bill of materials: Raptor-class engine, reference design point", "",
          f"Total dry mass **{b.mass:,.0f} kg** (Raptor 2 public figure about 1,630 kg, low confidence). "
          f"Sea-level thrust-to-weight {b.thrust_to_weight:.0f}.", "",
          "Basis: *sized* means the mass comes from geometry the models computed; *estimate* means a scaling "
          "rule or an allowance. Turbopump masses carry about +-50% uncertainty.", ""]
    by_asm: dict[str, list] = {}
    for i in b.bom:
        by_asm.setdefault(i.assembly, []).append(i)
    md += ["| Assembly | Mass (kg) | Share |", "| --- | ---: | ---: |"]
    for asm, items in by_asm.items():
        m = sum(i.mass for i in items)
        md.append(f"| {asm} | {m:,.1f} | {m / b.mass:.0%} |")
    md += ["", "| Part | Name | Material | Qty | Unit mass (kg) | Mass (kg) | Basis | Note |",
           "| --- | --- | --- | ---: | ---: | ---: | --- | --- |"]
    for i in b.bom:
        md.append(f"| {i.part_number} | {i.name} | {i.material} | {i.quantity} | {i.unit_mass:.2f} | {i.mass:.1f} | {i.basis} | {i.note} |")
    (out / "bom.md").write_text("\n".join(md) + "\n")
    return md


def sensitivity(b) -> list[dict]:
    """One-at-a-time changes to the least certain inputs, holding the design fixed."""
    rows = []
    perf, contour, ci = b.perf, b.contour, b.inputs
    base_kw = dict(coolant_flow=b.cooling.coolant_flow, coolant_inlet_pressure=b.cooling.coolant_inlet_pressure,
                   coolant_inlet_temperature=b.cooling.coolant_inlet_temperature)
    from raptor_sim.components.materials import MATERIALS

    def cool_row(label, **kw):
        hg = kw.pop("hg_scale", 1.0)
        cool_in = replace(ci.cooling, **kw.pop("cooling", {}))
        args = dict(base_kw) | kw
        r = solve_cooling(perf, contour, cool_in, hg_scale=hg, **args)
        worst = r.max_wall_station
        limit = 0.95 * MATERIALS[worst.material].max_service_temperature
        rows.append({"case": label, "result": f"hot wall {worst.t_wall_gas:.0f} K ({worst.material}, limit {limit:.0f} K); "
                     f"jacket drop {r.pressure_drop / 1e5:.0f} bar (budget {ci.cycle.dp_cooling * perf.design.pc / 1e5:.0f})",
                     "ok": worst.t_wall_gas <= limit and r.pressure_drop <= ci.cycle.dp_cooling * perf.design.pc})

    cool_row("Design point")
    cool_row("Gas-side heat transfer +20% (Bartz uncertainty)", hg_scale=1.2)
    cool_row("Gas-side heat transfer -20%", hg_scale=0.8)
    cool_row("Channel roughness x2", cooling={"roughness": 2 * ci.cooling.roughness})
    cool_row("Film cooling 50% less effective", cooling={"film_cooling_factor": 1 - 0.5 * (1 - ci.cooling.film_cooling_factor)})
    cool_row("Coolant inlet 20 K warmer", coolant_inlet_temperature=base_kw["coolant_inlet_temperature"] + 20)

    a = ci.cycle
    for label, change in (
        ("All turbomachinery efficiencies -0.03", dict(eta_pump_fuel=a.eta_pump_fuel - 0.03, eta_pump_ox=a.eta_pump_ox - 0.03,
                                                      eta_turbine_fuel=a.eta_turbine_fuel - 0.03, eta_turbine_ox=a.eta_turbine_ox - 0.03)),
        ("Oxygen-rich preburner 25 K cooler", dict(t_ox_rich_pb=a.t_ox_rich_pb - 25)),
        ("Line and duct losses +50%", dict(dp_liquid_lines=1.5 * a.dp_liquid_lines, dp_hot_gas_ducts=1.5 * a.dp_hot_gas_ducts)),
    ):
        c = solve_cycle(perf, replace(a, **change))
        if c.closed:
            res = (f"closes; fuel preburner {c.fuel_shaft.preburner_pressure / 1e5:.0f} bar, oxygen preburner "
                   f"{c.ox_shaft.preburner_pressure / 1e5:.0f} bar; highest pump discharge "
                   f"{max(c.fuel_shaft.pump_discharge_pressure, c.ox_shaft.pump_discharge_pressure) / 1e5:.0f} bar")
            ok = max(c.fuel_shaft.pump_discharge_pressure, c.ox_shaft.pump_discharge_pressure) <= a.p_pump_discharge_max
        else:
            res, ok = f"does not close ({c.message})", False
        rows.append({"case": label, "result": res, "ok": ok})
    return rows


def vehicle_impact(b) -> dict:
    """Carry the modelled engine mass into the Starship-class vehicle and re-run the Mars check."""
    ref = RAPTOR_2_SEA_LEVEL["mass"].value
    dm = (b.mass - ref) / 1000.0  # t per engine
    v0 = Vehicle()
    v1 = replace(v0, booster_dry_t=v0.booster_dry_t + v0.booster_engines * dm,
                 ship_dry_t=v0.ship_dry_t + (v0.ship_sl_engines + v0.ship_vac_engines) * dm)
    m = MissionAssumptions()
    out = {}
    for name, v in (("public engine mass", v0), ("modelled engine mass", v1)):
        p = vehicle_performance(v, m)
        r = mars_mission(v, m)
        out[name] = {"booster_dry_t": v.booster_dry_t, "ship_dry_t": v.ship_dry_t, "payload_to_leo_t": p.payload_to_leo_t,
                     "propellant_in_leo_t": r.propellant_needed_t, "tankers": r.tanker_flights,
                     "isru_t": r.isru_propellant_t, "meets": r.meets_requirement}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterate", action="store_true", help="re-run the design iteration from the first guess")
    ap.add_argument("--trials", type=int, default=200)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    history = None
    if args.iterate:
        b, history, _checks = iterate(ComponentInputs(), cooling_trials=args.trials, log=lambda s: print(s, flush=True))
        design_io.save(b.inputs)
        (OUT / "iteration_log.json").write_text(json.dumps([asdict(h) for h in history], indent=2) + "\n")
    ci = design_io.load()
    b = build_engine(ci)
    checks = all_checks(b)
    if history is None and (OUT / "iteration_log.json").exists():
        history = json.loads((OUT / "iteration_log.json").read_text())
    elif history is not None:
        history = [asdict(h) for h in history]

    drawings = make_all(b, OUT / "drawings")
    write_bom(b, OUT)
    sens = sensitivity(b)
    veh = vehicle_impact(b)
    isp_sl, isp_vac = delivered_isp(b)

    data = {
        "performance": {**b.perf.summary(), "isp_sl_after_film_s": isp_sl, "isp_vac_after_film_s": isp_vac,
                        "film_flow_kg_s": film_flow(b)},
        "chamber": b.contour.summary(),
        "cooling": b.cooling.summary(),
        "injector": {k: v for k, v in asdict(b.injector).items() if k not in ("rings", "inputs")} | {"elements": b.injector.placed_elements},
        "fuel_turbopump": {"pump": asdict(b.fuel_tp.pump), "turbine": asdict(b.fuel_tp.turbine), "mass_kg": b.fuel_tp.mass,
                           "shaft_diameter_m": b.fuel_tp.shaft_diameter, "kick_stage_diameter_m": b.fuel_tp.kick_stage_diameter},
        "ox_turbopump": {"pump": asdict(b.ox_tp.pump), "turbine": asdict(b.ox_tp.turbine), "mass_kg": b.ox_tp.mass,
                         "shaft_diameter_m": b.ox_tp.shaft_diameter, "kick_stage_diameter_m": b.ox_tp.kick_stage_diameter},
        "preburners": [asdict(b.fuel_pb), asdict(b.ox_pb)],
        "lines": [asdict(ln) for ln in b.lines],
        "valves": [asdict(v) for v in b.valves],
        "mass_kg": b.mass,
        "thrust_to_weight": b.thrust_to_weight,
        "cycle": {"fuel_shaft": asdict(b.cycle.fuel_shaft), "ox_shaft": asdict(b.cycle.ox_shaft)},
    }
    (OUT / "design_data.json").write_text(json.dumps(data, indent=2, default=float) + "\n")

    # ---- verification report -------------------------------------------------------
    n_pass = sum(c.passed for c in checks)
    L = ["# Component design verification report", "",
         "Reference engine: Raptor 2 class, 300 bar, mixture ratio 3.6, area ratio 34.3, 2,256 kN at sea level.",
         f"Generated by `scripts/run_component_design.py` from `src/raptor_sim/components/design_point.json`.", "",
         f"**{n_pass} of {len(checks)} checks pass.** Engine dry mass {b.mass:,.0f} kg, sea-level thrust-to-weight "
         f"{b.thrust_to_weight:.0f}, sea-level Isp after film-cooling loss {isp_sl:.1f} s.", ""]
    failed = [c for c in checks if not c.passed]
    if failed:
        L += ["## Open issues (checks that still fail)", ""]
        for c in failed:
            L.append(f"- **{c.id} {c.component}: {c.description}**: {fmt(c.value)} vs limit {fmt(c.limit)} {c.unit}. {c.basis}")
        L.append("")
    gates = {}
    for c in checks:
        if c.gate:
            gates.setdefault(c.gate, []).append(c)
    L += ["## Gate summary", "", "| Gate | Checks | Passed |", "| --- | ---: | ---: |"]
    for g in sorted(gates):
        L.append(f"| {g} | {len(gates[g])} | {sum(c.passed for c in gates[g])} |")
    for level, title in (("component", "Component checks"), ("subsystem", "Subsystem validation"), ("system", "Whole-engine validation")):
        L += ["", f"## {title}", "", "| ID | Component | Check | Value | Limit | Unit | Result | Gate | Basis |",
              "| --- | --- | --- | ---: | ---: | --- | --- | --- | --- |"]
        for c in checks:
            if c.level == level:
                L.append(f"| {c.id} | {c.component} | {c.description} | {fmt(c.value)} | {fmt(c.limit)} | {c.unit} | "
                         f"{'PASS' if c.passed else '**FAIL**'} | {c.gate} | {c.basis} |")
    L += ["", "## Pressure ladder", "", "Supply pressure minus line, valve and jacket losses, against what each consumer needs.", "",
          "| Path | Supply (bar) | Losses (bar) | Delivered (bar) | Required (bar) | Margin (bar) |",
          "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for r in pressure_ladder(b):
        L.append(f"| {r['path']} | {r['supply_bar']:.0f} | {r['losses_bar']:.1f} | {r['delivered_bar']:.0f} | "
                 f"{r['required_bar']:.0f} | {r['margin_bar']:.1f} |")
    L += ["", "## Sensitivity of the converged design", "",
          "One input changed at a time, design held fixed. A failing row means that uncertainty alone could break the design.", "",
          "| Case | Result | Within limits |", "| --- | --- | --- |"]
    for r in sens:
        L.append(f"| {r['case']} | {r['result']} | {'yes' if r['ok'] else '**no**'} |")
    pub, mod = veh["public engine mass"], veh["modelled engine mass"]
    L += ["", "## Vehicle impact", "",
          f"The modelled engine is {b.mass - RAPTOR_2_SEA_LEVEL['mass'].value:+,.0f} kg per engine against the public figure. "
          "Carried into the Starship-class vehicle (33 booster engines, 6 ship engines):", "",
          "| Quantity | Public engine mass | Modelled engine mass |", "| --- | ---: | ---: |",
          f"| Booster dry mass (t) | {pub['booster_dry_t']:.0f} | {mod['booster_dry_t']:.0f} |",
          f"| Ship dry mass (t) | {pub['ship_dry_t']:.0f} | {mod['ship_dry_t']:.0f} |",
          f"| Payload to LEO (t) | {pub['payload_to_leo_t']:.0f} | {mod['payload_to_leo_t']:.0f} |",
          f"| Propellant in LEO for 100 t to Mars (t) | {pub['propellant_in_leo_t']:.0f} | {mod['propellant_in_leo_t']:.0f} |",
          f"| Tanker launches | {pub['tankers']} | {mod['tankers']} |",
          f"| Propellant made on Mars for return (t) | {pub['isru_t']:.0f} | {mod['isru_t']:.0f} |",
          f"| G0 Mars requirement met | {'yes' if pub['meets'] else 'no'} | {'yes' if mod['meets'] else 'no'} |"]
    if history:
        L += ["", "## Iteration log", "",
              "Each pass builds every component, runs every check, and applies one fix per failing check (rules in "
              "`src/raptor_sim/components/iterate.py`).", ""]
        for h in history:
            L.append(f"### Pass {h['iteration']}: {len(h['failures'])} failing checks, mass {h['mass']:,.0f} kg")
            L.append("")
            if h["failures"]:
                L.append("Failing: " + "; ".join(h["failures"]))
                L.append("")
            for a in h["actions"]:
                L.append(f"- {a}")
            if not h["actions"]:
                L.append("- no automatic fix applies; remaining failures need a decision")
            L.append("")
    L += ["", "## Drawings", ""] + [f"- `drawings/{p.name}`" for p in drawings]
    (OUT / "verification.md").write_text("\n".join(L) + "\n")
    print(f"{n_pass}/{len(checks)} checks pass; mass {b.mass:.0f} kg; T/W {b.thrust_to_weight:.0f}")
    for c in failed:
        print(f"FAIL {c.id}: {c.description} {fmt(c.value)} vs {fmt(c.limit)}")


if __name__ == "__main__":
    main()
