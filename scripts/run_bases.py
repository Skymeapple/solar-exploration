"""Transit-base study: sites, power, ISRU, delta-v network, logistics, ranking, capabilities.

Writes results/bases/*.csv and results/bases/summary.md. Run: python scripts/run_bases.py
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from raptor_sim.bases import (
    SITES, Ship, base_buildup, best_power, build_network, capability_matrix, isru_plan,
    rank_sites, stepping_stone_routes,
)
from raptor_sim.bases.capabilities import CAPABILITIES, reuse_summary
from raptor_sim.bases.logistics import simulate_refill
from raptor_sim.bases.power import power_options, solar_fission_crossover_kwe
from raptor_sim.bases.ranking import SETTLEMENT_WEIGHTS

OUT = Path(__file__).resolve().parents[1] / "results" / "bases"


def fmt(x, nd=0):
    if x is None:
        return "-"
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return "n/a"
    return f"{x:,.{nd}f}"


def write_csv(name, rows):
    if not rows:
        return
    with open(OUT / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for dry in (100.0, 150.0):
        ship = Ship.from_engine_model(dry_t=dry)
        net = build_network(ship)
        routes = stepping_stone_routes(net)
        results[dry] = (ship, net, routes)
    ship, net, routes = results[100.0]
    ship150, net150, routes150 = results[150.0]

    # ---- sites
    site_rows = []
    for k, s in SITES.items():
        site_rows.append({
            "site": k, "name": s.name, "a_au": round(s.a_au, 3), "g_m_s2": round(s.surface_g, 3),
            "v_escape_m_s": round(s.v_escape), "t_min_k": s.t_min_k, "t_max_k": s.t_max_k,
            "pressure_bar": s.pressure_bar, "night_h": s.night_h, "solar_w_m2": round(s.solar_flux, 1),
            "dose_msv_yr": round(s.radiation_msv_yr), "water_frac": s.resources.water_frac,
            "carbon_source": s.resources.carbon_source, "nitrogen": s.resources.nitrogen,
            "metals_index": s.resources.metals,
            "basis_dose": s.basis_of("rad_trapped_msv_d" if s.rad_trapped_msv_d else "rad_gcr_msv_d"),
            "basis_water": s.basis_of("resources.water_frac"),
        })
    write_csv("sites.csv", site_rows)

    # ---- power and ISRU
    pw_rows, isru_rows = [], []
    for k, s in SITES.items():
        for load in (100.0, 1_000.0, 10_000.0):
            for o in power_options(s, load):
                pw_rows.append({"site": k, "load_kwe": load, "option": o.kind, "mass_t": round(o.mass_t, 1),
                                "kg_per_kwe": round(o.kg_per_kwe, 1), "feasible": o.feasible})
        plan = isru_plan(s)
        for c in plan.options:
            isru_rows.append({"site": k, "chain": c.name, "chosen": c.name == plan.best.name,
                              "local_fraction": round(c.local_fraction, 3),
                              "energy_mwh_per_t": round(c.energy_kwh_per_t / 1e3, 2),
                              "feed_t_per_t": round(c.feed_t_per_t, 1), "practical": c.practical,
                              "imported": c.imported, "passive_cryo": plan.passive_cryo})
    write_csv("power.csv", pw_rows)
    write_csv("isru.csv", isru_rows)

    # ---- network
    leg_rows = []
    for (a, b), leg in net.legs.items():
        leg_rows.append({"from": a, "to": b, "dv_space_m_s": round(leg.dv_space), "dv_surface_m_s": round(leg.dv_surface),
                         "dv_total_m_s": round(leg.dv_total), "tof_days": round(leg.tof_days, 1),
                         "window_every_days": round(leg.synodic_days), "entry_m_s": round(leg.entry_speed),
                         "payload_capacity_t_dry100": round(net.payload[(a, b)], 1),
                         "payload_capacity_t_dry150": round(net150.payload[(a, b)], 1)})
    write_csv("network_legs.csv", leg_rows)
    route_rows = []
    for k, r in routes.items():
        r150 = routes150[k]
        route_rows.append({"site": k, "route": " > ".join(r.path), "cargo_t": round(r.cargo_t, 1),
                           "direct_capacity_t": round(r.direct_payload_t, 1), "trip_days": round(r.tof_days),
                           "route_dry150": " > ".join(r150.path), "cargo_t_dry150": round(r150.cargo_t, 1)})
    write_csv("routes.csv", route_rows)

    # ---- logistics and refill simulation
    log_rows, refill_rows = [], []
    for k, s in SITES.items():
        for ph in base_buildup(s, net, routes):
            log_rows.append({"site": k, "phase": ph.phase, "power_mwe": round(ph.power_kwe / 1e3, 2),
                             "power_kind": ph.power_kind, "power_t": round(ph.power_t), "isru_plant_t": round(ph.isru_plant_t),
                             "habitat_t": round(ph.hab_t), "other_t": round(ph.other_t), "imported_t": round(ph.imported_t),
                             "deliveries": fmt(ph.deliveries, 1), "earth_launches": fmt(ph.earth_launches, 0),
                             "earth_launches_no_hubs": fmt(ph.earth_launches_direct, 0),
                             "shielding": ph.shielding_needed, "local_ship_fraction": ph.local_ship_fraction,
                             "methane_import_t_yr": round(ph.imported_ch4_t_per_yr)})
        r = routes[k]
        onward = [d for d in net.nodes if d not in (k,) and net.payload[(k, d)] > 0]
        # Departure window: the next interplanetary hop on any route through this site,
        # else the return to LEO; hops inside one planet's system assume a yearly cadence.
        nxt = [rt.path[rt.path.index(k) + 1] for rt in routes.values() if k in rt.path[1:-1]]
        nxt = [n for n in nxt if net.legs[(k, n)].synodic_days > 0]
        nxt_node = nxt[0] if nxt else "leo"
        window = net.legs[(k, nxt_node)].synodic_days or 365.25
        outpost = base_buildup(s, net, routes)[0]
        sim = simulate_refill(s, outpost.power_kwe, ship.propellant_t, window, crew_kwe=4 * 15.0)
        refill_rows.append({"site": k, "onward_to": nxt_node, "window_days": round(window),
                            "outpost_power_mwe": round(outpost.power_kwe / 1e3, 2),
                            "days_to_fill_ship": fmt(sim.days_to_fill, 0), "boiloff_t": round(sim.boiloff_t, 1),
                            "meets_window": sim.meets_window, "one_hop_destinations": len(onward)})
    write_csv("logistics.csv", log_rows)
    write_csv("refill.csv", refill_rows)

    # ---- ranking
    hub = rank_sites(net, routes)
    sett = rank_sites(net, routes, weights=SETTLEMENT_WEIGHTS, gate=False)
    hub150 = {s.site: s.rank for s in rank_sites(net150, routes150)}
    rank_rows = []
    sett_rank = {s.site: s for s in sett}
    for s in hub:
        row = {"site": s.site, "hub_rank": s.rank, "hub_score": round(s.total, 3),
               "hub_mean_rank_mc": round(s.mean_rank_mc, 2), "hub_p_top3": round(s.p_top3_mc, 2),
               "hub_rank_dry150": hub150[s.site], "settlement_rank": sett_rank[s.site].rank,
               "settlement_score": round(sett_rank[s.site].total, 3)}
        row.update({f"c_{c}": round(v, 2) for c, v in s.scores.items()})
        rank_rows.append(row)
    write_csv("ranking.csv", rank_rows)

    # ---- capabilities
    mat = capability_matrix(routes)
    cap_rows = []
    caps = {c.key: c for c in CAPABILITIES}
    for key, n in reuse_summary(mat):
        row = {"capability": caps[key].name, "group": caps[key].group, "first_proven_at": caps[key].origin, "sites": n}
        row.update({k: ("x" if v else "") for k, v in mat[key].items()})
        cap_rows.append(row)
    write_csv("capabilities.csv", cap_rows)

    summary = {
        "ship": ship.__dict__, "hubs": net.hubs,
        "routes": {r["site"]: r for r in route_rows}, "ranking": rank_rows,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    write_summary_md(site_rows, isru_rows, route_rows, log_rows, refill_rows, rank_rows, cap_rows, ship, net)
    return summary


def write_summary_md(site_rows, isru_rows, route_rows, log_rows, refill_rows, rank_rows, cap_rows, ship, net):
    L = ["# Transit bases across the solar system: study results", "",
         f"Ship: {ship.dry_t:.0f} t dry, {ship.propellant_t:.0f} t propellant, Isp {ship.isp_space:.1f} s (RVac) / "
         f"{ship.isp_surface:.1f} s (sea-level engines in vacuum), cargo cap {ship.max_payload_t:.0f} t.",
         f"Full refuelling hubs (ISRU makes the whole methane/oxygen load): {', '.join(net.hubs)}.", "",
         "## Ranking", "", "| Site | Hub rank | P(top 3) | Rank at 150 t dry | Settlement rank |", "|---|---|---|---|---|"]
    for r in rank_rows:
        L.append(f"| {r['site']} | {r['hub_rank']} | {r['hub_p_top3']:.2f} | {r['hub_rank_dry150']} | {r['settlement_rank']} |")
    L += ["", "## Routes from LEO (refuelling at hubs)", "", "| Site | Route | Cargo t | Direct capacity t | Trip days | Cargo t at 150 t dry |",
          "|---|---|---|---|---|---|"]
    for r in route_rows:
        L.append(f"| {r['site']} | {r['route']} | {r['cargo_t']} | {r['direct_capacity_t']} | {r['trip_days']} | {r['cargo_t_dry150']} |")
    L += ["", "## ISRU chain chosen", "", "| Site | Chain | Local share | MWh per t | Feedstock t/t |", "|---|---|---|---|---|"]
    for r in isru_rows:
        if r["chosen"]:
            L.append(f"| {r['site']} | {r['chain']} | {r['local_fraction']} | {r['energy_mwh_per_t']} | {r['feed_t_per_t']} |")
    L += ["", "## Outpost refill check", "", "| Site | Onward to | Window days | Outpost MWe | Days to fill a ship | Meets window |",
          "|---|---|---|---|---|---|"]
    for r in refill_rows:
        L.append(f"| {r['site']} | {r['onward_to']} | {r['window_days']} | {r['outpost_power_mwe']} | {r['days_to_fill_ship']} | {r['meets_window']} |")
    L += ["", "## Build-up (Earth launches incl. LEO tankers)", "", "| Site | Phase | MWe | Imported t | Earth launches | Without hubs |", "|---|---|---|---|---|---|"]
    for r in log_rows:
        L.append(f"| {r['site']} | {r['phase']} | {r['power_mwe']} | {r['imported_t']} | {r['earth_launches']} | {r['earth_launches_no_hubs']} |")
    L += ["", "## Capability reuse", "", "| Capability | Group | Sites |", "|---|---|---|"]
    for r in cap_rows:
        L.append(f"| {r['capability']} | {r['group']} | {r['sites']} |")
    (OUT / "summary.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
    print((OUT / "summary.md").read_text())
