import math

import pytest

from raptor_sim.mission import (
    A_EARTH,
    A_MARS,
    MU_EARTH,
    R_EARTH,
    Vehicle,
    burn_from_orbit,
    hohmann_vinf,
    mars_mission,
    vehicle_performance,
)
from raptor_sim.optimize import evaluate, optimize

REFERENCE = {"pc_bar": 300.0, "mixture_ratio": 3.6, "eps": 34.34, "t_ox_rich_pb": 800.0, "t_fuel_rich_pb": 1000.0}


def test_reference_design_is_feasible():
    t = evaluate(REFERENCE)
    assert t.feasible, t.reason


def test_wide_nozzle_is_rejected():
    t = evaluate({**REFERENCE, "eps": 60.0})
    assert not t.feasible
    assert "package" in t.reason


def test_optimizer_finds_a_feasible_design_at_least_as_good_as_reference(tmp_path):
    best, trials = optimize(n_trials=60, seed=1, log_path=tmp_path / "log.csv")
    assert best is not None and best.feasible
    assert len(trials) == 60
    assert (tmp_path / "log.csv").read_text().count("\n") == 61
    assert best.objective >= evaluate(REFERENCE).objective - 1.0


def test_hohmann_earth_mars_matches_textbook():
    vinf_dep, vinf_arr, days = hohmann_vinf(A_EARTH, A_MARS)
    assert vinf_dep == pytest.approx(2945, abs=10)
    assert vinf_arr == pytest.approx(2649, abs=10)
    assert days == pytest.approx(259, abs=1)
    # Classic figure: about 3.6 km/s from a 300 km parking orbit.
    assert burn_from_orbit(vinf_dep, MU_EARTH, R_EARTH + 300e3) == pytest.approx(3590, abs=30)


def test_heavier_ship_carries_less_and_needs_more_tankers():
    light = Vehicle(ship_dry_t=100.0)
    heavy = Vehicle(ship_dry_t=150.0)
    assert vehicle_performance(heavy).payload_to_leo_t < vehicle_performance(light).payload_to_leo_t
    assert mars_mission(heavy).tanker_flights > mars_mission(light).tanker_flights


def test_mars_mission_closes_for_reference_vehicle():
    r = mars_mission()
    assert r.meets_requirement
    assert math.isfinite(r.isru_propellant_t)
