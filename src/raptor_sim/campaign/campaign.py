"""Mission-level launch and deployment campaign for the first Mars mission.

Runs every phase simulation in order, checks each against its objective, runs
Monte Carlo dispersions, and returns one report. `iterate.py` changes the design
levers below until every objective passes.

Phases
  P1 Earth ascent (cargo ship and tankers)       ascent.fly_ascent
  P2 Booster return to launch site               ascent.booster_return
  P3 LEO refilling campaign                      refill.refill_monte_carlo
  P4 Trans-Mars injection (finite burn)          burns.finite_departure
  P5 Cruise and trajectory corrections           interplanetary.tcm_monte_carlo
  P6 Mars entry, descent and propulsive landing  entry.fly_entry
  P7 Propellant production on Mars               mars_ops.isru_monte_carlo
  P8 Mars ascent and trans-Earth injection       mars_ops.mars_ascent, burns
  P9 Earth return entry                          entry.fly_entry
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta

import numpy as np

from ..constants import G0
from .ascent import Dispersion, best_kick, booster_return, fly_ascent, max_q_trim, payload_capability
from .bodies import MU_EARTH, MU_MARS, R_EARTH, R_MARS
from .burns import finite_departure, impulsive_departure, propellant_for
from .entry import ENTRY_INTERFACE, EntryGuidance, EntryVehicle, corridor, entry_speed, fly_entry
from .interplanetary import porkchop, tcm_monte_carlo
from .mars_ops import IsruPlant, isru_monte_carlo, mars_ascent
from .refill import RefillPlan, refill_monte_carlo
from .vehicle import Stack, tanker_stack


@dataclass(frozen=True)
class Design:
    """Everything the iteration loop may change, plus the mission requirements."""

    # Requirements (G0 of the procedure)
    cargo: float = 100e3  # kg landed on Mars [requirement]
    return_payload: float = 20e3  # kg brought back to Earth [requirement]
    earth_departure_search_start: date = date(2028, 9, 1)  # first window after this study [public windows ~26 months apart]
    mars_departure_search_start: date = date(2030, 8, 1)

    # Vehicle levers
    booster_reserve_fraction: float = 0.14  # converged in the 2026-10-31 iteration (was the mission.py 8%)
    # Adaptive booster cut-off: on a launch that is running short (low engine thrust), the booster may burn
    # up to this fraction of its propellant out of the return reserve, Falcon 9 style. The booster may
    # then be lost (an asset loss, counted separately); the Mars ship still reaches orbit.
    booster_adaptive_draw: float = 0.0
    q_limit_throttle: float = 0.0
    tanker_landing_reserve: float = 30e3  # kg each tanker keeps to land again [est]
    ship_dry_growth: float = 0.0
    isp_factor: float = 1.0  # risk and sensitivity cases scale every engine's Isp

    # Launch period: accept departures whose TMI is within this much of the best date
    launch_period_dv_margin: float = 100.0  # m/s

    # Refilling
    refill: RefillPlan = field(default_factory=RefillPlan)
    leo_propellant_margin: float = 0.02  # extra fraction of the computed need loaded before TMI

    # Cruise
    tcm_budget: float = 30.0  # m/s allocated
    cruise_boiloff_per_day: float = 0.0003  # [est] deep space, shaded tanks
    unusable_fraction: float = 0.01  # [est] residuals that cannot be burned

    # Mars entry and landing
    landing_propellant: float = 115e3  # kg loaded for landing, converged 2026-10-31 (mission.py's 700 m/s was 60 t)
    mars_entry_fpa: float = -12.4  # deg target at 125 km; steepened from -12.0 (campaign risk R6: thin-air robustness)
    v_srp: float = 1_000.0  # m/s retropropulsion ignition speed
    mars_peak_g_limit: float = 5.0  # [est] cargo; crew would be 4 g
    tps_limit_w_cm2: float = 100.0  # [est] ceramic tile system, stagnation-point convective
    max_arrival_vinf: float = 4_000.0  # m/s, keeps Mars entry speed below ~6.4 km/s

    # ISRU
    # Converged plant (40,000 m2 arrays) with fission sized for a certain global dust storm (campaign R8: 380 kWe).
    isru: IsruPlant = field(default_factory=lambda: IsruPlant(solar_array_m2=40_000.0, nuclear_kwe=380.0))

    # Earth return
    earth_braking_dv: float = 0.0  # m/s burn just before Earth entry to lower entry speed
    return_tps_upgrade: bool = True  # ablative windward TPS, now part of the ship (Stack.ship_ablator_mass), campaign R9
    return_tps_limit_w_cm2: float = 400.0  # [est] PICA-class ablator rating used for the upgrade (Stardust-class entries exceed 1,000 W/cm2 [public])
    return_tps_mass: float = 6e3  # kg added by the upgrade [est]
    earth_entry_fpa: float = -5.9  # corridor centre from the 2026-10-31 iteration
    earth_peak_g_limit: float = 5.0  # [est] crew-rated return
    earth_landing_reserve: float = 30e3  # kg [est]


@dataclass
class Objective:
    id: str
    phase: str
    text: str
    value: float
    limit: float
    unit: str
    passed: bool
    note: str = ""


@dataclass
class CampaignReport:
    design: Design
    objectives: list[Objective]
    numbers: dict
    samples: dict  # Monte Carlo arrays for plots

    @property
    def all_passed(self) -> bool:
        return all(o.passed for o in self.objectives)

    def failing(self) -> list[Objective]:
        return [o for o in self.objectives if not o.passed]


def make_stack(d: Design) -> Stack:
    st = Stack(booster_reserve_fraction=d.booster_reserve_fraction, q_limit_throttle=d.q_limit_throttle,
               ship_dry_growth=d.ship_dry_growth,
               ship_ablator_mass=d.return_tps_mass if d.return_tps_upgrade else 0.0)
    if d.isp_factor != 1.0:
        st = replace(st, engine=st.engine.scaled(d.isp_factor))
    return st


def ascent_dispersions(rng: np.random.Generator) -> Dispersion:
    """1-sigma: Isp 0.3%, thrust 1%, dry masses 2%, density 3%, drag 5% [all est]."""
    return Dispersion(isp=rng.normal(1, 0.003), thrust=rng.normal(1, 0.01), booster_dry=rng.normal(1, 0.02),
                      ship_dry=rng.normal(1, 0.02), density=rng.normal(1, 0.03), cd=rng.normal(1, 0.05))


# --------------------------------------------------------------------------- helpers


def tmi_requirement(stack: Stack, d: Design, vinf: float) -> tuple[float, float, float]:
    """Propellant the ship must hold in LEO to depart with v-infinity vinf, land, and keep margins.

    Returns (total required kg, TMI propellant kg, gravity loss m/s).
    """
    e = stack.engine
    after_tmi = d.landing_propellant
    m_land_ship = stack.ship_dry + d.cargo
    tcm_prop = propellant_for(d.tcm_budget, m_land_ship + after_tmi, e.rvac_isp)
    cruise_days = 240
    boil = after_tmi * (1 - (1 - d.cruise_boiloff_per_day) ** cruise_days)
    after = after_tmi + tcm_prop + boil
    after /= 1 - d.unusable_fraction
    m_after = m_land_ship + after
    p_tmi = propellant_for(impulsive_departure(vinf, MU_EARTH, R_EARTH + 300e3), m_after, e.rvac_isp)
    loss = 0.0
    for _ in range(3):
        burn = finite_departure("earth", vinf, m_after + p_tmi, e, stack.ship_vac_engines)
        loss = burn.gravity_loss
        p_tmi = propellant_for(burn.impulsive_dv + loss, m_after, e.rvac_isp)
    total = (p_tmi + after) * (1 + d.leo_propellant_margin)
    return total, p_tmi, loss


def return_requirement(stack: Stack, d: Design, vinf_dep: float, vinf_arr: float) -> dict:
    """ISRU propellant needed on Mars for ascent, trans-Earth injection, corrections, braking and landing."""
    e = stack.engine
    extra = 0.0  # the ablator is carried the whole mission, so it is in stack.ship_dry
    m_final = stack.ship_dry + extra + d.return_payload + d.earth_landing_reserve
    brake = propellant_for(d.earth_braking_dv, m_final, e.rvac_isp)
    tcm = propellant_for(d.tcm_budget, m_final + brake, e.rvac_isp)
    m_after_tei = m_final + brake + tcm
    tei_imp = impulsive_departure(vinf_dep, MU_MARS, R_MARS + 300e3)
    p_tei = propellant_for(tei_imp, m_after_tei, e.rvac_isp)
    burn = finite_departure("mars", vinf_dep, m_after_tei + p_tei, e, stack.ship_vac_engines)
    p_tei = propellant_for(burn.impulsive_dv + burn.gravity_loss, m_after_tei, e.rvac_isp)
    needed_in_orbit = (p_tei + brake + tcm + d.earth_landing_reserve) / (1 - d.unusable_fraction)
    payload_up = d.return_payload + extra
    # Find the surface load that leaves `needed_in_orbit` in the 300 km orbit.
    lo, hi = 100e3, stack.ship_propellant
    if mars_ascent(stack, payload_up, hi).residual < needed_in_orbit:
        load = math.inf
        asc = mars_ascent(stack, payload_up, hi)
    else:
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            if mars_ascent(stack, payload_up, mid).residual >= needed_in_orbit:
                hi = mid
            else:
                lo = mid
            if hi - lo < 500:
                break
        load = hi
        asc = mars_ascent(stack, payload_up, load)
    return {"isru_load": load, "ascent": asc, "tei_dv": burn.impulsive_dv + burn.gravity_loss,
            "tei_gravity_loss": burn.gravity_loss, "needed_in_orbit": needed_in_orbit, "payload_up": payload_up}


def earth_entry_speed(d: Design, vinf_arr: float) -> float:
    return entry_speed(vinf_arr, "earth") - d.earth_braking_dv


# --------------------------------------------------------------------------- main evaluation


def evaluate(d: Design, n_mc: int = 300, seed: int = 11, quick: bool = False) -> CampaignReport:
    rng = np.random.default_rng(seed)
    stack = make_stack(d)
    obj: list[Objective] = []
    num: dict = {}
    smp: dict = {}

    def add(id_, phase, text, value, limit, unit, passed, note=""):
        obj.append(Objective(id_, phase, text, float(value), float(limit), unit, bool(passed), note))

    # ---------------- P1 ascent
    kick, _ = best_kick(stack, d.tanker_landing_reserve)  # Mars ship (4 sea-level engines, ablator)
    tst = tanker_stack(stack)  # tankers fly the standard ship
    tkick, cap = best_kick(tst, d.tanker_landing_reserve)
    tanker = fly_ascent(tst, 0.0, tkick)
    cargo = fly_ascent(stack, d.cargo, kick, keep_trace=True)
    deliver_nom = tanker.ship_residual - d.tanker_landing_reserve
    num.update(kick_deg=kick, payload_capability_t=cap / 1e3, tanker_delivery_t=deliver_nom / 1e3,
               cargo_residual_t=cargo.ship_residual / 1e3, max_q_kpa=cargo.max_q_kpa, max_q_mach=cargo.max_q_mach,
               max_q_alt_km=cargo.max_q_alt_km, meco_time_s=cargo.meco_time, meco_alt_km=cargo.meco_alt_km,
               meco_speed=cargo.meco_speed_air, meco_gamma_deg=cargo.meco_gamma_deg, seco_time_s=cargo.seco_time,
               orbit_km=(cargo.perigee_km, cargo.apogee_km), gravity_loss=cargo.gravity_loss,
               drag_loss=cargo.drag_loss, ideal_dv=cargo.ideal_dv, max_booster_g=cargo.max_booster_g,
               max_ship_g=cargo.max_ship_g)
    smp["ascent_trace"] = cargo.trace
    n_asc = max(30, n_mc // 3) if quick else n_mc
    deliveries, cargo_ok, n_drawn = [], [], 0
    disps = [ascent_dispersions(rng) for _ in range(n_asc)]
    for ds in disps:
        t = fly_ascent(tst, 0.0, tkick, ds)
        deliveries.append(t.ship_residual - d.tanker_landing_reserve if t.reached_orbit else 0.0)
        c = fly_ascent(stack, d.cargo, kick, ds)
        ok = c.reached_orbit and c.ship_residual >= 0
        if not ok and d.booster_adaptive_draw > 0:
            drawn = replace(stack, booster_reserve_fraction=stack.booster_reserve_fraction - d.booster_adaptive_draw)
            c = fly_ascent(drawn, d.cargo, kick, ds)
            ok = c.reached_orbit and c.ship_residual >= 0
            n_drawn += 1
        cargo_ok.append(ok)
    deliveries = np.array(deliveries)
    num["booster_reserve_draws_fraction"] = n_drawn / len(disps)
    smp["tanker_delivery_t"] = deliveries / 1e3
    p_cargo = float(np.mean(cargo_ok))
    add("O1", "P1 ascent", "Mars ship reaches 300 km orbit with 100 t cargo (Monte Carlo)", p_cargo, 0.99, "probability",
        p_cargo >= 0.99, f"nominal residual {cargo.ship_residual/1e3:.1f} t"
        + (f"; {n_drawn / len(disps):.1%} of launches draw up to {d.booster_adaptive_draw:.0%} from the booster reserve"
           if d.booster_adaptive_draw > 0 else ""))
    add("O2", "P1 ascent", "Maximum dynamic pressure", cargo.max_q_kpa, 35.0, "kPa", cargo.max_q_kpa <= 35.0,
        "limit is an estimate (Falcon 9 class ~32 kPa)")
    trim = max_q_trim(stack, cargo)
    num["trim"] = asdict(trim)
    add("O3", "P1 ascent", "Gimbal angle to trim a 60 m/s crosswind at max-Q (control authority)",
        trim.gimbal_required_deg, trim.gimbal_limit_deg, "deg", trim.passed)

    # ---------------- P2 booster return
    br = booster_return(stack, cargo)
    num["booster_return"] = asdict(br) | {"margin_fraction": br.margin_fraction}
    n_b = 30 if quick else max(50, n_mc // 4)
    b_ok = []
    margins = []
    b_why: dict[str, int] = {}
    for ds in disps[:n_b]:
        a = fly_ascent(stack, d.cargo, kick, ds)
        if not a.reached_orbit:
            continue
        r = booster_return(stack, a, ds)
        margins.append(r.margin_fraction)
        why = []
        if r.propellant_used > r.reserve:
            why.append("propellant")
        if r.touchdown_speed > 3.0:
            why.append("touchdown speed")
        if r.miss_distance_m > 5_000:
            why.append("miss distance")
        for w in why:
            b_why[w] = b_why.get(w, 0) + 1
        b_ok.append(not why)
    smp["booster_margin"] = np.array(margins)
    num["booster_failures"] = b_why
    p_b = float(np.mean(b_ok)) if b_ok else 0.0
    add("O4", "P2 booster return", "Booster lands at the launch site with propellant left (Monte Carlo)", p_b, 0.99,
        "probability", p_b >= 0.99, f"nominal margin {100*br.margin_fraction:.1f}% of reserve, miss {br.miss_distance_m:.0f} m; "
        f"touchdown limit 3 m/s, miss limit 5 km (no terminal divert in L1); failures {b_why}")

    # ---------------- windows (P4 geometry)
    cands = porkchop("earth", "mars", d.earth_departure_search_start, 200, (120, 330), 2)
    tmi_dv = lambda t: impulsive_departure(t.vinf_depart, MU_EARTH, R_EARTH + 300e3)
    ok_arr = [t for t in cands if t.vinf_arrive <= d.max_arrival_vinf]
    best = min(ok_arr, key=tmi_dv)
    by_day: dict[date, object] = {}
    for t in ok_arr:
        if t.depart not in by_day or tmi_dv(t) < tmi_dv(by_day[t.depart]):
            by_day[t.depart] = t
    period = sorted(dd for dd, t in by_day.items() if tmi_dv(t) <= tmi_dv(best) + d.launch_period_dv_margin)
    w_open, w_days = period[0], (period[-1] - period[0]).days
    num.update(transfer={"depart": str(best.depart), "arrive": str(best.arrive), "c3_km2s2": best.c3,
                         "vinf_arrive": best.vinf_arrive, "tof_days": best.tof_days, "tmi_impulsive": tmi_dv(best)},
               launch_period=(str(period[0]), str(period[-1])))
    smp["porkchop"] = [(str(t.depart), t.tof_days, t.c3, t.vinf_arrive) for t in cands]

    # ---------------- P6 Mars entry, landing (needed before TMI to size landing propellant)
    e = stack.engine
    veh = EntryVehicle(mass=stack.ship_dry + d.cargo + d.landing_propellant)
    guid = EntryGuidance(v_srp=d.v_srp)
    nom = fly_entry("mars", best.vinf_arrive, d.mars_entry_fpa, veh, guid, engine=e,
                    landing_propellant=d.landing_propellant, keep_trace=True)
    smp["mars_entry_trace"] = nom.trace
    cor = corridor("mars", best.vinf_arrive, veh, d.mars_peak_g_limit, d.tps_limit_w_cm2, guid, engine=e,
                   landing_propellant=d.landing_propellant)
    num["mars_entry"] = {"v_entry": nom.v_entry, "peak_g": nom.peak_g, "peak_heat": nom.peak_heat_w_cm2,
                         "landing_propellant_used_t": nom.landing_propellant / 1e3, "corridor_deg": cor,
                         "ballistic_coefficient": veh.ballistic_coefficient, "srp_ignition_alt_km": nom.alt_at_ignition_km}
    n_e = max(60, n_mc // 3) if quick else n_mc
    edl_ok, used, pg, ph = [], [], [], []
    e_why: dict[str, int] = {}
    for _ in range(n_e):
        fpa = d.mars_entry_fpa + rng.normal(0, 0.1)  # [est] delivery accuracy after the last TCM
        dens = math.exp(rng.normal(0, 0.15))  # [est] seasonal and dust variability
        ldf = rng.normal(1, 0.10)
        isp = rng.normal(1, 0.003)
        vi = best.vinf_arrive + rng.normal(0, 20)
        r = fly_entry("mars", vi, fpa, veh, guid, density_factor=dens, ld_factor=ldf, engine=e.scaled(isp),
                      landing_propellant=d.landing_propellant)
        why = [w for w, bad in (("skip-out", r.skipped), ("crash", r.crashed), ("g", r.peak_g > d.mars_peak_g_limit),
                                ("heating", r.peak_heat_w_cm2 > d.tps_limit_w_cm2),
                                ("propellant", r.landing_propellant > d.landing_propellant),
                                ("touchdown speed", r.touchdown_speed > 3.0)) if bad]
        for w in why:
            e_why[w] = e_why.get(w, 0) + 1
        edl_ok.append(not why)
        used.append(r.landing_propellant)
        pg.append(r.peak_g)
        ph.append(r.peak_heat_w_cm2)
    smp.update(mars_landing_prop_t=np.array(used) / 1e3, mars_peak_g=np.array(pg), mars_peak_heat=np.array(ph))
    p_edl = float(np.mean(edl_ok))
    num["mars_landing_prop_p99_t"] = float(np.percentile(used, 99)) / 1e3
    num["mars_edl_failures"] = e_why
    add("O8", "P6 Mars EDL", "Entry, descent and landing succeed under dispersions (Monte Carlo)", p_edl, 0.99,
        "probability", p_edl >= 0.99,
        f"landing propellant used p99 {np.percentile(used, 99)/1e3:.1f} t of {d.landing_propellant/1e3:.0f} t loaded; failures {e_why}")
    width = (cor[1] - cor[0]) if cor else 0.0
    add("O9", "P6 Mars EDL", "Entry corridor width (g and heating limits, no skip-out)", width, 0.6, "deg",
        width >= 0.6, f"corridor {cor}; 0.6 deg = +/-3 sigma of the 0.1 deg delivery error")

    # ---------------- P4 TMI requirement across the launch period
    req_cache: dict[int, float] = {}
    tmi_nom = tmi_requirement(stack, d, best.vinf_depart)

    def required(day: int) -> float:
        if day not in req_cache:
            dd = w_open + timedelta(days=day)
            t = by_day.get(dd) or by_day.get(dd - timedelta(days=1)) or best
            req_cache[day] = tmi_requirement(stack, d, t.vinf_depart)[0]
        return req_cache[day]

    req_max = max(required(i) for i in range(0, w_days + 1, 2))
    num.update(leo_required_t=tmi_nom[0] / 1e3, tmi_propellant_t=tmi_nom[1] / 1e3, tmi_gravity_loss=tmi_nom[2],
               leo_required_worst_in_period_t=req_max / 1e3)
    add("O6", "P4 TMI", "Propellant needed in LEO fits the ship tanks (worst day of launch period)", req_max / 1e3,
        stack.ship_propellant / 1e3, "t", req_max <= stack.ship_propellant)

    # ---------------- P3 refilling
    deliv_ok = deliveries[deliveries > 0]
    rf = refill_monte_carlo(d.refill, w_open, w_days, required, max(cargo.ship_residual, 0.0), deliv_ok,
                            n=400 if quick else 2000, seed=seed)
    smp.update(tankers=rf.tankers_launched, departure_day=rf.departure_offset_days)
    num.update(refill_p_on_time=rf.p_on_time, tankers_median=float(np.median(rf.tankers_launched)),
               tankers_p95=float(np.percentile(rf.tankers_launched, 95)),
               nominal_tankers=math.ceil(max(0.0, tmi_nom[0] - cargo.ship_residual) / max(deliver_nom * (1 - d.refill.transfer_loss), 1)),
               boiloff_mean_t=float(np.mean(rf.boiloff_kg)) / 1e3)
    add("O5", "P3 refilling", "Ship is full and departs inside the launch period (Monte Carlo)", rf.p_on_time, 0.95,
        "probability", rf.p_on_time >= 0.95,
        f"median {np.median(rf.tankers_launched):.0f} tanker launches, 95th pct {np.percentile(rf.tankers_launched, 95):.0f}")

    # ---------------- P5 cruise
    tcm = tcm_monte_carlo(best, n=60 if quick else 300, seed=seed)
    p99 = float(np.percentile(tcm.tcm_total, 99))
    smp["tcm"] = tcm.tcm_total
    add("O7", "P5 cruise", "Trajectory correction delta-v, 99th percentile", p99, d.tcm_budget, "m/s",
        p99 <= d.tcm_budget)

    # ---------------- P8 return trajectory and requirement
    rc = porkchop("mars", "earth", d.mars_departure_search_start, 360, (150, 330), 6)
    arrive_mars = best.arrive
    rc = [t for t in rc if (t.depart - arrive_mars).days >= 300]
    ret_cost = lambda t: impulsive_departure(t.vinf_depart, MU_MARS, R_MARS + 300e3)
    ret = min(rc, key=ret_cost)
    req_ret = return_requirement(stack, d, ret.vinf_depart, ret.vinf_arrive)
    stay = (ret.depart - arrive_mars).days
    num.update(return_transfer={"depart": str(ret.depart), "arrive": str(ret.arrive), "vinf_depart": ret.vinf_depart,
                                "vinf_arrive": ret.vinf_arrive, "tof_days": ret.tof_days},
               surface_stay_days=stay, isru_load_t=req_ret["isru_load"] / 1e3, tei_dv=req_ret["tei_dv"],
               mars_ascent_dv=req_ret["ascent"].dv_spent, mars_ascent_gravity_loss=req_ret["ascent"].gravity_loss)
    load_ok = req_ret["isru_load"] <= stack.ship_propellant
    add("O10", "P8 Mars ascent", "Return propellant made on Mars fits the tanks", req_ret["isru_load"] / 1e3,
        stack.ship_propellant / 1e3, "t", load_ok,
        f"ascent {req_ret['ascent'].dv_spent:.0f} m/s, TEI {req_ret['tei_dv']:.0f} m/s")

    # ---------------- P7 ISRU
    need = min(req_ret["isru_load"], 1e12)
    isr = isru_monte_carlo(d.isru, need, stay, n=300 if quick else 1000, seed=seed)
    smp["isru_produced_t"] = isr.produced_kg / 1e3
    num.update(isru_p_success=isr.p_success, isru_kwh_per_kg=d.isru.kwh_per_kg_propellant(),
               isru_mean_power_kw=isr.mean_power_kw, isru_produced_p5_t=float(np.percentile(isr.produced_kg, 5)) / 1e3)
    add("O11", "P7 ISRU", "Return propellant produced before the return window (Monte Carlo, dust storms)",
        isr.p_success, 0.95, "probability", isr.p_success >= 0.95 and load_ok,
        f"{need/1e3:.0f} t needed in {stay} days; 5th percentile production {np.percentile(isr.produced_kg, 5)/1e3:.0f} t")

    # ---------------- P9 Earth entry
    extra = 0.0  # ablator already in stack.ship_dry
    rveh = EntryVehicle(mass=stack.ship_dry + extra + d.return_payload + d.earth_landing_reserve)
    v_ei = earth_entry_speed(d, ret.vinf_arrive)
    tps = d.return_tps_limit_w_cm2 if d.return_tps_upgrade else d.tps_limit_w_cm2
    eg = EntryGuidance(v_full_lift=0.0)
    ecor = corridor("earth", ret.vinf_arrive, rveh, d.earth_peak_g_limit, tps, eg, v_entry_override=v_ei)
    num["earth_corridor_deg"] = ecor
    en = fly_entry("earth", ret.vinf_arrive, d.earth_entry_fpa, rveh, eg, v_entry_override=v_ei, keep_trace=True)
    smp["earth_entry_trace"] = en.trace
    n_ee = max(60, n_mc // 3) if quick else n_mc
    ee_ok, eh, egs = [], [], []
    ee_why: dict[str, int] = {}
    for _ in range(n_ee):
        r = fly_entry("earth", ret.vinf_arrive, d.earth_entry_fpa + rng.normal(0, 0.1), rveh, eg,
                      density_factor=math.exp(rng.normal(0, 0.05)), ld_factor=rng.normal(1, 0.1),
                      v_entry_override=v_ei + rng.normal(0, 10))
        why = [w for w, bad in (("lost to space", r.skipped), ("g", r.peak_g > d.earth_peak_g_limit),
                                ("heating", r.peak_heat_w_cm2 > tps)) if bad]
        for w in why:
            ee_why[w] = ee_why.get(w, 0) + 1
        ee_ok.append(not why)
        eh.append(r.peak_heat_w_cm2)
        egs.append(r.peak_g)
    smp.update(earth_peak_heat=np.array(eh), earth_peak_g=np.array(egs))
    p_ee = float(np.mean(ee_ok))
    num["earth_entry"] = {"v_entry": v_ei, "peak_g": en.peak_g, "peak_heat": en.peak_heat_w_cm2, "tps_limit": tps,
                          "passes": en.passes, "failures": ee_why}
    ew = (ecor[1] - ecor[0]) if ecor else 0.0
    add("O12", "P9 Earth entry", "Earth entry within heating and g limits (Monte Carlo)", p_ee, 0.99, "probability",
        p_ee >= 0.99, f"nominal {v_ei/1e3:.2f} km/s, {en.peak_heat_w_cm2:.0f} W/cm2 vs {tps:.0f}, {en.peak_g:.1f} g, "
        f"corridor {ecor}, failures {ee_why}")

    # ---------------- overall
    p_mission = p_cargo * rf.p_on_time * p_edl * (isr.p_success if load_ok else 0.0) * p_ee
    num["p_mission"] = p_mission
    add("O13", "Overall", "End-to-end mission success (product of phase probabilities)", p_mission, 0.90,
        "probability", p_mission >= 0.90, "booster loss is an asset loss and is tracked by O4, not here")
    return CampaignReport(d, obj, num, smp)
