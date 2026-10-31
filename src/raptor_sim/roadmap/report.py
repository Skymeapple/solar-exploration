"""Roadmap outputs: tables, capability transfer matrix, Gantt chart and summary."""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from . import logistics as L
from .catalog import KEY_MILESTONES, PHASES, Program, build_program, load_overrides
from .montecarlo import MCResult, mode_plan, run_monte_carlo
from .options import OPTIONS, RECOMMENDED, apply
from .schedule import WINDOWS, driving_path, forward_pass, to_date, to_year, total_float, window_dates
from .sources import EXTERNAL, SOURCES

OVERRIDES = Path(__file__).with_name("overrides.json")


def transfer_matrix(prog: Program, timing) -> list[dict]:
    """For each capability: where it is first proven, when, and every later step that reuses it."""
    rows = []
    for cap, src in sorted(prog.provider.items(), key=lambda kv: timing[kv[1]].finish):
        users = [s.id for s in prog.steps.values() if cap in s.needs]
        soft = [s.id for s in prog.steps.values() if cap in s.benefits]
        rows.append({"capability": cap, "proven_by": src, "proven": to_date(timing[src].finish).isoformat(),
                     "phase": prog.steps[src].phase, "needed_by": users, "reused_by": soft,
                     "uses": len(users) + len(soft)})
    return rows


def gantt_svg(prog: Program, timing, mc: MCResult | None, path: Path, y0: int = 2026, y1: int = 2060) -> None:
    """Gantt chart: bar = most likely plan; whisker = Monte Carlo P10-P90 finish; diamonds = Mars windows."""
    order = sorted(prog.order, key=lambda k: (prog.steps[k].phase, timing[k].start))
    left, top, row_h, width = 360, 40, 16, 1180
    px = (width - left - 20) / (y1 - y0)
    h = top + row_h * len(order) + 60
    colors = {"P0": "#4e79a7", "P1": "#59a14f", "P2": "#9c755f", "P3": "#e15759",
              "P4": "#b07aa1", "P5": "#f28e2b", "P6": "#76b7b2"}
    X = lambda yr: left + (yr - y0) * px  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" font-family="Helvetica,Arial,sans-serif" font-size="11">',
           f'<rect width="{width}" height="{h}" fill="white"/>',
           '<text x="10" y="20" font-size="14" font-weight="bold">Solar exploration master schedule</text>',
           f'<text x="{left}" y="20" fill="#555">bar: most likely plan; line: Monte Carlo P10-P90 finish; red ticks: Mars launch windows</text>']
    for yr in range(y0, y1 + 1, 2):
        out.append(f'<line x1="{X(yr):.1f}" y1="{top - 8}" x2="{X(yr):.1f}" y2="{h - 50}" stroke="#eee"/>')
        out.append(f'<text x="{X(yr):.1f}" y="{h - 36}" text-anchor="middle" fill="#555">{yr}</text>')
    for d in window_dates("mars", y1):
        yr = d.year + (d.timetuple().tm_yday - 1) / 365.25
        out.append(f'<line x1="{X(yr):.1f}" y1="{top - 8}" x2="{X(yr):.1f}" y2="{h - 50}" stroke="#e15759" stroke-opacity="0.35"/>')
    for i, sid in enumerate(order):
        s = prog.steps[sid]
        y = top + i * row_h
        a, b = to_year(timing[sid].start), to_year(timing[sid].finish)
        out.append(f'<text x="{left - 6}" y="{y + 11}" text-anchor="end">{sid}  {s.name[:32]}</text>')
        xb = min(X(b), X(y1))
        out.append(f'<rect x="{X(a):.1f}" y="{y + 3}" width="{max(2, xb - X(a)):.1f}" height="{row_h - 6}" fill="{colors[s.phase]}" rx="2"/>')
        if b > y1:
            out.append(f'<text x="{X(y1) - 4:.1f}" y="{y + 11}" text-anchor="end" fill="white" font-size="9">to {b:.0f} &#8594;</text>')
        if mc and sid in mc.milestones:
            m = mc.milestones[sid]
            if m["p10"] < y1:
                out.append(f'<line x1="{X(m["p10"]):.1f}" y1="{y + 8}" x2="{X(min(m["p90"], y1)):.1f}" y2="{y + 8}" stroke="#222"/>')
            if m["p50"] < y1:
                out.append(f'<circle cx="{X(m["p50"]):.1f}" cy="{y + 8}" r="3" fill="#222"/>')
    lx = 10
    for ph, name in PHASES.items():
        out.append(f'<rect x="{lx}" y="{h - 22}" width="10" height="10" fill="{colors[ph]}"/>'
                   f'<text x="{lx + 14}" y="{h - 13}">{ph}</text>')
        lx += 50
    out.append("</svg>")
    path.write_text("\n".join(out))


def _yr(x: float) -> str:
    return f"{x:.1f}"


def run(out_dir: Path, n: int = 5000, seed: int = 2026, overrides: Path | None = OVERRIDES) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = load_overrides(overrides) if overrides and overrides.exists() else None
    prog = build_program(steps)
    dur, cost = mode_plan(prog)
    tm = forward_pass(prog, dur)
    mc = run_monte_carlo(prog, n=n, seed=seed)

    # Options, each alone and the recommended set
    base_steps = list(prog.steps.values())
    options = []
    for key, keys in [("baseline", ())] + [(k, (k,)) for k in OPTIONS] + [("recommended", RECOMMENDED)]:
        p = build_program(apply(keys, base_steps))
        r = mc if key == "baseline" else run_monte_carlo(p, n=n, seed=seed)
        options.append({"key": key, "label": OPTIONS[key][0] if key in OPTIONS else key.capitalize(),
                         "cargo1_p50": r.milestones["MARS-CARGO-1"]["p50"],
                         "crew_p10": r.milestones["MARS-CREW-1"]["p10"],
                         "crew_p50": r.milestones["MARS-CREW-1"]["p50"],
                         "crew_p90": r.milestones["MARS-CREW-1"]["p90"],
                         "return_p50": r.milestones["MARS-CREW-RETURN"]["p50"],
                         "cost_to_return_p50": r.cost_to["MARS-CREW-RETURN"]["p50"],
                         "p_crew_by_2040": r.prob_by["MARS-CREW-1"].get(2040)})
        if key == "recommended":
            rec_prog, rec_mc = p, r
    rec_dur = mode_plan(rec_prog)[0]
    rec_tm = forward_pass(rec_prog, rec_dur)
    fl = total_float(rec_prog, rec_dur, KEY_MILESTONES)

    logs = {c.name: L.campaign(rec_prog, rec_tm, c) for c in (L.VEHICLE_MODEL, L.VEHICLE_CONSERVATIVE)}
    tmx = transfer_matrix(rec_prog, rec_tm)

    # ---- files ----
    with open(out_dir / "schedule.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "phase", "kind", "start", "finish", "float_months", "window",
                    "trl_now", "trl_end", "cost_mode_musd", "p10_finish", "p50_finish", "p90_finish",
                    "criticality_mars_crew", "owner", "basis"])
        for sid in rec_prog.order:
            s = rec_prog.steps[sid]
            m = rec_mc.milestones.get(sid, {})
            w.writerow([sid, s.name, s.phase, s.kind, to_date(rec_tm[sid].start), to_date(rec_tm[sid].finish),
                        fl.get(sid, ""), s.window or "", s.trl[0] if s.trl else "", s.trl[1] if s.trl else "",
                        s.cost[1], _yr(m["p10"]) if m else "", _yr(m["p50"]) if m else "", _yr(m["p90"]) if m else "",
                        f'{rec_mc.criticality.get(sid, 0):.2f}', s.owner, s.basis])
    for name, rows in logs.items():
        fn = "logistics_model.csv" if name == L.VEHICLE_MODEL.name else "logistics_conservative.csv"
        with open(out_dir / fn, "w", newline="") as f:
            keys = [k for k in asdict(rows[0]) if k != "notes"]
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow({k: (round(v, 1) if isinstance(v, float) else v) for k, v in asdict(r).items() if k != "notes"})
    gantt_svg(rec_prog, rec_tm, rec_mc, out_dir / "gantt.svg")
    data = {
        "start": "2026-11-01", "n_runs": n, "seed": seed,
        "mars_windows": [d.isoformat() for d in window_dates("mars", 2050)],
        "baseline": {"milestones": mc.milestones, "cost_total": mc.cost_total, "cost_to": mc.cost_to,
                     "criticality": mc.criticality, "prob_by": mc.prob_by,
                     "mode_finish": {k: to_date(tm[k].finish).isoformat() for k in KEY_MILESTONES},
                     "driving_path_mars_crew": driving_path(prog, tm, "MARS-CREW-1")},
        "recommended": {"options": list(RECOMMENDED), "milestones": rec_mc.milestones, "cost_total": rec_mc.cost_total,
                        "cost_by_phase": rec_mc.cost_by_phase, "cost_to": rec_mc.cost_to,
                        "spend_by_year": rec_mc.spend_by_year, "criticality": rec_mc.criticality,
                        "criticality_outer": rec_mc.criticality_outer, "failure_rate": rec_mc.failure_rate,
                        "prob_by": rec_mc.prob_by,
                        "mode_finish": {k: to_date(rec_tm[k].finish).isoformat() for k in KEY_MILESTONES},
                        "driving_path_mars_crew": driving_path(rec_prog, rec_tm, "MARS-CREW-1"),
                        "driving_path_outer_crew": driving_path(rec_prog, rec_tm, "OUTER-CREW-1")},
        "options": options, "transfer": tmx, "float_months": fl,
        "lunar_tankers": {c.name: L.lunar_tankers(c, L.LogisticsAssumptions()) for c in (L.VEHICLE_MODEL, L.VEHICLE_CONSERVATIVE)},
        "isru_power_kw_per_ship": L.isru_power_kw(L.LogisticsAssumptions()),
        "logistics": {k: [asdict(r) for r in v] for k, v in logs.items()},
    }
    (out_dir / "roadmap.json").write_text(json.dumps(data, indent=1, default=str))
    (out_dir / "summary.md").write_text(summary_md(rec_prog, rec_tm, rec_mc, prog, tm, mc, options, logs, tmx, fl))
    return data


def summary_md(prog, tm, mc, base_prog, base_tm, base_mc, options, logs, tmx, fl) -> str:
    L_ = []
    a = L_.append
    a("# Master roadmap results\n")
    a("Generated by `scripts/run_roadmap.py`. Dates are calendar years as decimals (2038.5 = July 2038). "
      f"Monte Carlo: {mc.n} runs. Money in 2026 $M. Basis tags per step are in `schedule.csv` and `catalog.py`.\n")
    a("## Key milestones, recommended plan\n")
    a("| Milestone | Plan date (most likely durations, no failures) | P10 | P50 | P90 | Baseline P50 |")
    a("| --- | --- | ---: | ---: | ---: | ---: |")
    for m in KEY_MILESTONES:
        r, b = mc.milestones[m], base_mc.milestones[m]
        a(f"| {m} {prog.steps[m].name} | {to_date(tm[m].finish)} | {_yr(r['p10'])} | {_yr(r['p50'])} | {_yr(r['p90'])} | {_yr(b['p50'])} |")
    a("\n## Acceleration options for the first crewed Mars landing\n")
    a("| Option | First cargo P50 | Crew lands P10 / P50 / P90 | Crew back P50 | Cost to crew return P50 ($M) | P(crew lands by end 2040) |")
    a("| --- | ---: | --- | ---: | ---: | ---: |")
    for o in options:
        a(f"| {o['label']} | {_yr(o['cargo1_p50'])} | {_yr(o['crew_p10'])} / {_yr(o['crew_p50'])} / {_yr(o['crew_p90'])} | "
          f"{_yr(o['return_p50'])} | {o['cost_to_return_p50']:,.0f} | {o['p_crew_by_2040']:.0%} |")
    a("\n## Critical path to the first crewed Mars landing\n")
    a("Plan (most likely durations, no failures): " + " → ".join(driving_path(prog, tm, "MARS-CREW-1")) + "\n")
    a("| Step | Share of runs on the driving path |")
    a("| --- | ---: |")
    for k, v in sorted(mc.criticality.items(), key=lambda kv: -kv[1]):
        if v >= 0.05:
            a(f"| {k} {prog.steps[k].name} | {v:.0%} |")
    a("\n## Cost\n")
    a(f"Whole program, all steps including Earth-side cost to Mars self-sufficiency: P10 {mc.cost_total['p10']:,.0f}, "
      f"P50 {mc.cost_total['p50']:,.0f}, P90 {mc.cost_total['p90']:,.0f}.\n")
    a("| To reach | P10 | P50 | P90 |")
    a("| --- | ---: | ---: | ---: |")
    for k, v in mc.cost_to.items():
        a(f"| {k} | {v['p10']:,.0f} | {v['p50']:,.0f} | {v['p90']:,.0f} |")
    a("\n| Phase | P10 | P50 | P90 |")
    a("| --- | ---: | ---: | ---: |")
    for ph, v in mc.cost_by_phase.items():
        a(f"| {ph} {PHASES[ph]} | {v['p10']:,.0f} | {v['p50']:,.0f} | {v['p90']:,.0f} |")
    a("\n| Year | Spend P50 | P90 |")
    a("| --- | ---: | ---: |")
    for y, v in mc.spend_by_year.items():
        if y <= 2060:
            a(f"| {y} | {v['p50']:,.0f} | {v['p90']:,.0f} |")
    a("\n## Technology readiness ladder\n")
    a("| Step | TRL now → at completion | Most likely completion | Failure-rework chance |")
    a("| --- | --- | --- | ---: |")
    for sid in prog.order:
        s = prog.steps[sid]
        if s.trl:
            p = min(0.6, 0.1 * (s.trl[1] - s.trl[0]))
            a(f"| {sid} {s.name} | {s.trl[0]} → {s.trl[1]} | {to_date(tm[sid].finish)} | {p:.0%} |")
    a("\n## Capability transfer\n")
    a("| Capability | First proven by | Date | Needed by | Also reused by |")
    a("| --- | --- | --- | --- | --- |")
    for r in tmx:
        a(f"| {r['capability']} | {r['proven_by']} | {r['proven']} | {', '.join(r['needed_by']) or '-'} | {', '.join(r['reused_by']) or '-'} |")
    for name, rows in logs.items():
        a(f"\n## Launch campaign: {name}\n")
        a("| Year | Mars ships | Lunar landings | Tankers | Commercial LEO | Launches | Propellant (kt) | Methane (kt) | Peak launches/month | Pads | Ships built | Engines built | Mars ISRU power (kW) |")
        a("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for r in rows:
            if r.year <= 2055:
                a(f"| {r.year} | {r.mars_ships} | {r.lunar_landings} | {r.tanker_launches} | {r.commercial_leo} | {r.launches} | "
                  f"{r.propellant_kt:,.0f} | {r.methane_kt:,.0f} | {r.peak_launches_per_month:.1f} | {r.pads_needed} | "
                  f"{r.ships_built} | {r.engines_built} | {r.mars_isru_kw:,.0f} |")
    a("\n## Steps with the most float (months; 60 means at least 60)\n")
    a("| Step | Float |")
    a("| --- | ---: |")
    for k, v in sorted(fl.items(), key=lambda kv: -kv[1])[:10]:
        a(f"| {k} | {v:.0f} |")
    a("\n## External reference points (cited)\n")
    for what, when, src in EXTERNAL:
        a(f"- {what}: {when} ([source]({SOURCES[src]}))")
    a("")
    return "\n".join(L_)
