"""Sweep chamber pressure and re-run the full component iteration at each point.

    python scripts/sweep_chamber_pressure.py 300 298 295 290 285 280

Each point starts from the first guess, trims the nozzle area ratio to keep a 1.38 m exit,
and runs `iterate` (about 15 minutes per point). Results go to results/components/pc_sweep.json;
the highest pressure that passes every check becomes the design point via
`run_component_design.py --iterate --pc <bar>`. Run points one at a time: RocketCEA writes a
shared temporary file and parallel runs can crash or corrupt each other.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

from raptor_sim.components.assembly import ComponentInputs  # noqa: E402
from raptor_sim.components.iterate import engine_at_pressure, iterate  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "results" / "components" / "pc_sweep.json"


def main() -> None:
    rows = []
    for pc in map(float, sys.argv[1:] or ["300", "298", "295", "290", "285", "280"]):
        d = engine_at_pressure(pc * 1e5)
        b, history, checks = iterate(ComponentInputs(engine=d), log=lambda s: print(s, flush=True))
        failing = [f"{c.id} {c.description}" for c in checks if not c.passed]
        rows.append({"pc_bar": pc, "area_ratio": round(d.eps, 2), "mass_kg": round(b.mass),
                     "thrust_to_weight": round(b.thrust_to_weight, 1), "passes": not failing,
                     "failing": failing, "iterations": len(history)})
        print(json.dumps(rows[-1]), flush=True)
    OUT.write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
