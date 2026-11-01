"""Build the master roadmap: schedule, Monte Carlo risk, options, logistics -> results/roadmap/.

    python scripts/run_roadmap.py            # 5,000 runs, about a minute
    python scripts/run_roadmap.py --runs 500 # quick look
"""
from __future__ import annotations

import argparse
from pathlib import Path

from raptor_sim.roadmap.report import run

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "results" / "roadmap")
    args = ap.parse_args()
    run(args.out, n=args.runs, seed=args.seed)
    print((args.out / "summary.md").read_text())
