"""Design iteration: find failing checks, apply a fix for each, rebuild, repeat.

Each fix is an engineering decision written as a rule, and every pass is logged
with the failures it saw and what it changed, so the path from the first guess
to the final design can be reviewed.

Fix rules:

* Cooling (CL-1 to CL-6): re-optimize the channel layout with Optuna (TPE with
  constraints). Objective: coolant pressure drop plus a penalty for film
  cooling, which costs Isp. Then the cycle's cooling pressure budget is set to
  the result plus 10%.
* Pressure ladder (SS-1 to SS-6): set the cycle's line and duct loss allowances
  from the sized lines plus 10%; enable the fuel kick stage when the oxygen-rich
  preburner needs more pressure than the fuel pump gives, and an oxidizer kick
  stage when the fuel-rich preburner needs more than the oxidizer pump gives.
* Impeller too large (TP-x2): raise the pump inlet pressure requirement by 1 bar
  (higher NPSH allows a faster, smaller pump). This becomes a vehicle requirement.
* Pump and turbine efficiencies: the cycle's placeholder values (0.75) are
  replaced by the turbopump model's predictions less a 0.03 margin, every pass.
* Preburner wall too hot (PB-x2): give it a propellant-cooled liner; if it is
  still too hot, lower that preburner's temperature by 25 K.
* Injector ligament too thin (IN-3): 10% fewer elements.

G6 (mass) failures and pump discharge pressures above the G2 limit have no
automatic fix. They are reported for a decision. The loop stops when a pass
changes nothing.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace

from .assembly import ComponentInputs, EngineBuild, build_engine, coolant_inlet_temperature, with_changes
from .cooling import CoolingInputs, solve_cooling
from .materials import MATERIALS
from .verification import (
    MAX_CHANNEL_ASPECT,
    MIN_CHANNEL_WIDTH,
    WALL_TEMPERATURE_MARGIN,
    Check,
    all_checks,
    pressure_ladder,
)

FILM_PENALTY_BAR = 400.0  # objective cost of going from no film to film factor 0 (i.e. 40 bar per 0.1)
MAX_COOLING_DP_FRACTION = 1.0  # jacket drop may not exceed this fraction of Pc (keeps the search out of
# the regime where friction exhausts the supply pressure)
SEED_LAYOUT = {
    "film_cooling_factor": 0.5, "n_channels_throat": 360, "hot_wall_thickness": 0.7e-3,
    "copper_nozzle_wall_thickness": 1.8e-3, "nozzle_wall_thickness": 0.5e-3, "rib_width": 1.0e-3,
    "rib_fraction_nozzle": 0.6, "depth_throat": 6.5e-3, "depth_chamber": 9e-3, "depth_exit": 12e-3,
    "max_channel_width": 1.2e-3, "max_channel_width_nozzle": 1.5e-3, "copper_to_area_ratio": 15.0,
}
MAX_PUMP_INLET = 12e5
EFFICIENCY_MARGIN = 0.03
COOLING_STATIONS = 120  # same resolution as the build, so optimizer and checks agree  # Pa, assumed upper limit the vehicle can supply (tank ullage + acceleration head)


@dataclass
class IterationRecord:
    iteration: int
    failures: list[str]
    actions: list[str]
    mass: float
    pressure_drop_bar: float


def _cooling_constraints(res) -> list[float]:
    """Each value <= 0 means satisfied (Optuna convention)."""
    st = res.stations
    out = []
    for key in ("GRCop-42", "IN718"):
        temps = [s.t_wall_gas for s in st if s.material == key]
        if temps:
            out.append(max(temps) / (WALL_TEMPERATURE_MARGIN * MATERIALS[key].max_service_temperature) - 1)
    out.append(max(s.hot_wall_stress / s.hot_wall_allowable for s in st) - 1)
    out.append(max(s.rib_stress / s.rib_allowable for s in st) - 1)
    out.append(MIN_CHANNEL_WIDTH / min(s.width for s in st) - 1)
    out.append(max(s.depth / s.width for s in st) / MAX_CHANNEL_ASPECT - 1)
    return out


def optimize_cooling(b: EngineBuild, n_trials: int = 200, seed: int = 7) -> tuple[CoolingInputs, dict]:
    import warnings

    import optuna

    warnings.filterwarnings("ignore", category=FutureWarning, module="optuna")
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    fu = b.cycle.fuel_shaft
    f1 = fu.turbine_flow / (1 + fu.preburner_mixture_ratio)
    a = b.inputs.cycle
    pc = b.perf.design.pc
    # Pressure the coolant must still have at the jacket outlet: the fuel-rich preburner
    # injector inlet plus the line and valve allowance. The jacket inlet pressure is that
    # plus the jacket's own drop, so each trial is evaluated at its own consistent inlet
    # pressure (two passes of a fixed-point iteration).
    p_outlet_need = fu.preburner_pressure * (1 + a.dp_pb_injector) + a.dp_liquid_lines * pc
    kw = dict(
        coolant_flow=f1,
        coolant_inlet_temperature=coolant_inlet_temperature(b.cycle, b.inputs.turbopump.t_fuel_inlet),
        n_stations=COOLING_STATIONS,
    )
    base = b.inputs.cooling
    eps = b.perf.design.eps

    def build(trial) -> CoolingInputs:
        film = trial.suggest_float("film_cooling_factor", 0.4, 1.0)
        return replace(
            base,
            n_channels_throat=trial.suggest_int("n_channels_throat", 200, 480, step=10),
            hot_wall_thickness=trial.suggest_float("hot_wall_thickness", 0.5e-3, 1.0e-3),
            copper_nozzle_wall_thickness=trial.suggest_float("copper_nozzle_wall_thickness", 0.8e-3, 2.0e-3),
            nozzle_wall_thickness=trial.suggest_float("nozzle_wall_thickness", 0.5e-3, 1.0e-3),
            rib_width=trial.suggest_float("rib_width", 0.8e-3, 1.6e-3),
            rib_fraction_nozzle=trial.suggest_float("rib_fraction_nozzle", 0.35, 0.80),
            depth_throat=trial.suggest_float("depth_throat", 3.0e-3, 8.0e-3),
            depth_chamber=trial.suggest_float("depth_chamber", 4.0e-3, 10.0e-3),
            depth_exit=trial.suggest_float("depth_exit", 4.0e-3, 12.0e-3),
            max_channel_width=trial.suggest_float("max_channel_width", 0.8e-3, 2.0e-3),
            max_channel_width_nozzle=trial.suggest_float("max_channel_width_nozzle", 1.0e-3, 2.5e-3),
            copper_to_area_ratio=trial.suggest_float("copper_to_area_ratio", 5.0, eps),
            film_cooling_factor=film,
            film_fraction_of_fuel=round(0.10 * (1 - film), 4),
        )

    def objective(trial):
        ci = build(trial)
        try:
            dp = b.cooling.pressure_drop if b.cooling.pressure_drop < pc else 0.8 * pc
            for _ in range(2):
                res = solve_cooling(b.perf, b.contour, ci, coolant_inlet_pressure=p_outlet_need + dp, **kw)
                dp = min(res.pressure_drop, 1.5 * pc)
        except Exception:
            trial.set_user_attr("constraints", [10.0])
            trial.set_user_attr("pressure_drop", 1e9)
            return 1e5
        cons = _cooling_constraints(res) + [res.pressure_drop / (MAX_COOLING_DP_FRACTION * b.perf.design.pc) - 1]
        trial.set_user_attr("constraints", cons)
        trial.set_user_attr("pressure_drop", res.pressure_drop)
        return res.pressure_drop / 1e5 + FILM_PENALTY_BAR * (1 - ci.film_cooling_factor)

    sampler = optuna.samplers.TPESampler(seed=seed, constraints_func=lambda t: t.user_attrs["constraints"])
    study = optuna.create_study(direction="minimize", sampler=sampler)
    # Seed with a hand-built starting layout (engineering judgment) so the search starts
    # near the feasible region; TPE then explores around it.
    study.enqueue_trial(SEED_LAYOUT | {"copper_to_area_ratio": min(SEED_LAYOUT["copper_to_area_ratio"], eps)})
    if base.film_cooling_factor < 1.0:  # warm start from the previous pass's layout
        study.enqueue_trial({k: getattr(base, k) for k in SEED_LAYOUT})
    study.optimize(objective, n_trials=n_trials)
    feasible = [t for t in study.trials if t.value is not None and all(c <= 0 for c in t.user_attrs["constraints"])]
    if feasible:
        best = min(feasible, key=lambda t: t.value)
    else:
        best = min(study.trials, key=lambda t: sum(max(c, 0) for c in t.user_attrs["constraints"]))
    ci = build(optuna.trial.FixedTrial(best.params))
    info = {"trials": len(study.trials), "feasible": len(feasible), "objective": best.value,
            "pressure_drop": best.user_attrs["pressure_drop"]}
    return ci, info


def _round_up(x: float, step: float) -> float:
    return math.ceil(x / step) * step


def iterate(ci: ComponentInputs | None = None, max_iter: int = 12, cooling_trials: int = 200,
            log=print) -> tuple[EngineBuild, list[IterationRecord], list[Check]]:
    ci = ci or ComponentInputs()
    history: list[IterationRecord] = []
    for it in range(1, max_iter + 1):
        b = build_engine(ci)
        if not b.ok:
            raise RuntimeError(f"Iteration {it}: cycle does not close: {b.cycle.message}")
        checks = all_checks(b)
        failed = [c for c in checks if not c.passed]
        fixable = [c for c in failed if c.gate != "G6"]
        actions: list[str] = []
        ids = {c.id for c in failed}
        pc = b.perf.design.pc
        cyc = ci.cycle

        if any(i.startswith("CL-") for i in ids):
            new_cool, info = optimize_cooling(b, n_trials=cooling_trials)
            ci = with_changes(ci, cooling=new_cool)
            dp_new = info["pressure_drop"]
            budget = _round_up(1.10 * dp_new / pc, 0.01)
            cyc = replace(cyc, dp_cooling=budget)
            actions.append(
                f"cooling layout re-optimized ({info['feasible']}/{info['trials']} feasible trials): "
                f"{new_cool.n_channels_throat} channels at throat, hot wall {new_cool.hot_wall_thickness * 1e3:.2f} mm, "
                f"film factor {new_cool.film_cooling_factor:.2f}, copper to area ratio {new_cool.copper_to_area_ratio:.1f}; "
                f"jacket drop {dp_new / 1e5:.0f} bar, cycle budget set to {cyc.dp_cooling:.2f} Pc"
            )
        ladder = pressure_ladder(b)
        if any(i in ids for i in ("SS-2", "SS-3", "SS-4")):
            need = max(r["losses_bar"] for r in ladder[1:4]) * 1e5 / pc
            new = _round_up(1.10 * need, 0.005)
            if new > cyc.dp_liquid_lines:
                cyc = replace(cyc, dp_liquid_lines=new)
                actions.append(f"liquid line and valve loss allowance set to {new:.3f} Pc")
        if "SS-3" in ids and not cyc.ox_kick_stage:
            cyc = replace(cyc, ox_kick_stage=True)
            actions.append("oxidizer kick stage added: the fuel-rich preburner now runs above the oxidizer pump discharge")
        if "SS-4" in ids and not cyc.fuel_kick_stage:
            cyc = replace(cyc, fuel_kick_stage=True)
            actions.append("fuel kick stage added: the oxygen-rich preburner needs more pressure than the main fuel pump gives")
        if any(i in ids for i in ("SS-5", "SS-6")):
            need = max(r["losses_bar"] for r in ladder[4:6]) * 1e5 / pc
            new = _round_up(1.10 * need, 0.005)
            if new > cyc.dp_hot_gas_ducts:
                cyc = replace(cyc, dp_hot_gas_ducts=new)
                actions.append(f"hot-gas duct loss allowance set to {new:.3f} Pc")
        if "SS-1" in ids and "CL-4" not in ids:
            # Jacket is within budget but the lines around it are not.
            extra = -ladder[0]["margin_bar"] * 1e5 / pc
            cyc = replace(cyc, dp_cooling=_round_up(cyc.dp_cooling + 1.1 * extra, 0.01))
            actions.append(f"cooling-path budget raised to {cyc.dp_cooling:.2f} Pc to cover lines and the coolant valve")
        tp = ci.turbopump
        if ("TP-F2" in ids or "TP-O2" in ids):
            if cyc.p_pump_inlet < MAX_PUMP_INLET:
                cyc = replace(cyc, p_pump_inlet=cyc.p_pump_inlet + 1e5)
                actions.append(f"pump inlet pressure requirement raised to {cyc.p_pump_inlet / 1e5:.0f} bar (vehicle requirement)")
            elif tp.max_stages < 4:
                tp = replace(tp, max_stages=tp.max_stages + 1)
                actions.append(f"allowed {tp.max_stages} pump stages")
        for shaft_name, tpd in (("fuel", b.fuel_tp), ("ox", b.ox_tp)):
            for kind, pred in (("pump", tpd.pump.efficiency_predicted), ("turbine", tpd.turbine.efficiency_predicted)):
                key = f"eta_{kind}_{shaft_name}"
                now = getattr(cyc, key)
                # The cycle takes the component prediction less a 0.03 margin, rounded down.
                target = math.floor((pred - EFFICIENCY_MARGIN) * 100) / 100
                if abs(target - now) >= 0.01:
                    cyc = replace(cyc, **{key: target})
                    actions.append(f"{shaft_name} {kind} efficiency in the cycle set from {now:.2f} to {target:.2f} "
                                   f"(component prediction {pred:.3f} less {EFFICIENCY_MARGIN})")
        pbi = ci.preburner
        for tag, flag, tkey, label in (("F", "fuel_rich_liner_cooled", "t_fuel_rich_pb", "fuel-rich"),
                                       ("O", "ox_rich_liner_cooled", "t_ox_rich_pb", "oxygen-rich")):
            if f"PB-{tag}2" not in ids:
                continue
            if not getattr(pbi, flag):
                pbi = replace(pbi, **{flag: True})
                actions.append(f"{label} preburner given a propellant-cooled liner (wall too hot)")
            else:
                cyc = replace(cyc, **{tkey: getattr(cyc, tkey) - 25.0})
                actions.append(f"{label} preburner temperature lowered to {getattr(cyc, tkey):.0f} K")
        inj = ci.injector
        if "IN-3" in ids:
            inj = replace(inj, n_elements=int(inj.n_elements * 0.9))
            actions.append(f"injector elements reduced to {inj.n_elements}")

        new_ci = with_changes(ci, cycle=cyc, turbopump=tp, injector=inj, preburner=pbi)
        if new_ci == ci:
            actions = []  # the fixes reproduced the same design: converged, stop
        ci = new_ci
        rec = IterationRecord(it, [f"{c.id} {c.description}: {c.value:.3g} vs {c.limit:.3g} {c.unit}" for c in failed],
                              actions, b.mass, b.cooling.pressure_drop / 1e5)
        history.append(rec)
        log(f"iteration {it}: {len(failed)} failing checks, mass {b.mass:.0f} kg")
        for a in actions:
            log(f"   - {a}")
        if not fixable or not actions:
            return b, history, checks
    b = build_engine(ci)
    return b, history, all_checks(b)
