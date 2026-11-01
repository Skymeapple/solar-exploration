"""Unit and verification tests for the sample return models (no RocketCEA needed)."""

import math

import numpy as np
import pytest

from sample_return.ascent import MAV, design_mav, simulate_ascent
from sample_return.bodies import AU, DAY, EARTH, MARS, MU_SUN, date_from_jd, jd_from_date, planet_state
from sample_return.collection import SealDesign, earth_air_ingress, headspace_retained
from sample_return.containment import ContainmentInputs, p_overload, release_probability
from sample_return.entry import MSR_EEV, STARDUST, EntryConditions, allen_eggers, simulate_entry
from sample_return.rendezvous import approach_monte_carlo, cw_stm, cw_two_impulse, cw_vs_nonlinear
from sample_return.transfer import hohmann_vinf, lambert, propagate, search_window


def test_julian_date_roundtrip():
    jd = jd_from_date(2000, 1, 1.5)
    assert jd == pytest.approx(2_451_545.0)
    assert date_from_jd(jd_from_date(2031, 8, 29)) == "2031-08-29"


def test_planet_state_radius_and_speed():
    r, v = planet_state("Earth", jd_from_date(2030, 1, 1))
    assert np.linalg.norm(r) / AU == pytest.approx(1.0, abs=0.02)
    assert np.linalg.norm(v) == pytest.approx(29_780, rel=0.03)


def test_lambert_matches_propagation():
    r1, _ = planet_state("Mars", jd_from_date(2030, 10, 1))
    r2, _ = planet_state("Earth", jd_from_date(2031, 8, 20))
    tof = (jd_from_date(2031, 8, 20) - jd_from_date(2030, 10, 1)) * DAY
    v1, v2 = lambert(r1, r2, tof)
    r2p, v2p = propagate(r1, v1, tof)
    assert np.linalg.norm(r2p - np.asarray(r2)) < 100.0
    assert np.linalg.norm(v2p - v2) < 1e-3


def test_lambert_hohmann_limit():
    a1, a2 = AU, 1.523679 * AU
    vd, _, tof = hohmann_vinf(a1, a2)
    th = math.radians(179.9)
    v1, _ = lambert([a1, 0, 0], [a2 * math.cos(th), a2 * math.sin(th), 0], tof)
    vinf = np.linalg.norm(v1 - np.array([0, math.sqrt(MU_SUN / a1), 0]))
    assert vinf == pytest.approx(vd, rel=1e-3)


def test_2028_window_matches_tianwen3_window():
    # Tianwen-3 plans to use the Dec 2028 - Jan 2029 window [cited]; ours should be close.
    w, _ = search_window("Earth", "Mars", (2028, 9, 1), 240, (150, 330), weight_arrival=0.3, step_days=6)
    assert w.depart_date[:4] == "2028" and w.depart_date[5:7] in ("10", "11", "12")
    assert w.c3_depart < 15.0


def test_mav_design_closes_inside_public_mass():
    mav, res = design_mav(MAV(payload=16.0))
    assert abs(res.periapsis_alt - 380e3) < 10e3
    assert abs(res.apoapsis_alt - 380e3) < 10e3
    assert 300 < mav.gross_mass < 450  # public range 350-450 kg [cited], allowing a lighter design
    assert 3_900 < res.ideal_dv < 4_600


def test_mav_energy_bookkeeping():
    mav, res = design_mav(MAV(payload=16.0))
    # delivered dv cannot exceed the rocket-equation total
    assert res.delivered_dv < res.ideal_dv
    assert 300 < res.losses < 1_200


def test_cw_stm_composition():
    n = 1e-3
    a = cw_stm(n, 300.0) @ cw_stm(n, 500.0)
    np.testing.assert_allclose(a, cw_stm(n, 800.0), atol=1e-9)


def test_cw_two_impulse_reaches_target():
    n = 1e-3
    r0, rf = np.array([0.0, -1000.0, 50.0]), np.zeros(3)
    v0p, _ = cw_two_impulse(n, r0, np.zeros(3), rf, 2000.0)
    end = cw_stm(n, 2000.0) @ np.concatenate([r0, v0p])
    np.testing.assert_allclose(end[:3], rf, atol=1e-6)


def test_cw_matches_nonlinear_within_one_percent():
    miss, rng = cw_vs_nonlinear(MARS, 380e3, -10_000.0)
    assert miss / rng < 0.01


def test_capture_monte_carlo():
    res = approach_monte_carlo(MARS, 380e3, n=400)
    assert res.p_success > 0.99
    assert np.percentile(res.dv, 99) < 20.0


@pytest.mark.parametrize("gamma", [-30.0, -45.0, -60.0])
def test_entry_matches_allen_eggers(gamma):
    cond = EntryConditions(11_800.0, gamma, interface_alt=150e3, exponential=True)
    sim = simulate_entry(MSR_EEV, cond)
    n_ae, q_ae = allen_eggers(MSR_EEV, cond)
    assert sim.peak_decel_g == pytest.approx(n_ae, rel=0.03)
    assert sim.peak_heat_flux == pytest.approx(q_ae, rel=0.03)


def test_stardust_reference_case():
    r = simulate_entry(STARDUST, EntryConditions(12_900.0, -8.2))
    # Order-of-magnitude reference: published peak heating about 1 kW/cm2 [memory];
    # our convective-only model should land within -40 % / +20 %.
    assert 600 < r.peak_heat_flux / 1e4 < 1_200
    assert 20 < r.peak_decel_g < 50


def test_eev_impact_speed_is_terminal_velocity():
    r = simulate_entry(MSR_EEV, EntryConditions(11_900.0, -10.5))
    vt = math.sqrt(2 * MSR_EEV.mass * 9.80665 / (1.225 * MSR_EEV.cd_subsonic * MSR_EEV.area))
    assert r.impact_speed == pytest.approx(vt, rel=0.05)


def test_seal_models_monotone():
    s = SealDesign()
    assert headspace_retained(s, 100) > headspace_retained(s, 1000)
    assert earth_air_ingress(s, 60) > earth_air_ingress(s, 30) * 3.9  # grows with t^2
    leaky = SealDesign(tube_leak_he=1e-7, cv_leak_he=1e-6)
    assert earth_air_ingress(leaky, 60) > 1e-2


def test_containment_fault_tree():
    ci = ContainmentInputs()
    assert p_overload(250, 20, 400) < 1e-10
    r = release_probability(ci, 250, 20)
    assert r.meets_requirement
    worse = release_probability(ContainmentInputs(p_sterilisation_failure=1e-2), 250, 20)
    assert not worse.meets_requirement
