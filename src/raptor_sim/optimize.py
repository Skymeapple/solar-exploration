"""Step 3: AI-driven design iteration.

An Optuna TPE (Bayesian) sampler proposes designs, every design runs through
the gates that have models (G2 cycle balance, G3 sea-level separation, plus a
packaging limit), and every trial is logged with its inputs, outputs and the
reason it failed. The best feasible design is then re-checked against G1 with
the independent Cantera chemistry.

Objective: the average of sea-level and vacuum Isp, which is what a booster
engine that fires from launch to staging cares about. Thrust is held at the
Raptor 2 value so that designs stay comparable.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .cycle import CycleAssumptions, solve_cycle
from .engine import EngineDesign, size_engine
from .gates import gate_g1

# Packaging: 33 engines sit under a 9 m booster, so the nozzle exit cannot grow
# much past Raptor's roughly 1.3 m. 1.40 m is our assumed limit.
MAX_EXIT_DIAMETER = 1.40  # m

BOUNDS = {
    "pc_bar": (200.0, 400.0),
    "mixture_ratio": (3.0, 4.2),
    "eps": (15.0, 60.0),
    "t_ox_rich_pb": (650.0, 850.0),  # K, capped by the oxidizer turbine limit
    "t_fuel_rich_pb": (800.0, 1100.0),  # K, capped by the fuel turbine limit
}


@dataclass
class Trial:
    number: int
    pc_bar: float
    mixture_ratio: float
    eps: float
    t_ox_rich_pb: float
    t_fuel_rich_pb: float
    feasible: bool = False
    reason: str = ""
    isp_sl: float = math.nan
    isp_vac: float = math.nan
    objective: float = math.nan
    exit_diameter: float = math.nan
    separation_margin: float = math.nan
    ox_pump_discharge_bar: float = math.nan
    fuel_pump_discharge_bar: float = math.nan


def evaluate(
    params: dict[str, float],
    base: EngineDesign | None = None,
    assumptions: CycleAssumptions | None = None,
    number: int = -1,
) -> Trial:
    """Run one design through the gates and return its logged record."""
    base = base or EngineDesign()
    a = assumptions or CycleAssumptions()
    t = Trial(number=number, **params)
    design = replace(base, pc=params["pc_bar"] * 1e5, mixture_ratio=params["mixture_ratio"], eps=params["eps"])
    a = replace(a, t_ox_rich_pb=params["t_ox_rich_pb"], t_fuel_rich_pb=params["t_fuel_rich_pb"])

    try:
        perf = size_engine(design)
    except ValueError as exc:
        t.reason = str(exc)
        return t
    t.isp_sl, t.isp_vac = perf.isp_sl, perf.isp_vac
    t.objective = 0.5 * (perf.isp_sl + perf.isp_vac)
    t.exit_diameter = perf.exit_diameter
    t.separation_margin = perf.separation_margin

    reasons = []
    if perf.separation_margin < 1.0:
        reasons.append("G3 flow separates at sea level")
    if perf.exit_diameter > MAX_EXIT_DIAMETER:
        reasons.append("nozzle too wide to package")
    try:
        cycle = solve_cycle(perf, a)
    except ValueError as exc:  # preburner temperature not reachable
        cycle = None
        reasons.append(f"G2 {exc}")
    if cycle is not None:
        if not cycle.closed:
            reasons.append(f"G2 {cycle.message}")
        else:
            t.ox_pump_discharge_bar = cycle.ox_shaft.pump_discharge_pressure / 1e5
            t.fuel_pump_discharge_bar = cycle.fuel_shaft.pump_discharge_pressure / 1e5
            limit = a.p_pump_discharge_max / 1e5
            if max(t.ox_pump_discharge_bar, t.fuel_pump_discharge_bar) > limit:
                reasons.append("G2 pump discharge over limit")
    t.feasible = not reasons
    t.reason = "; ".join(reasons)
    return t


def optimize(n_trials: int = 300, seed: int = 7, log_path: str | Path | None = None):
    """Search the design space. Returns (best feasible Trial, all trials)."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    trials: list[Trial] = []

    def objective(ot: "optuna.Trial") -> float:
        params = {k: ot.suggest_float(k, lo, hi) for k, (lo, hi) in BOUNDS.items()}
        rec = evaluate(params, number=ot.number)
        trials.append(rec)
        # Optuna treats constraint values > 0 as violated.
        ot.set_constraint("gates", 0.0 if rec.feasible else 1.0)
        return rec.objective if not math.isnan(rec.objective) else 0.0

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials)

    if log_path is not None:
        write_log(trials, log_path)
    feasible = [t for t in trials if t.feasible]
    best = max(feasible, key=lambda t: t.objective) if feasible else None
    return best, trials


def write_log(trials: list[Trial], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(asdict(trials[0]).keys()))
        writer.writeheader()
        for t in trials:
            writer.writerow({k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(t).items()})


def best_design(best: Trial) -> EngineDesign:
    return replace(EngineDesign(), pc=best.pc_bar * 1e5, mixture_ratio=best.mixture_ratio, eps=best.eps)


def confirm_best(best: Trial):
    """Re-check the winner with the independent chemistry (gate G1)."""
    return gate_g1(best_design(best))
