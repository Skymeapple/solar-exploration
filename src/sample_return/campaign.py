"""End-to-end Mars sample return run with verification gates SR-1 to SR-8.

Reference architecture (the NASA-ESA MSR pattern, also close to Tianwen-3):
a lander carrying the MAV launches in the 2028 window; samples are cached on the
surface; the MAV puts the orbiting sample container (OS) into a 380 km orbit; an
orbiter captures it, seals it in the containment vessel and departs in the
2030-31 return window; a passive EEV lands it on Earth.

Gate thresholds are study requirements [estimate] unless marked otherwise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .ascent import MAV, AscentConditions, design_mav, monte_carlo_ascent
from .bodies import AU, DAY, EARTH, MARS, MU_SUN
from .collection import SampleCache, SealDesign, SurfaceCampaign, earth_air_ingress, headspace_retained
from .containment import REQUIREMENT, ContainmentInputs, release_probability
from .entry import MSR_EEV, STARDUST, EntryConditions, allen_eggers, footprint_monte_carlo, simulate_entry
from .rendezvous import approach_monte_carlo, cw_vs_nonlinear, matching_dv
from .targets import compare_targets
from .transfer import burn_from_orbit, entry_speed, hohmann_vinf, lambert, propagate, search_window, transfer


@dataclass(frozen=True)
class Gate:
    id: str
    phase: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Requirements:
    """Study thresholds [estimate]."""

    lambert_position_error_m: float = 1_000.0
    hohmann_limit_tol: float = 0.005
    max_os_mass_kg: float = 16.0  # MAV payload allocation [cited 14-16 kg package]
    min_headspace_retained: float = 0.99
    max_air_ingress: float = 0.01
    days_landing_to_opening: float = 60.0
    mav_gross_max_kg: float = 450.0  # [cited] upper end of the public MAV mass
    min_os_periapsis_m: float = 200e3
    min_fraction_above_periapsis: float = 0.99
    cw_error_frac_at_10km: float = 0.01
    min_p_capture: float = 0.997
    orbiter_rendezvous_dv_budget: float = 150.0  # m/s
    max_entry_speed: float = 12.5e3  # m/s, below Stardust's flown 12.9 km/s
    ae_tol: float = 0.03
    max_heat_flux_W_cm2: float = 1_000.0  # PICA-class with margin [estimate]
    max_downrange_3sigma_km: float = 50.0
    gamma_entry_deg: float = -10.5


def _gate(gid: str, phase: str, ok: bool, detail: str) -> Gate:
    return Gate(gid, phase, bool(ok), detail)


def run_campaign(mc_runs: int = 300, req: Requirements | None = None) -> dict:
    req = req or Requirements()
    out: dict = {"requirements": req}
    gates: list[Gate] = []

    # --- SR-1 transfers --------------------------------------------------------
    outbound, _ = search_window("Earth", "Mars", (2028, 9, 1), 240, (150, 330), weight_arrival=0.3, step_days=4)
    ret, ret_grid = search_window("Mars", "Earth", (2030, 6, 1), 420, (150, 330), weight_arrival=1.0, step_days=4)
    # Independent check: propagate the solved return arc and compare with Earth's position.
    from .bodies import planet_state

    r1, _ = planet_state("Mars", ret.depart_jd)
    r2, _ = planet_state("Earth", ret.arrive_jd)
    v1, _ = lambert(r1, r2, (ret.arrive_jd - ret.depart_jd) * DAY)
    r2p, _ = propagate(r1, v1, (ret.arrive_jd - ret.depart_jd) * DAY)
    pos_err = float(np.linalg.norm(r2p - np.asarray(r2)))
    # Hohmann limit: circular coplanar, 179.9 deg transfer at Hohmann time.
    a1, a2 = AU, 1.523679 * AU
    vd_h, _, tof_h = hohmann_vinf(a1, a2)
    th = math.radians(179.9)
    v1h, _ = lambert([a1, 0, 0], [a2 * math.cos(th), a2 * math.sin(th), 0], tof_h)
    vinf_lam = float(np.linalg.norm(v1h - np.array([0, math.sqrt(MU_SUN / a1), 0])))
    hoh_err = abs(vinf_lam - vd_h) / vd_h
    out["transfer"] = {"outbound": outbound, "return": ret, "lambert_pos_err_m": pos_err, "hohmann_rel_err": hoh_err}
    gates.append(
        _gate(
            "SR-1",
            "Transfer windows",
            pos_err < req.lambert_position_error_m and hoh_err < req.hohmann_limit_tol,
            f"Lambert arc propagated independently lands {pos_err:.3f} m from Earth; "
            f"Hohmann-limit v_inf error {hoh_err * 100:.4f} %. Outbound {outbound.depart_date} -> {outbound.arrive_date} "
            f"(C3 {outbound.c3_depart:.1f} km2/s2); return {ret.depart_date} -> {ret.arrive_date} "
            f"(v_inf {ret.vinf_depart / 1e3:.2f} / {ret.vinf_arrive / 1e3:.2f} km/s)",
        )
    )

    # --- SR-2 collection and sealing -------------------------------------------
    cache, seal = SampleCache(), SealDesign()
    cruise_days = (ret.arrive_jd - ret.depart_jd) + 400  # wait in orbit + cruise
    retained = headspace_retained(seal, cruise_days)
    ingress = earth_air_ingress(seal, req.days_landing_to_opening, cruise_days)
    sols = SurfaceCampaign().expected_sols()
    out["collection"] = {
        "os_mass_kg": cache.os_mass,
        "sample_mass_kg": cache.sample_mass,
        "headspace_retained": retained,
        "air_ingress_fraction": ingress,
        "surface_sols": sols,
    }
    gates.append(
        _gate(
            "SR-2",
            "Collection and sealing",
            cache.os_mass <= req.max_os_mass_kg and retained >= req.min_headspace_retained and ingress <= req.max_air_ingress,
            f"OS {cache.os_mass:.1f} kg with {cache.sample_mass * 1e3:.0f} g of samples; headspace kept {retained * 100:.2f} % "
            f"after {cruise_days:.0f} days in vacuum; Earth air reaching a tube after {req.days_landing_to_opening:.0f} days "
            f"= {ingress:.1e} of its Martian gas",
        )
    )

    # --- SR-3 ascent -----------------------------------------------------------
    mav, asc = design_mav(MAV(payload=max(cache.os_mass, 16.0)))
    # Design iteration: run the baseline dispersions; if too many orbits fall below
    # the periapsis floor, apply the mitigation (motor-lot acceptance firing halves
    # the Isp uncertainty [estimate]) and re-run.
    iterations = []
    mc = None
    for label, isp_sigma in (("baseline, Isp 0.5 % 1-sigma", 0.005), ("mitigated, Isp 0.25 % 1-sigma", 0.0025)):
        mc = monte_carlo_ascent(mav, n=mc_runs, min_periapsis=req.min_os_periapsis_m, isp_sigma=isp_sigma)
        iterations.append((label, mc.success_fraction))
        if mc.success_fraction >= req.min_fraction_above_periapsis:
            break
    out["ascent"] = {"mav": mav, "nominal": asc, "monte_carlo": mc, "iterations": iterations}
    history = "; ".join(f"{lab}: {frac * 100:.1f} %" for lab, frac in iterations)
    gates.append(
        _gate(
            "SR-3",
            "Mars ascent",
            abs(asc.periapsis_alt - 380e3) < 10e3
            and mav.gross_mass <= req.mav_gross_max_kg
            and mc.success_fraction >= req.min_fraction_above_periapsis,
            f"MAV {mav.gross_mass:.0f} kg (stage-2 load {mav.stage2.propellant:.1f} kg, pitch rate {mav.pitch_rate:.3f} deg/s) "
            f"reaches {asc.periapsis_alt / 1e3:.0f} x {asc.apoapsis_alt / 1e3:.0f} km; ideal dv {asc.ideal_dv:.0f} m/s, "
            f"losses {asc.losses:.0f} m/s; Monte Carlo ({mc.n} runs) share with periapsis >= "
            f"{req.min_os_periapsis_m / 1e3:.0f} km: {history}",
        )
    )

    # --- SR-4 rendezvous and capture ---------------------------------------------
    miss, rng_m = cw_vs_nonlinear(MARS, 380e3, -10_000.0)
    a_ref = MARS.radius + 380e3
    e_mc = (mc.apoapsis_alt - mc.periapsis_alt) / (2 * MARS.radius + mc.apoapsis_alt + mc.periapsis_alt)
    rng = np.random.default_rng(7)
    di = np.radians(0.05) * rng.standard_normal(mc.n)  # launch-azimuth error [estimate]
    match = np.array([matching_dv(MARS, a_ref, a, e, d) for a, e, d in zip(mc.sma, e_mc, di)])
    appr = approach_monte_carlo(MARS, 380e3, n=max(2000, mc_runs * 5))
    dv_p99 = float(np.percentile(match, 99) + np.percentile(appr.dv, 99))
    out["rendezvous"] = {"cw_miss_m": miss, "match_dv": match, "approach": appr, "dv_p99": dv_p99}
    gates.append(
        _gate(
            "SR-4",
            "Rendezvous and capture",
            miss / rng_m < req.cw_error_frac_at_10km
            and appr.p_success >= req.min_p_capture
            and dv_p99 <= req.orbiter_rendezvous_dv_budget,
            f"CW hop from 10 km flown nonlinearly misses by {miss:.1f} m ({miss / rng_m * 100:.2f} %); "
            f"capture in {appr.p_success * 100:.2f} % of {appr.success.size} runs; orbit-matching + approach dv "
            f"p99 {dv_p99:.0f} m/s",
        )
    )

    # --- SR-5 Earth return ---------------------------------------------------------
    tei = burn_from_orbit(ret.vinf_depart, MARS, 380e3)
    v_entry = entry_speed(ret.vinf_arrive, EARTH, 125e3)
    best_entry = min(entry_speed(w.vinf_arrive, EARTH, 125e3) for w in ret_grid)
    out["return"] = {"tei_dv": tei, "entry_speed": v_entry, "min_entry_speed_in_window": best_entry}
    gates.append(
        _gate(
            "SR-5",
            "Earth return",
            v_entry <= req.max_entry_speed,
            f"Trans-Earth burn {tei:.0f} m/s from 380 km; entry {v_entry / 1e3:.2f} km/s at 125 km "
            f"(lowest in the window {best_entry / 1e3:.2f} km/s)",
        )
    )

    # --- SR-6 entry ------------------------------------------------------------------
    cond = EntryConditions(v_entry, req.gamma_entry_deg)
    nominal = simulate_entry(MSR_EEV, cond, keep_trajectory=True)
    check = EntryConditions(v_entry, -45.0, interface_alt=150e3, exponential=True)
    sim_chk = simulate_entry(MSR_EEV, check)
    ae_n, ae_q = allen_eggers(MSR_EEV, check)
    err_n = abs(sim_chk.peak_decel_g / ae_n - 1)
    err_q = abs(sim_chk.peak_heat_flux / ae_q - 1)
    stardust = simulate_entry(STARDUST, EntryConditions(12_900.0, -8.2))
    fp = footprint_monte_carlo(MSR_EEV, cond, n=mc_runs)
    out["entry"] = {
        "nominal": nominal,
        "allen_eggers_err": (err_n, err_q),
        "stardust": stardust,
        "footprint": fp,
    }
    fps = fp.summary()
    gates.append(
        _gate(
            "SR-6",
            "Earth entry",
            max(err_n, err_q) < req.ae_tol
            and fps["peak_heat_p99_W_cm2"] <= req.max_heat_flux_W_cm2
            and fps["downrange_3sigma_km"] <= req.max_downrange_3sigma_km,
            f"Allen-Eggers check: decel {err_n * 100:.1f} %, heat flux {err_q * 100:.1f} %; nominal peak "
            f"{nominal.peak_heat_flux / 1e4:.0f} W/cm2, {nominal.peak_decel_g:.0f} g, heat load {nominal.heat_load / 1e7:.1f} kJ/cm2; "
            f"3-sigma downrange {fps['downrange_3sigma_km']:.1f} km",
        )
    )

    # --- SR-7 impact --------------------------------------------------------------------
    ci = ContainmentInputs()
    gates.append(
        _gate(
            "SR-7",
            "Landing impact",
            fps["impact_g_p99"] <= ci.impact_rating_g,
            f"Ground impact {nominal.impact_speed:.1f} m/s; mean crush load p99 {fps['impact_g_p99']:.0f} g "
            f"vs {ci.impact_rating_g:.0f} g rating",
        )
    )

    # --- SR-8 containment ---------------------------------------------------------------
    cr = release_probability(ci, float(fp.impact_g.mean()), float(fp.impact_g.std()))
    out["containment"] = cr
    worst = max(cr.paths, key=cr.paths.get)
    gates.append(
        _gate(
            "SR-8",
            "Containment",
            cr.meets_requirement,
            f"P(release) {cr.total:.1e} vs {REQUIREMENT:.0e}; largest path: {worst} ({cr.paths[worst]:.1e})",
        )
    )

    out["targets"] = compare_targets(req.gamma_entry_deg)
    out["gates"] = gates
    return out
