"""Print the gate report for the selected design point: python -m raptor_sim"""

from .gates import run_all_gates


def main() -> None:
    perf, cycle, results = run_all_gates()
    print(f"Selected design (Raptor 2 class, sea-level nozzle, {perf.design.pc / 1e5:.0f} bar)")
    for key, value in perf.summary().items():
        print(f"  {key:<24} {value:10.3f}")
    print()
    for r in results:
        status = "not run" if r.passed is None else ("PASS" if r.passed else "FAIL")
        print(f"{r.gate:<20} {status:<8} {r.detail}")


if __name__ == "__main__":
    main()
