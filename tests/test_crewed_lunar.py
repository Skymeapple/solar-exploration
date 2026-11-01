"""Verification of the crewed lunar models against cited data (reference.py)."""

import math

import pytest

from raptor_sim.crewed_lunar import architecture as arch
from raptor_sim.crewed_lunar import legs
from raptor_sim.crewed_lunar.landing import Lander, simulate_ascent, simulate_descent
from raptor_sim.crewed_lunar.reference import APOLLO_LM as LM
from raptor_sim.crewed_lunar.reference import EARTH_RETURN, ORION, STARSHIP_HLS, TRAJECTORY


@pytest.fixture(scope="module")
def apollo():
    lm = Lander("LM", LM["total_wet"].value, LM["dps_thrust"].value, LM["dps_isp"].value, LM["dps_throttle_min"].value)
    asc = Lander("APS", LM["ascent_wet"].value, LM["aps_thrust"].value, LM["aps_isp"].value, 1.0)
    return simulate_descent(lm), simulate_ascent(asc)


@pytest.fixture(scope="module")
def architectures():
    return arch.run_all()


# Legs

def test_tli_and_transfer_time_match_textbook():
    assert legs.tli_dv() == pytest.approx(3_108, abs=15)
    assert 4.5 < legs.tli_transfer_days() < 5.5


def test_entry_speed_matches_artemis_ii():
    cited = EARTH_RETURN["artemis2_entry_speed"].value
    assert legs.earth_entry_speed() == pytest.approx(cited, rel=0.02)


def test_lunar_gravity():
    assert legs.G_MOON == pytest.approx(1.62, abs=0.01)


# Landing simulation against Apollo

def test_apollo_descent_fits_inside_lm_capability(apollo):
    d, _ = apollo
    assert 1_850 < d.total_dv < LM["descent_dv_capability"].value
    assert d.propellant < LM["descent_propellant"].value
    assert d.hover_capable  # the DPS throttles to 10%
    assert d.gravity_loss > 0


def test_apollo_ascent_fits_inside_lm_capability(apollo):
    _, a = apollo
    assert 1_780 < a.total_dv < LM["ascent_dv_capability"].value
    assert a.propellant < LM["ascent_propellant"].value
    assert 350 < a.burn_time < 470  # Apollo ascent burns ran about 7 minutes


def test_descent_reaches_gate(apollo):
    d, _ = apollo
    t = d.trajectory
    assert t["alt_m"][-1] == pytest.approx(150.0, abs=5.0)
    assert t["speed_m_s"][-1] == pytest.approx(3.0, abs=0.5)
    assert min(t["alt_m"]) > 0


def test_ascent_reaches_target_orbit(apollo):
    _, a = apollo
    assert a.trajectory["alt_m"][-1] == pytest.approx(15_240, abs=50)


def test_underpowered_lander_is_rejected():
    weak = Lander("weak", 15_000, 3_000, 311, 0.1)  # thrust-to-weight 0.12 in lunar gravity
    with pytest.raises(ValueError):
        simulate_descent(weak)


# Architectures

def test_orion_can_use_nrho_but_not_llo(architectures):
    cap = ORION["dv_after_upper_stage_sep"].value
    assert TRAJECTORY["nrho_loi_plus_tei"].value <= cap
    assert not architectures["B"].feasible
    assert 2 * legs.lunar_orbit_insertion_dv() > cap


def test_nrho_architecture_tanker_count_inside_cited_range(architectures):
    a = architectures["A"]
    low = STARSHIP_HLS["tanker_flights_low"].value
    high = STARSHIP_HLS["tanker_flights_high"].value
    assert low <= a.tanker_launches <= high
    # The lighter landers close inside the 1,600 t tank; 120 t is marginal.
    light = arch.nrho_hls(arch.LunarAssumptions(hls_dry_t=100.0))
    assert light.feasible


def test_lander_descent_uses_simulated_dv(architectures):
    a = architectures["A"]
    assert 1_850 < a.descent.total_dv < 2_200
    assert a.descent.hover_capable  # on its landing thrusters


def test_raptor_alone_cannot_hover(architectures):
    from raptor_sim.engine import size_engine
    from raptor_sim.mission import Vehicle
    from raptor_sim.crewed_lunar.reference import RAPTOR

    sl = size_engine(Vehicle().engine)
    m = architectures["A"].descent.landed_mass
    assert RAPTOR["throttle_min"].value * sl.thrust_vac > m * legs.G_MOON


def test_direct_ship_needs_lunar_orbit_refill(architectures):
    c = architectures["C"]
    assert not c.feasible
    assert c.propellant_in_leo_t > 1_600


def test_hydrolox_isru_needs_no_earth_propellant(architectures):
    h = architectures["D_hydrolox"]
    m = architectures["D_methane"]
    assert h.from_earth_t == 0
    assert m.from_earth_t > 0
    assert m.earth_launches_per_sortie < architectures["A"].total_launches


def test_heavier_lander_needs_more_tankers():
    light = arch.nrho_hls(arch.LunarAssumptions(hls_dry_t=100.0))
    heavy = arch.nrho_hls(arch.LunarAssumptions(hls_dry_t=140.0))
    assert heavy.tanker_launches > light.tanker_launches


# Earth return

def test_lunar_return_corridor_and_heating():
    from raptor_sim.crewed_lunar.earth_return import earth_return_checks

    d = earth_return_checks()["data"]
    for name, v in d["vehicles"].items():
        assert v["corridor"]["width_deg"] > 0.5, name
        assert v["lunar"]["peak_g"] < 5.0
        assert not v["lunar"]["skipped"]
        assert v["lunar"]["peak_total_w_cm2"] > 3 * v["leo"]["peak_total_w_cm2"]
        assert v["lunar"]["peak_rad_w_cm2"] > 0  # radiative heating appears above about 10 km/s


def test_surface_cases_stay_inside_career_dose_limit():
    from raptor_sim.crewed_lunar.surface import surface_cases

    cases = surface_cases()
    assert all(c["career_fraction"] < 1.0 for c in cases)
    assert cases[-1]["dose_msv"] > cases[0]["dose_msv"]


def test_lunar_base_constants_agree_if_present():
    orbits = pytest.importorskip("raptor_sim.lunar_base.orbits")
    v = orbits.LEGS["leo_to_tli"].value if "leo_to_tli" in orbits.LEGS else None
    if v is None:
        pytest.skip("leg key differs")
    assert v == pytest.approx(legs.tli_dv(), rel=0.01)
