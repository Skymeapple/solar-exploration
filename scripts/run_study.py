"""Run the full study: gates on the reference engine, the optimizer, and the Mars check.

    python scripts/run_study.py [--trials 300]

Writes results/optimizer_log.csv (every design tried) and results/summary.md.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
from pathlib import Path

from raptor_sim import CycleAssumptions, run_all_gates
from raptor_sim.benchmarks import RAPTOR_VACUUM, STARSHIP_BLOCK_3
from raptor_sim.mission import MissionAssumptions, Vehicle, mars_mission, vehicle_performance
from raptor_sim.optimize import best_design, confirm_best, evaluate, optimize

RESULTS = Path(__file__).resolve().parent.parent / "results"


def status(passed):
    return "not run" if passed is None else ("PASS" if passed else "FAIL")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    lines = ["# Study summary", ""]

    # Reference engine and its gates
    _perf, _cycle, gates = run_all_gates()
    lines += ["## Reference engine gates (Raptor 2 class)", "", "| Gate | Result | Detail |", "| --- | --- | --- |"]
    lines += [f"| {g.gate} | {status(g.passed)} | {g.detail} |" for g in gates]

    # Step 3: optimizer
    ref_params = {"pc_bar": 300.0, "mixture_ratio": 3.6, "eps": 34.34, "t_ox_rich_pb": 800.0, "t_fuel_rich_pb": 1000.0}
    ref = evaluate(ref_params)
    best, trials = optimize(args.trials, seed=args.seed, log_path=RESULTS / "optimizer_log.csv")
    g1 = confirm_best(best)
    reasons = Counter(r for t in trials if not t.feasible for r in t.reason.split("; "))
    lines += [
        "",
        f"## Optimizer ({len(trials)} designs, {sum(t.feasible for t in trials)} passed every gate)",
        "",
        "| Quantity | Reference | Best found |",
        "| --- | --- | --- |",
        f"| Chamber pressure (bar) | {ref.pc_bar:.0f} | {best.pc_bar:.0f} |",
        f"| Mixture ratio | {ref.mixture_ratio:.2f} | {best.mixture_ratio:.2f} |",
        f"| Area ratio | {ref.eps:.1f} | {best.eps:.1f} |",
        f"| Oxygen-rich turbine inlet (K) | {ref.t_ox_rich_pb:.0f} | {best.t_ox_rich_pb:.0f} |",
        f"| Fuel-rich turbine inlet (K) | {ref.t_fuel_rich_pb:.0f} | {best.t_fuel_rich_pb:.0f} |",
        f"| Sea-level Isp (s) | {ref.isp_sl:.1f} | {best.isp_sl:.1f} |",
        f"| Vacuum Isp (s) | {ref.isp_vac:.1f} | {best.isp_vac:.1f} |",
        f"| Nozzle exit diameter (m) | {ref.exit_diameter:.2f} | {best.exit_diameter:.2f} |",
        f"| Oxygen pump discharge (bar) | {ref.ox_pump_discharge_bar:.0f} | {best.ox_pump_discharge_bar:.0f} |",
        "",
        f"Winner re-checked with independent chemistry: {g1.gate} {status(g1.passed)} ({g1.detail}).",
        "",
        "Why designs failed:",
        "",
    ]
    lines += [f"- {r}: {n}" for r, n in reasons.most_common()]

    # Step 4: vehicle and Mars
    m = MissionAssumptions()
    rows = []
    for name, engine in (("Reference engine", Vehicle().engine), ("Optimized engine", best_design(best))):
        v = Vehicle(engine=engine)
        vp = vehicle_performance(v, m)
        mr = mars_mission(v, m)
        rows.append((name, vp, mr))
    lines += [
        "",
        "## Vehicle and Mars mission",
        "",
        "| Quantity | " + " | ".join(r[0] for r in rows) + " |",
        "| --- | " + " | ".join("---" for _ in rows) + " |",
        "| Payload to LEO, reusable (t) | " + " | ".join(f"{r[1].payload_to_leo_t:.0f}" for r in rows) + " |",
        "| Liftoff thrust-to-weight | " + " | ".join(f"{r[1].liftoff_thrust_to_weight:.2f}" for r in rows) + " |",
        "| Vacuum engine Isp (s) | " + " | ".join(f"{r[1].rvac_isp:.1f}" for r in rows) + " |",
        "| Trans-Mars injection from LEO (m/s) | " + " | ".join(f"{r[2].tmi_dv:.0f}" for r in rows) + " |",
        "| Transfer time, minimum energy (days) | " + " | ".join(f"{r[2].transfer_days:.0f}" for r in rows) + " |",
        f"| Propellant in LEO to land {m.mars_cargo_requirement_t:.0f} t on Mars (t) | " + " | ".join(f"{r[2].propellant_needed_t:.0f}" for r in rows) + " |",
        "| Tanker launches needed | " + " | ".join(f"{r[2].tanker_flights}" for r in rows) + " |",
        "| Mars surface to Earth transfer (m/s) | " + " | ".join(f"{r[2].return_dv:.0f}" for r in rows) + " |",
        "| Propellant made on Mars for return with 20 t (t) | " + " | ".join(f"{r[2].isru_propellant_t:.0f}" for r in rows) + " |",
        "| Mission closes | " + " | ".join("yes" if r[2].meets_requirement else "no" for r in rows) + " |",
    ]

    # Sensitivity: the LEO payload SpaceX states (100 t) versus the model
    lines += ["", "## Sensitivity: ship dry mass", "", "| Ship dry mass (t) | Payload to LEO (t) | Tanker launches |", "| --- | --- | --- |"]
    for dry in (100.0, 125.0, 150.0, 175.0):
        v = Vehicle(ship_dry_t=dry, engine=best_design(best))
        lines.append(
            f"| {dry:.0f} | {vehicle_performance(v, m).payload_to_leo_t:.0f} | {mars_mission(v, m).tanker_flights} |"
        )
    lines += [
        "",
        f"SpaceX states about {STARSHIP_BLOCK_3['payload_to_leo_t'].value:.0f} t to LEO for Block 3. "
        f"Raptor Vacuum is quoted at {RAPTOR_VACUUM['isp_vac'].value:.0f} s.",
    ]

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
