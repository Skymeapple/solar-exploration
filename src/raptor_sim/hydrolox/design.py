"""Design iteration for the project's two hydrogen/oxygen engines.

HL-44  lunar lander engine, BE-7 class (44 kN vacuum), closed expander.
       Used by the crewed lunar study's hydrogen lander (raptor_sim.crewed_lunar).
HL-250 lunar tanker / shuttle engine (250 kN vacuum). Both cycles are tried;
       used by the lunar base study's all-lunar tankers (raptor_sim.lunar_base.depot).

An Optuna TPE sampler (the same optimizer as the methane engine, raptor_sim.optimize)
moves chamber pressure, mixture ratio and area ratio. Every trial runs the cycle
balance and the packaging limit and is logged with its reason for failing.
Objective: vacuum Isp. Mixture ratio is held between 5 and 6.5, the range the
lunar ice plant (raptor_sim.lunar_base.isru) and the crewed lunar study assume.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from functools import lru_cache

from . import cycles
from .benchmarks import RL10B_2, RL10C_1, RS_25
from .engine import design, expander_isp_bias, size

MR_BOUNDS = (5.0, 6.5)
EXPANDER_HEAT_MARGIN = 0.15  # engine must still close with 15% less wall heat than predicted [est]


@dataclass(frozen=True)
class EngineSpec:
    name: str
    thrust_vac: float  # N
    cycle: str  # "expander" or "staged"
    max_exit_diameter: float  # m
    pc_bounds: tuple[float, float]  # bar
    eps_bounds: tuple[float, float]
    use: str


HL_44 = EngineSpec("HL-44", 44e3, "expander", 1.0, (20.0, 80.0), (40.0, 250.0),
                   "crewed lunar hydrogen lander (9 engines), raptor_sim.crewed_lunar")
HL_250_EXP = EngineSpec("HL-250 (expander)", 250e3, "expander", 2.0, (20.0, 60.0), (30.0, 120.0),
                        "lunar hydrogen tanker / shuttle, raptor_sim.lunar_base.depot")
HL_250_SC = EngineSpec("HL-250 (staged combustion)", 250e3, "staged", 2.0, (60.0, 220.0), (40.0, 150.0),
                       "alternative for the lunar tanker")
SPECS = (HL_44, HL_250_EXP, HL_250_SC)


@dataclass
class HTrial:
    number: int
    pc_bar: float
    mixture_ratio: float
    eps: float
    feasible: bool = False
    reason: str = ""
    isp_vac: float = math.nan
    exit_diameter: float = math.nan
    power_margin: float = math.nan  # expander only: heat-load margin (cycles.heat_margin)
    pump_discharge_bar: float = math.nan
    turbine_inlet_K: float = math.nan


def thrust_to_weight(spec: EngineSpec) -> float:
    """Engine thrust-to-weight [est], from the closest published engine of the same cycle."""
    ref = RL10C_1 if spec.cycle == "expander" else RS_25
    return ref.thrust_vac / (ref.mass * 9.80665)


@lru_cache(maxsize=1)
def expander_assumptions() -> cycles.ExpanderAssumptions:
    from .engine import reference_design

    return cycles.calibrate(size(reference_design(RL10B_2)))


def evaluate(spec: EngineSpec, pc_bar: float, mr: float, eps: float, number: int = 0) -> HTrial:
    t = HTrial(number, pc_bar, mr, eps)
    perf = size(design(pc_bar * 1e5, mr, eps, spec.thrust_vac))
    t.isp_vac, t.exit_diameter = perf.isp_vac, perf.exit_diameter
    if perf.exit_diameter > spec.max_exit_diameter:
        t.reason = f"exit diameter {perf.exit_diameter:.2f} m over {spec.max_exit_diameter} m"
        return t
    if spec.cycle == "expander":
        r = cycles.solve_expander(perf, expander_assumptions())
        t.pump_discharge_bar, t.turbine_inlet_K = r.h2_pump_discharge / 1e5, r.t_turbine_inlet
        if not r.closed:
            t.reason = r.message
            return t
        t.power_margin = cycles.heat_margin(perf, expander_assumptions())
        if t.power_margin < EXPANDER_HEAT_MARGIN:
            t.reason = f"heat margin {t.power_margin:.0%} under {EXPANDER_HEAT_MARGIN:.0%}"
            return t
    else:
        r = cycles.solve_staged(perf)
        t.pump_discharge_bar = r.h2_pump_discharge / 1e5
        if not r.closed:
            t.reason = r.message
            return t
    t.feasible = True
    return t


def optimise(spec: EngineSpec, n_trials: int = 60, seed: int = 7) -> tuple[HTrial, list[HTrial]]:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    log: list[HTrial] = []

    def objective(trial: "optuna.Trial") -> float:
        t = evaluate(
            spec,
            trial.suggest_float("pc_bar", *spec.pc_bounds),
            trial.suggest_float("mixture_ratio", *MR_BOUNDS),
            trial.suggest_float("eps", *spec.eps_bounds),
            trial.number,
        )
        log.append(t)
        return t.isp_vac if t.feasible else t.isp_vac - 100.0

    study = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(seed=seed))
    # Seed with a conservative corner (low pressure, short nozzle) so the search starts from a feasible design.
    study.enqueue_trial({"pc_bar": spec.pc_bounds[0] * 1.25, "mixture_ratio": 6.0, "eps": spec.eps_bounds[0] * 1.25})
    study.optimize(objective, n_trials=n_trials)
    feasible = [t for t in log if t.feasible]
    if not feasible:
        raise RuntimeError(f"{spec.name}: no feasible design in {n_trials} trials")
    return max(feasible, key=lambda t: t.isp_vac), log


def expander_wall(thrust_vac: float, mr: float, eps: float, lo_bar: float = 10.0, hi_bar: float = 150.0) -> float:
    """Highest chamber pressure (bar) at which a closed expander still balances, with no margin."""
    a = expander_assumptions()

    def closes(pc_bar: float) -> bool:
        return cycles.solve_expander(size(design(pc_bar * 1e5, mr, eps, thrust_vac)), a).closed

    if not closes(lo_bar):
        return lo_bar
    if closes(hi_bar):
        return hi_bar
    for _ in range(18):
        mid = 0.5 * (lo_bar + hi_bar)
        lo_bar, hi_bar = (mid, hi_bar) if closes(mid) else (lo_bar, mid)
    return lo_bar


def summary(spec: EngineSpec, best: HTrial) -> dict:
    perf = size(design(best.pc_bar * 1e5, best.mixture_ratio, best.eps, spec.thrust_vac))
    twr = thrust_to_weight(spec)
    return {
        "name": spec.name,
        "cycle": spec.cycle,
        "use": spec.use,
        "thrust_vac_kN": spec.thrust_vac / 1e3,
        "chamber_pressure_bar": best.pc_bar,
        "mixture_ratio": best.mixture_ratio,
        "area_ratio": best.eps,
        "isp_vac_s": perf.isp_vac,
        # Value for mission studies: expander Isp corrected by the mean bias seen on flown expanders.
        "isp_vac_for_studies_s": perf.isp_vac / (1 + expander_isp_bias()) if spec.cycle == "expander" else perf.isp_vac,
        "exit_diameter_m": perf.exit_diameter,
        "throat_diameter_m": perf.throat_diameter,
        "mdot_kg_s": perf.mdot,
        "mass_kg_est": spec.thrust_vac / (twr * 9.80665),
        "thrust_to_weight_est": twr,
        "trial": asdict(best),
    }
