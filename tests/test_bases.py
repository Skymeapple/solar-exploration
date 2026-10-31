"""Checks for the transit-base models (raptor_sim.bases)."""

import math

import pytest

from raptor_sim.bases import (
    SITES, Ship, base_buildup, best_power, build_network, capability_matrix, isru_plan,
    leg_dv, rank_sites, stepping_stone_routes,
)
from raptor_sim.bases.isru import sabatier_mass_balance
from raptor_sim.bases.logistics import simulate_refill
from raptor_sim.bases.power import fission_mass_kg
from raptor_sim.bases.ranking import SETTLEMENT_WEIGHTS


@pytest.fixture(scope="module")
def net():
    return build_network(Ship())


@pytest.fixture(scope="module")
def routes(net):
    return stepping_stone_routes(net)


def test_every_value_has_a_basis_tag():
    for s in SITES.values():
        for field, tag in s.basis.items():
            assert tag.split(":")[0] in ("cited", "literature", "estimate"), (s.key, field, tag)


def test_body_constants():
    assert SITES["phobos"].v_escape == pytest.approx(11.3, abs=0.5)  # m/s
    assert SITES["callisto"].v_escape == pytest.approx(2_440, rel=0.01)
    assert SITES["titan"].surface_g == pytest.approx(1.35, rel=0.01)
    assert SITES["callisto"].solar_flux == pytest.approx(1361 / 5.2044**2, rel=1e-6)


def test_sabatier_conserves_elements():
    for v in sabatier_mass_balance().values():
        assert abs(v) < 1e-6


def test_isru_chains_follow_resources():
    assert isru_plan(SITES["mars_arcadia"]).best.name == "sabatier"
    assert isru_plan(SITES["titan"]).best.name == "native_ch4"
    moon = isru_plan(SITES["moon_south_pole"]).best
    assert moon.name.startswith("o2_") and moon.local_fraction == pytest.approx(3.6 / 4.6)
    # Mars propellant energy lies in the published 5-20 MWh/t band
    assert 5_000 < isru_plan(SITES["mars_arcadia"]).best.energy_kwh_per_t < 20_000


def test_fission_reference_point():
    assert fission_mass_kg(40.0) == pytest.approx(6_000.0)
    assert best_power(SITES["titan"], 100).kind == "fission"  # no useful sunlight at Titan


def test_known_delta_v_values():
    leo_mars = leg_dv("leo", "mars_arcadia")
    assert leo_mars.dv_space / 1.10 == pytest.approx(3_600, rel=0.03)  # Hohmann TMI from 300 km
    assert leo_mars.tof_days == pytest.approx(259, abs=2)
    moon = leg_dv("leo", "moon_south_pole")
    assert 5_500 < moon.dv_total < 6_300  # LEO to lunar surface
    assert leg_dv("leo", "titan").tof_days / 365.25 == pytest.approx(6.05, abs=0.1)


def test_ship_matches_mission_model():
    from raptor_sim.mission import mars_mission

    ship = Ship.from_engine_model()
    leg = leg_dv("leo", "mars_arcadia")
    assert ship.payload(leg.dv_space, leg.dv_surface) == pytest.approx(mars_mission().cargo_max_t, rel=0.01)


def test_hubs_open_the_outer_system(net, routes):
    assert net.payload[("leo", "ceres")] < 0  # cannot be flown from LEO in one hop
    assert routes["ceres"].cargo_t > 100 and "phobos" in routes["ceres"].path
    assert routes["callisto"].cargo_t > 0
    assert routes["mercury_north_pole"].cargo_t == 0  # needs gravity assists or high-Isp stages


def test_refill_meets_martian_window():
    s = SITES["mars_arcadia"]
    sim = simulate_refill(s, 2_000.0, 1_600.0, 780.0)
    assert sim.meets_window and sim.boiloff_t > 0


def test_buildup_counts(net, routes):
    phases = base_buildup(SITES["titan"], net, routes)
    assert [p.phase for p in phases] == ["outpost", "base", "city"]
    assert phases[0].earth_launches < phases[0].earth_launches_direct  # hubs save launches


def test_rankings(net, routes):
    hub = rank_sites(net, routes, n_mc=500)
    assert hub[-1].site in ("venus_clouds", "mercury_north_pole")
    assert sum(s.p_top3_mc for s in hub) == pytest.approx(3.0)
    sett = rank_sites(net, routes, n_mc=500, weights=SETTLEMENT_WEIGHTS, gate=False)
    assert {s.site for s in sett[:3]} & {"mars_arcadia", "venus_clouds", "titan"}


def test_capability_matrix(routes):
    m = capability_matrix(routes)
    assert all(m["ch4_engine"].values())
    assert m["hydrocarbon_handling"]["titan"] and sum(m["hydrocarbon_handling"].values()) == 1
