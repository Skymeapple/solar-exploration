"""Run the end-to-end Mars sample return simulation: python -m sample_return [--runs N] [--out DIR]"""

import argparse

from .campaign import run_campaign
from .report import write


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=int, default=300, help="Monte Carlo runs for ascent and entry")
    p.add_argument("--out", default="results/sample_return", help="output directory")
    a = p.parse_args()
    o = run_campaign(mc_runs=a.runs)
    for g in o["gates"]:
        print(f"{g.id:<5} {g.phase:<24} {'PASS' if g.passed else 'FAIL':<5} {g.detail}")
    md, js = write(o, a.out)
    print(f"\nwrote {md} and {js}")


if __name__ == "__main__":
    main()
