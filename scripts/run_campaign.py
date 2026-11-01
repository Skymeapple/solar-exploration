"""Mars launch campaign: iterate the design until every objective passes, then verify it.

    python scripts/run_campaign.py [--rounds 10] [--mc 300]

1. Design iteration with reduced Monte Carlo sizes (raptor_sim.campaign.iterate).
2. Full Monte Carlo verification of the converged design.
3. Risk cases with and without mitigation, whole-campaign stress cases, sensitivity.
Writes results/campaign/: summary.md, campaign.json, iteration_log.json and plots.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np

from raptor_sim.campaign.campaign import Design, evaluate
from raptor_sim.campaign.iterate import iterate, propose
from raptor_sim.campaign.risks import run_risks, sensitivity, stress_cases

OUT = Path(__file__).resolve().parent.parent / "results" / "campaign"


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return jsonable(x.tolist())
    if isinstance(x, (np.floating, np.integer)):
        return x.item()
    if isinstance(x, date):
        return str(x)
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def plots(rep):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s = rep.samples
    fig, ax = plt.subplots(2, 2, figsize=(11, 7.5))
    tr = np.array([r[:5] for r in s["ascent_trace"]], dtype=float)
    stage = np.array([r[5] == "booster" for r in s["ascent_trace"]])
    a = ax[0, 0]
    a.plot(tr[stage, 0], tr[stage, 1] / 1e3, label="booster")
    a.plot(tr[~stage, 0], tr[~stage, 1] / 1e3, label="ship")
    a.set_xlabel("time (s)"); a.set_ylabel("altitude (km)"); a.set_title("P1 ascent with 100 t cargo"); a.legend()
    a2 = a.twinx(); a2.plot(tr[:, 0], tr[:, 3] / 1e3, "k:", lw=1); a2.set_ylabel("dynamic pressure (kPa), dotted")
    a = ax[0, 1]
    m = np.array(s["mars_entry_trace"], dtype=float)
    a.plot(m[:, 2] / 1e3, m[:, 1] / 1e3)
    a.set_xlabel("speed (km/s)"); a.set_ylabel("altitude (km)"); a.set_title("P6 Mars entry (nominal)")
    a = ax[1, 0]
    e = np.array(s["earth_entry_trace"], dtype=float)
    a.plot(e[:, 0], e[:, 3], label="deceleration (g)")
    a.plot(e[:, 0], e[:, 4] / 100, label="heat flux (100 W/cm2)")
    a.set_xlabel("time from entry interface (s)"); a.set_title("P9 Earth return entry (nominal)"); a.legend()
    a = ax[1, 1]
    a.hist(s["mars_landing_prop_t"], bins=30)
    a.axvline(rep.design.landing_propellant / 1e3, color="r", label="loaded")
    a.set_xlabel("Mars landing propellant used (t)"); a.set_title("P6 Monte Carlo"); a.legend()
    fig.tight_layout(); fig.savefig(OUT / "phases.png", dpi=110); plt.close(fig)

    fig, ax = plt.subplots(1, 3, figsize=(13, 3.8))
    ax[0].hist(s["tankers"], bins=np.arange(s["tankers"].min() - 0.5, s["tankers"].max() + 1.5))
    ax[0].set_xlabel("tanker launches"); ax[0].set_title("P3 refilling Monte Carlo")
    ax[1].hist(s["isru_produced_t"], bins=30); ax[1].axvline(rep.numbers["isru_load_t"], color="r", label="needed")
    ax[1].set_xlabel("propellant made on Mars (t)"); ax[1].set_title("P7 ISRU with dust storms"); ax[1].legend()
    ax[2].hist(s["earth_peak_g"], bins=30); ax[2].axvline(rep.design.earth_peak_g_limit, color="r", label="limit")
    ax[2].set_xlabel("Earth entry peak g"); ax[2].set_title("P9 Monte Carlo"); ax[2].legend()
    fig.tight_layout(); fig.savefig(OUT / "monte_carlo.png", dpi=110); plt.close(fig)

    pk = s["porkchop"]
    deps = sorted({p[0] for p in pk}); tofs = sorted({p[1] for p in pk})
    grid = np.full((len(tofs), len(deps)), np.nan)
    for dd, tof, c3, _ in pk:
        grid[tofs.index(tof), deps.index(dd)] = min(c3, 30)
    fig, a = plt.subplots(figsize=(8, 4.5))
    cs = a.contourf(range(len(deps)), tofs, grid, levels=np.arange(8, 31, 1.5))
    fig.colorbar(cs, label="C3 (km2/s2)")
    ticks = list(range(0, len(deps), 15)); a.set_xticks(ticks); a.set_xticklabels([deps[i] for i in ticks], rotation=30)
    a.set_ylabel("time of flight (days)"); a.set_title("Earth to Mars 2028 window (departure C3)")
    fig.tight_layout(); fig.savefig(OUT / "porkchop_2028.png", dpi=110); plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=10)
    ap.add_argument("--mc", type=int, default=300)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    # Quick-Monte-Carlo iteration, then full verification. If verification finds a new failure
    # (a rare case the small samples missed), apply the rule and iterate again.
    d, history = Design(), []
    for outer in range(4):
        d, _, h = iterate(d, max_rounds=args.rounds)
        for e in h:
            e["round"] = len(history)
            history.append(e)
        print("verifying the converged design with full Monte Carlo ...")
        rep = evaluate(d, n_mc=args.mc, quick=False, seed=101 + outer)
        for o in rep.objectives:
            print(f"  {o.id} {'PASS' if o.passed else 'FAIL'} {o.text}: {o.value:.3g} vs {o.limit:g} {o.unit}")
        failing = [o.id for o in rep.failing()]
        entry = {"round": len(history), "failing": failing, "verification": True,
                 "objectives": {o.id: {"value": o.value, "limit": o.limit, "passed": o.passed} for o in rep.objectives},
                 "changes": []}
        history.append(entry)
        if not failing:
            break
        d, changes = propose(rep)
        entry["changes"] = ["(full Monte Carlo verification) " + c for c in changes]
        print("  verification failed; changes:", changes)
    print("risk cases ...")
    risks = run_risks(d, rep.numbers)
    print("stress cases ...")
    stress = stress_cases(d)
    print("sensitivity ...")
    sens = sensitivity(d)
    plots(rep)

    (OUT / "iteration_log.json").write_text(json.dumps(jsonable(history), indent=1))
    (OUT / "campaign.json").write_text(json.dumps(jsonable({
        "design": asdict(d), "objectives": [asdict(o) for o in rep.objectives], "numbers": rep.numbers,
        "risks": [asdict(r) for r in risks], "stress": stress, "sensitivity": sens}), indent=1))
    write_summary(d, rep, history, risks, stress, sens)
    print("done:", OUT)


def write_summary(d, rep, history, risks, stress, sens):
    n = rep.numbers
    L = ["# Mars launch campaign: simulation and verification results", "",
         f"{len(history)} evaluation rounds (quick Monte Carlo iterations plus full verifications). Final verification: "
         f"{sum(o.passed for o in rep.objectives)} of {len(rep.objectives)} objectives pass.", "",
         "## Objectives (final verification)", "", "| ID | Phase | Objective | Result | Limit | Pass | Note |",
         "| --- | --- | --- | --- | --- | --- | --- |"]
    for o in rep.objectives:
        L.append(f"| {o.id} | {o.phase} | {o.text} | {o.value:.3g} {o.unit} | {o.limit:g} | {'PASS' if o.passed else 'FAIL'} | {o.note} |")
    L += ["", "## Iteration history", "", "| Round | Failing objectives | Changes made |", "| --- | --- | --- |"]
    for h in history:
        tag = " (full verification)" if h.get("verification") else ""
        L.append(f"| {h['round']}{tag} | {', '.join(h['failing']) or 'none'} | {'<br>'.join(h['changes']) or '(all pass)'} |")
    tr, rt = n["transfer"], n["return_transfer"]
    br = n["booster_return"]
    me, ee = n["mission_entry"] if "mission_entry" in n else n["mars_entry"], n["earth_entry"]
    L += ["", "## Mission timeline and key numbers", "",
          "| Phase | Result |", "| --- | --- |",
          f"| P1 ascent | Max-Q {n['max_q_kpa']:.1f} kPa at Mach {n['max_q_mach']:.2f}, {n['max_q_alt_km']:.1f} km; staging at {n['meco_time_s']:.0f} s, {n['meco_alt_km']:.0f} km, {n['meco_speed']:.0f} m/s; orbit at {n['seco_time_s']:.0f} s. Gravity loss {n['gravity_loss']:.0f} m/s, drag loss {n['drag_loss']:.0f} m/s. Payload with tanker landing reserve: {n['payload_capability_t']:.0f} t. Cargo ship arrives with {n['cargo_residual_t']:.0f} t propellant. |",
          f"| P2 booster return | Boostback {br['boostback_s']:.0f} s, landing burn {br['landing_burn_s']:.0f} s, {br['propellant_used']/1e3:.0f} t used of {br['reserve']/1e3:.0f} t reserve ({100*br['margin_fraction']:.0f}% margin), touchdown {br['touchdown_speed']:.1f} m/s, {br['miss_distance_m']:.0f} m from the pad. Reserve {d.booster_reserve_fraction:.0%} of booster propellant. |",
          f"| P3 refilling | {n['leo_required_t']:.0f} t needed in LEO ({n['leo_required_worst_in_period_t']:.0f} t on the worst day). Each tanker delivers {n['tanker_delivery_t']:.0f} t. {n['tankers_median']:.0f} tanker launches median, {n['tankers_p95']:.0f} at 95%. P(on time) {n['refill_p_on_time']:.3f}. Mean boil-off {n['boiloff_mean_t']:.0f} t. Launch period {n['launch_period'][0]} to {n['launch_period'][1]}. |",
          f"| P4 trans-Mars injection | Depart {tr['depart']}, C3 {tr['c3_km2s2']:.1f} km2/s2, {tr['tmi_impulsive']:.0f} m/s impulsive + {n['tmi_gravity_loss']:.0f} m/s gravity loss on 3 vacuum engines, {n['tmi_propellant_t']:.0f} t burned. |",
          f"| P5 cruise | {tr['tof_days']} days, arrive {tr['arrive']}. Correction delta-v 99th percentile {np.percentile(rep.samples['tcm'], 99):.1f} m/s (budget {d.tcm_budget:.0f}). |",
          f"| P6 Mars EDL | Entry {me['v_entry']/1e3:.2f} km/s at {d.mars_entry_fpa} deg, ballistic coefficient {me['ballistic_coefficient']:.0f} kg/m2, peak {me['peak_g']:.1f} g and {me['peak_heat']:.0f} W/cm2, corridor {me['corridor_deg']}. Retropropulsion from {me['srp_ignition_alt_km']:.1f} km; {me['landing_propellant_used_t']:.0f} t used nominal, {n['mars_landing_prop_p99_t']:.0f} t at 99%, {d.landing_propellant/1e3:.0f} t loaded. |",
          f"| P7 ISRU | {n['surface_stay_days']} days on the surface. {n['isru_kwh_per_kg']:.1f} kWh per kg of propellant [est]. {d.isru.solar_array_m2:,.0f} m2 arrays + {d.isru.nuclear_kwe:.0f} kWe fission. Needs {n['isru_load_t']:.0f} t; 5th percentile production {n['isru_produced_p5_t']:.0f} t. P(ready) {n['isru_p_success']:.3f}. |",
          f"| P8 Mars ascent and TEI | Ascent {n['mars_ascent_dv']:.0f} m/s to a 300 km orbit, TEI {n['tei_dv']:.0f} m/s; depart {rt['depart']}. |",
          f"| P9 Earth return | Arrive {rt['arrive']} at {ee['v_entry']/1e3:.2f} km/s, {d.earth_entry_fpa} deg; peak {ee['peak_g']:.1f} g, {ee['peak_heat']:.0f} W/cm2 vs {ee['tps_limit']:.0f} limit, corridor {n['earth_corridor_deg']}. |",
          f"| Overall | P(mission success) {n['p_mission']:.3f} (product of phase probabilities). |"]
    L += ["", "## Risks and mitigations (each checked in simulation)", "",
          "| ID | Phase | Risk | Mitigation | Without mitigation | With mitigation | Verified |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in risks:
        L.append(f"| {r.id} | {r.phase} | {r.risk} | {r.mitigation} | {r.unmitigated} | {r.mitigated} | {'yes' if r.verified else 'NO'} |")
    L += ["", "## Stress cases (whole campaign re-run, no redesign)", "", "| Case | Objectives that fail | Tankers (median) | P(mission) |", "| --- | --- | --- | --- |"]
    for s in stress:
        L.append(f"| {s['case']} | {'; '.join(s['failing']) or 'none'} | {s['tankers_median'] if s['tankers_median'] is None else round(s['tankers_median'])} | {s['p_mission']:.3f} |")
    L += ["", "## Sensitivity (deterministic, one change at a time)", "", "| Case | Tanker delivery (t) | Tankers | LEO propellant (t) | Mars propellant (t) |", "| --- | --- | --- | --- | --- |"]
    for s in sens:
        if s.get("note"):
            L.append(f"| {s['case']} | {s['note']} | - | {s['leo_required_t']:.0f} | {s['isru_load_t']:.0f} |")
        else:
            L.append(f"| {s['case']} | {s['tanker_delivery_t']:.0f} | {s['tankers']} | {s['leo_required_t']:.0f} | {s['isru_load_t']:.0f} |")
    L += ["", "![phases](phases.png)", "", "![monte carlo](monte_carlo.png)", "", "![porkchop](porkchop_2028.png)", ""]
    (OUT / "summary.md").write_text("\n".join(L))


if __name__ == "__main__":
    main()
