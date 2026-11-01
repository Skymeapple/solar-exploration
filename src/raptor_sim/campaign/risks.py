"""Risk register, mitigations checked in simulation, and sensitivity (stability) analysis.

Each risk is flown twice through the same phase simulation: once as it would
happen without the mitigation, once with it. A mitigation counts as verified
only if the mitigated case meets the phase objective.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .ascent import Dispersion, best_kick, booster_return, fly_ascent
from .bodies import MU_EARTH, R_EARTH
from .burns import finite_departure, impulsive_departure, propellant_for
from .campaign import Design, evaluate, make_stack, return_requirement, tmi_requirement
from .vehicle import tanker_stack
from .entry import EntryGuidance, EntryVehicle, fly_entry
from .interplanetary import transfer
from .mars_ops import isru_monte_carlo
from .refill import refill_monte_carlo


@dataclass
class Risk:
    id: str
    phase: str
    risk: str
    likelihood: str  # qualitative, estimate
    consequence: str
    mitigation: str
    unmitigated: str
    mitigated: str
    verified: bool


def _req_fn(st, d, vinf):
    v = tmi_requirement(st, d, vinf)[0]
    return lambda day: v


def run_risks(d: Design, base: dict) -> list[Risk]:
    """base: CampaignReport.numbers of the converged design."""
    st = make_stack(d)
    out: list[Risk] = []
    kick = base["kick_deg"]
    tr = base["transfer"]
    from datetime import date
    best = transfer("earth", "mars", date.fromisoformat(tr["depart"]), tr["tof_days"])
    vinf_arr = best.vinf_arrive

    # R1 booster engine out
    a0 = fly_ascent(st, d.cargo, kick, Dispersion(booster_engine_out_time=30.0))
    br = booster_return(st, a0, Dispersion(booster_engine_out_time=0.0)) if a0.reached_orbit else None
    out.append(Risk("R1", "P1/P2", "One booster engine fails 30 s after liftoff", "medium", "loss of mission and booster",
                    "Engine-out capability: the other 32 engines burn longer; return reserve sized with margin",
                    "No engine-out capability: abort, mission lost",
                    f"orbit reached: {a0.reached_orbit}, ship residual {a0.ship_residual/1e3:.1f} t; booster return margin "
                    f"{(br.margin_fraction*100 if br else float('nan')):.1f}% of reserve",
                    bool(a0.reached_orbit and a0.ship_residual >= 0 and br and br.margin_fraction >= 0)))

    # R2 ship engine out
    a1 = fly_ascent(st, d.cargo, kick, Dispersion(ship_engine_out_time=60.0))
    out.append(Risk("R2", "P1", "One ship sea-level engine fails 60 s after staging", "medium", "ship short of orbit",
                    "Remaining five engines burn longer; cargo ship reaches orbit with less residual and takes one more tanker",
                    "Abort to a sub-orbital disposal", f"orbit reached: {a1.reached_orbit}, residual {a1.ship_residual/1e3:.1f} t "
                    f"(nominal {base['cargo_residual_t']:.1f} t)", bool(a1.reached_orbit and a1.ship_residual >= 0)))

    # Delivery samples for refill risks (tankers fly the standard ship)
    tkick, _ = best_kick(tanker_stack(st), d.tanker_landing_reserve)
    rng = np.random.default_rng(4)
    deliv = []
    for _ in range(60):
        ds = Dispersion(isp=rng.normal(1, 0.003), thrust=rng.normal(1, 0.01), ship_dry=rng.normal(1, 0.02))
        t = fly_ascent(tanker_stack(st), 0.0, tkick, ds)
        deliv.append(t.ship_residual - d.tanker_landing_reserve)
    deliv = np.array(deliv)
    req = _req_fn(st, d, best.vinf_depart)
    w_days = (date.fromisoformat(base["launch_period"][1]) - date.fromisoformat(base["launch_period"][0])).days
    res0 = max(base["cargo_residual_t"] * 1e3, 0.0)

    def p_refill(plan):
        return refill_monte_carlo(plan, date.fromisoformat(base['launch_period'][0]), w_days, req, res0, deliv, n=1000, seed=9).p_on_time

    # R3 tanker reliability and cadence
    bad = replace(d.refill, launch_success=0.90, pad_turnaround_days=20.0)
    fix = replace(bad, pads=3, lead_days=d.refill.lead_days + 40, boiloff_per_day=0.0003)
    p_bad, p_fix = p_refill(bad), p_refill(fix)
    out.append(Risk("R3", "P3", "Tanker flights less reliable (90%) and slower to turn around (20 days)", "high",
                    "ship not full when the launch period closes: 26-month slip",
                    "Third pad, campaign starts 40 days earlier, sunshade on the waiting ship",
                    f"P(on time) {p_bad:.3f}", f"P(on time) {p_fix:.3f}", p_fix >= 0.95))

    # R4 boil-off
    bad = replace(d.refill, boiloff_per_day=0.003)
    fix = replace(bad, boiloff_per_day=0.0003)
    p_bad, p_fix = p_refill(bad), p_refill(fix)
    out.append(Risk("R4", "P3", "Boil-off in LEO three times the estimate (0.3%/day)", "medium",
                    "propellant lost faster than tankers deliver it",
                    "Sunshade and insulation on the waiting ship (0.03%/day) [est]",
                    f"P(on time) {p_bad:.3f}", f"P(on time) {p_fix:.3f}", p_fix >= 0.95))

    # R5 vacuum engine out during TMI
    loaded = tmi_requirement(st, d, best.vinf_depart)[0]
    m0 = st.ship_dry + d.cargo + loaded
    nominal = finite_departure("earth", best.vinf_depart, m0, st.engine, 3)
    two = finite_departure("earth", best.vinf_depart, m0, st.engine, 2)
    mixed = finite_departure("earth", best.vinf_depart, m0, st.engine, 2, 3)
    spare = loaded - nominal.propellant
    out.append(Risk("R5", "P4", "One vacuum engine fails at the start of trans-Mars injection", "low",
                    "longer burn, larger gravity loss, landing propellant eaten", 
                    "Fly on two vacuum engines (or add the three sea-level engines) and spend the 2% LEO margin",
                    f"2 RVac: {two.propellant/1e3:.0f} t burned vs {nominal.propellant/1e3:.0f} t nominal "
                    f"(gravity loss {two.gravity_loss:.0f} m/s)",
                    f"2 RVac + 3 SL: {mixed.propellant/1e3:.0f} t; margin available {spare/1e3:.0f} t",
                    bool(min(two.propellant, mixed.propellant) - nominal.propellant <= spare)))

    # R6 dust storm atmosphere at Mars entry
    veh = EntryVehicle(mass=st.ship_dry + d.cargo + d.landing_propellant)
    guid = EntryGuidance(v_srp=d.v_srp)

    def edl_p(sig, lp, n=150, seed=7, fpa0=None):
        fpa0 = d.mars_entry_fpa if fpa0 is None else fpa0
        r_ = np.random.default_rng(seed)
        ok = 0
        v_ = EntryVehicle(mass=st.ship_dry + d.cargo + lp)
        for _ in range(n):
            r = fly_entry("mars", vinf_arr, fpa0 + r_.normal(0, 0.1), v_, guid,
                          density_factor=math.exp(r_.normal(0, sig)), ld_factor=r_.normal(1, 0.1),
                          engine=st.engine, landing_propellant=lp)
            ok += (not r.skipped and not r.crashed and r.peak_g <= d.mars_peak_g_limit
                   and r.landing_propellant <= lp and r.touchdown_speed <= 3)
        return ok / n

    p_bad = edl_p(0.35, d.landing_propellant)
    # Mitigation search: thin air is forecast weeks ahead by orbiters, so the last correction can
    # steepen the entry (more drag, lower and slower at ignition) and the ship can carry more propellant.
    best = (p_bad, d.mars_entry_fpa, d.landing_propellant)
    for dfpa in (0.0, -0.4, -0.8):
        for dlp in (0.0, 10e3, 20e3):
            if best[0] >= 0.99:
                break
            pp = edl_p(0.35, d.landing_propellant + dlp, fpa0=d.mars_entry_fpa + dfpa)
            if pp > best[0]:
                best = (pp, d.mars_entry_fpa + dfpa, d.landing_propellant + dlp)
    p_fix, fpa_fix, lp_fix = best
    out.append(Risk("R6", "P6", "Mars atmosphere density varies 35% (1-sigma) instead of 15%, e.g. during a dust storm",
                    "medium", "crash or propellant exhausted on landing",
                    (f"Steepen the entry to {fpa_fix:.1f} deg with the final correction and carry "
                     if fpa_fix != d.mars_entry_fpa else f"Keep the {fpa_fix:.1f} deg baseline entry (already steepened) and carry ")
                    + f"{(lp_fix - d.landing_propellant)/1e3:.0f} t more landing propellant when orbiters report thin air",
                    f"P(EDL) {p_bad:.3f} at {d.mars_entry_fpa} deg with {d.landing_propellant/1e3:.0f} t",
                    f"P(EDL) {p_fix:.3f} at {fpa_fix:.1f} deg with {lp_fix/1e3:.0f} t", p_fix >= 0.99))

    # R7 landing engine out. The design now carries a fourth sea-level engine (Stack.ship_sl_engines);
    # "without" is the public three-engine ship (one engine's mass lighter) with one out.
    n_sl = st.ship_sl_engines
    veh3 = EntryVehicle(mass=veh.mass - max(n_sl - 3, 0) * st.engine.mass)
    r_bad = fly_entry("mars", vinf_arr, d.mars_entry_fpa, veh3, guid, engine=st.engine, landing_engines=2,
                      landing_propellant=d.landing_propellant)
    r_fix = fly_entry("mars", vinf_arr, d.mars_entry_fpa, veh, guid, engine=st.engine, landing_engines=n_sl - 1,
                      landing_propellant=d.landing_propellant)
    out.append(Risk("R7", "P6", "One landing engine fails to light", "medium", "ship crashes",
                    f"Design change (in baseline): {n_sl} sea-level engines (+{st.engine.mass/1e3:.1f} t each beyond 3), so one failure leaves {n_sl - 1}",
                    f"3 engines, one out: crashed={r_bad.crashed}, used {r_bad.landing_propellant/1e3:.0f} t, "
                    f"impact {r_bad.touchdown_speed:.0f} m/s",
                    f"{n_sl} engines, one out: crashed={r_fix.crashed}, used {r_fix.landing_propellant/1e3:.0f} t of "
                    f"{d.landing_propellant/1e3:.0f} t, touchdown {r_fix.touchdown_speed:.1f} m/s",
                    bool(not r_fix.crashed and r_fix.landing_propellant <= d.landing_propellant)))

    # R8 global dust storm during ISRU
    need = base["isru_load_t"] * 1e3
    stay = base["surface_stay_days"]
    solar_only = replace(d.isru, nuclear_kwe=0.0)
    p_bad = isru_monte_carlo(solar_only, need, stay, n=400, seed=8, storm_override=True).p_success
    plant = d.isru
    p_fix = isru_monte_carlo(plant, need, stay, n=400, seed=8, storm_override=True).p_success
    while p_fix < 0.95 and plant.nuclear_kwe < d.isru.nuclear_kwe + 500:
        plant = replace(plant, nuclear_kwe=plant.nuclear_kwe + 20.0)
        p_fix = isru_monte_carlo(plant, need, stay, n=400, seed=8, storm_override=True).p_success
    out.append(Risk("R8", "P7", "Global dust storm during the surface stay (sunlight ~30% for 60-120 sols)", "medium",
                    "return propellant not ready: return slips 26 months",
                    f"Fission power sized for a certain storm: {plant.nuclear_kwe:.0f} kWe (baseline {d.isru.nuclear_kwe:.0f} kWe) "
                    f"beside {plant.solar_array_m2:,.0f} m2 of arrays",
                    f"solar only: P(ready) {p_bad:.3f}", f"with {plant.nuclear_kwe:.0f} kWe fission: P(ready) {p_fix:.3f}",
                    p_fix >= 0.95))

    # R9 Earth return heating
    ee = base["earth_entry"]
    out.append(Risk("R9", "P9", "Earth entry at ~12.3 km/s overheats the tile heat shield", "high (certain without change)",
                    "loss of ship and payload",
                    "Ablative windward heat shield on the return ship (+6 t) [est rating 400 W/cm2]",
                    f"peak {ee['peak_heat']:.0f} W/cm2 vs tile limit {d.tps_limit_w_cm2:.0f} W/cm2",
                    f"peak {ee['peak_heat']:.0f} W/cm2 vs ablator limit {ee['tps_limit']:.0f} W/cm2",
                    ee["peak_heat"] <= ee["tps_limit"]))
    return out


def stress_cases(d: Design, n_mc: int = 90) -> list[dict]:
    """Whole-campaign re-runs with an adverse change: are the margins large enough without redesign?"""
    cases = [
        ("Isp 1% low on every engine", replace(d, isp_factor=0.99)),
        ("Ship dry mass +10 t", replace(d, ship_dry_growth=10e3)),
        ("Booster reserve held at 12%", replace(d, booster_reserve_fraction=0.12)),
    ]
    out = []
    for name, dd in cases:
        try:
            rep = evaluate(dd, n_mc=n_mc, quick=True, seed=31)
        except AttributeError:  # nominal cargo ascent never staged: the case fails outright
            out.append({"case": name, "failing": ["O1 (nominal ascent fails)"], "tankers_median": None, "p_mission": 0.0})
            continue
        out.append({"case": name, "failing": [f"{o.id} ({o.text})" for o in rep.failing()],
                    "tankers_median": rep.numbers["tankers_median"], "p_mission": rep.numbers["p_mission"],
                    "leo_required_t": rep.numbers["leo_required_t"], "isru_load_t": rep.numbers["isru_load_t"]})
    return out


def sensitivity(d: Design) -> list[dict]:
    """One-at-a-time deterministic sensitivity of the main sizing numbers (tornado data)."""
    def chain(dd: Design) -> dict:
        st = make_stack(dd)
        kick, _ = best_kick(st, dd.tanker_landing_reserve)
        tkick, _ = best_kick(tanker_stack(st), dd.tanker_landing_reserve)
        tank = fly_ascent(tanker_stack(st), 0.0, tkick)
        cargo = fly_ascent(st, dd.cargo, kick)
        deliver = (tank.ship_residual - dd.tanker_landing_reserve) * (1 - dd.refill.transfer_loss)
        from datetime import date
        best = transfer("earth", "mars", date(2028, 12, 2), 320)
        req = tmi_requirement(st, dd, best.vinf_depart)[0]
        rr = return_requirement(st, dd, 2333.0, 5345.0)
        if not (tank.reached_orbit and cargo.reached_orbit) or deliver <= 0:
            return {"tanker_delivery_t": float("nan"), "tankers": None, "leo_required_t": req / 1e3,
                    "isru_load_t": rr["isru_load"] / 1e3, "note": "ascent does not reach orbit"}
        return {"tanker_delivery_t": deliver / 1e3, "tankers": math.ceil(max(0, req - cargo.ship_residual) / deliver),
                "leo_required_t": req / 1e3, "isru_load_t": rr["isru_load"] / 1e3}

    base = chain(d)
    cases = [("Isp -1%", replace(d, isp_factor=0.99)), ("Isp +1%", replace(d, isp_factor=1.01)),
             ("Ship dry +10 t", replace(d, ship_dry_growth=10e3)), ("Ship dry -10 t", replace(d, ship_dry_growth=-10e3)),
             ("Booster reserve +2 pts", replace(d, booster_reserve_fraction=d.booster_reserve_fraction + 0.02)),
             ("Landing propellant +20 t", replace(d, landing_propellant=d.landing_propellant + 20e3)),
             ("Cargo +20 t", replace(d, cargo=d.cargo + 20e3))]
    rows = [{"case": "baseline", **base}]
    for name, dd in cases:
        rows.append({"case": name, **chain(dd)})
    return rows
