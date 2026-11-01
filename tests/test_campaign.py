"""Fast checks of the campaign phase models against known values."""

import math
from datetime import date

import numpy as np
import pytest

from raptor_sim.campaign.ascent import booster_return, fly_ascent
from raptor_sim.campaign.bodies import earth_atmosphere, mars_atmosphere
from raptor_sim.campaign.burns import finite_departure
from raptor_sim.campaign.entry import EntryVehicle, fly_entry
from raptor_sim.campaign.interplanetary import kepler_propagate, lambert, planet_state, transfer
from raptor_sim.campaign.mars_ops import IsruPlant, isru_monte_carlo, mars_ascent
from raptor_sim.campaign.refill import RefillPlan, refill_monte_carlo
from raptor_sim.campaign.vehicle import Stack


def test_us76_reference_points():
    # US Standard Atmosphere 1976 tabulated values
    assert earth_atmosphere(0).density == pytest.approx(1.225, rel=1e-3)
    assert earth_atmosphere(11_000).pressure == pytest.approx(22_632, rel=5e-3)
    assert earth_atmosphere(30_000).density == pytest.approx(0.01841, rel=2e-2)


def test_mars_surface_density():
    assert 0.012 < mars_atmosphere(0).density < 0.022  # Viking / MGS range


def test_earth_orbit_and_lambert_round_trip():
    r, v = planet_state("earth", date(2028, 12, 1))
    assert np.linalg.norm(r) / 1.496e11 == pytest.approx(0.986, abs=0.01)
    assert np.linalg.norm(v) == pytest.approx(30_250, rel=0.01)
    tr = transfer("earth", "mars", date(2028, 12, 2), 320)
    r2, _ = kepler_propagate(tr.r_depart, tr.v_depart, 320 * 86400)
    rm, _ = planet_state("mars", tr.arrive)
    assert np.linalg.norm(r2 - rm) < 1e3


def test_2028_window_c3():
    # Published 2028 Earth-Mars minimum C3 is about 8-9 km2/s2 (NASA mission design handbooks)
    tr = transfer("earth", "mars", date(2028, 12, 2), 320)
    assert 8.0 < tr.c3 < 10.0


@pytest.fixture(scope="module")
def stack():
    return Stack(booster_reserve_fraction=0.14)


def test_cargo_ascent_reaches_orbit(stack):
    r = fly_ascent(stack, 100e3, 1.05)
    assert r.reached_orbit and r.ship_residual > 0
    assert abs(r.perigee_km - 300) < 5
    assert 20 < r.max_q_kpa < 40
    br = booster_return(stack, r)
    assert br.propellant_used <= br.reserve and br.touchdown_speed < 3 and br.miss_distance_m < 5_000


def test_tmi_gravity_loss_small(stack):
    b = finite_departure("earth", 3_000, stack.ship_dry + 100e3 + 1_000e3, stack.engine, 3)
    assert 0 < b.gravity_loss < 0.02 * b.impulsive_dv


def test_mars_ascent_delta_v(stack):
    r = mars_ascent(stack, 20e3, 800e3)
    assert r.reached_orbit
    assert 3_600 < r.dv_spent < 4_200  # literature range for Mars surface to low orbit


def test_mars_landing(stack):
    r = fly_entry("mars", 3_300, -12.0, EntryVehicle(mass=stack.ship_dry + 100e3 + 115e3), engine=stack.engine,
                  landing_propellant=115e3)
    assert not r.crashed and r.touchdown_speed < 3 and r.landing_propellant < 115e3
    assert r.peak_g < 5


def test_isru_energy_and_production():
    p = IsruPlant()
    assert 6.0 < p.kwh_per_kg_propellant() < 9.0
    res = isru_monte_carlo(p, 100e3, 380, n=50)
    assert res.p_success == 1.0


def test_refill_needs_enough_tankers():
    deliveries = np.full(10, 100e3)
    res = refill_monte_carlo(RefillPlan(launch_success=1.0, scrub_probability=0.0), date(2028, 11, 1), 40,
                             lambda day: 500e3, 0.0, deliveries, n=20)
    assert res.p_on_time == 1.0
    assert set(res.tankers_launched) == {6}  # 500 t / 98 t per tanker after transfer loss, plus boil-off
