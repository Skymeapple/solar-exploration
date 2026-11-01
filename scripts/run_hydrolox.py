"""Run the hydrogen/oxygen engine design iteration and verification gates.

    python scripts/run_hydrolox.py      # writes results/hydrolox/
"""

from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from raptor_sim.hydrolox.engine import eta_cf, ETA_CSTAR  # noqa: E402
from raptor_sim.hydrolox.design import expander_assumptions  # noqa: E402
from raptor_sim.hydrolox.gates import run_all  # noqa: E402

OUT = ROOT / "results" / "hydrolox"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rep = run_all()
    a = expander_assumptions()
    data = {
        "calibration": {"eta_cstar": ETA_CSTAR, "eta_cf": eta_cf(), "expander_heat_factor": a.heat_factor},
        "design_points": rep.points,
        "gates": [asdict(g) for g in rep.gates],
    }
    (OUT / "design_points.json").write_text(json.dumps(data, indent=2))
    with (OUT / "iteration_log.csv").open("w", newline="") as f:
        rows = [dict(engine=name, **asdict(t)) for name, log in rep.logs.items() for t in log]
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    lines = ["# Hydrogen/oxygen engine model: design points and verification", ""]
    lines += [f"Calibration: eta_cstar {ETA_CSTAR}, eta_cf {eta_cf():.4f} (fitted to RS-25 vacuum Isp only); "
              f"expander heat factor {a.heat_factor:.3f} on Bartz (fitted so RL10B-2 hydrogen leaves the jacket at 220 K).", ""]
    lines += ["## Gates", "", "| Gate | Result | Detail |", "| --- | --- | --- |"]
    for g in rep.gates:
        res = "NOT RUN" if g.passed is None else ("PASS" if g.passed else "FAIL")
        lines.append(f"| {g.gate} | {res} | {g.detail} |")
    lines += ["", "## Design points", "", "| Engine | Cycle | Thrust vac (kN) | Pc (bar) | MR | Area ratio | Isp vac (s) | Isp for studies (s) | Exit D (m) | Mass est (kg) | Use |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in rep.points.values():
        lines.append(f"| {s['name']} | {s['cycle']} | {s['thrust_vac_kN']:.0f} | {s['chamber_pressure_bar']:.1f} | {s['mixture_ratio']:.2f} | "
                     f"{s['area_ratio']:.0f} | {s['isp_vac_s']:.1f} | {s['isp_vac_for_studies_s']:.1f} | {s['exit_diameter_m']:.2f} | {s['mass_kg_est']:.0f} | {s['use']} |")
    lines += ["", "Isp for studies removes the mean +"
              f"{__import__('raptor_sim.hydrolox.engine', fromlist=['x']).expander_isp_bias():.1%} over-prediction the model shows on flown expander engines (H3).",
              "Lunar studies read these values from `raptor_sim.hydrolox.study_isp()`."]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0 if all(g.passed is not False for g in rep.gates) else 1


if __name__ == "__main__":
    raise SystemExit(main())
