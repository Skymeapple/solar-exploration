"""Tests for the crewed mission models (raptor_sim.crew)."""

import math

import pytest

from raptor_sim.crew import aborts as AB
from raptor_sim.crew import entry as E
from raptor_sim.crew import gravity as GR
from raptor_sim.crew import life_support as LS
from raptor_sim.crew import propulsion as PR
from raptor_sim.crew import radiation as RAD
from raptor_sim.crew.transfers import conjunction_class, trip_time_trade
from raptor_sim.crew.verification import run_all


def test_all_verification_items_pass():
    failed = [c.id for c in run_all() if not c.passed]
    assert not failed, failed


def test_radiation_reproduces_rad_anchors():
    assert RAD.gcr_rate(RAD.RAD_CRUISE_SHIELD, solar="rad2012") == pytest.approx(RAD.RAD_CRUISE_MSV_D, rel=1e-6)
    assert RAD.gcr_rate(0.0, solar="rad2012", environment="mars_surface") == pytest.approx(
        RAD.RAD_MARS_SURFACE_MSV_D, rel=1e-6)


def test_hydrogen_rich_shielding_beats_aluminium():
    assert RAD.gcr_rate(30, "polyethylene") < RAD.gcr_rate(30, "water") < RAD.gcr_rate(30, "aluminum")


def test_conjunction_mars_mission_exceeds_career_limit_at_solar_min():
    d = RAD.mission_dose(460, 480, "mars_surface", hull_gcm2=20, solar="min")
    assert d.total_msv > RAD.CAREER_LIMIT_MSV


def test_life_support_closed_loop_is_lighter_for_long_missions():
    assert LS.consumables(6, 950, "iss").total_kg < LS.consumables(6, 950, "open").total_kg
    assert LS.consumables(4, 30, "open").total_kg < LS.consumables(4, 30, "iss").total_kg
    assert 100 < LS.break_even_days(6, "iss") < 500


def test_oxygen_runs_out_without_reserve_during_outage():
    h = LS.simulate_stocks(6, 200, "iss", o2_reserve=50.0, failures=((50, 30, "oga"),))
    assert h.ran_out


def test_entry_corridor_narrows_with_speed():
    w = [E.entry_corridor(E.CAPSULE_ORION_CLASS, "earth", v, 5.0).width_deg for v in (11_000, 14_000)]
    assert w[0] > w[1] > 0


def test_lift_reduces_peak_g():
    base = E.simulate_entry(E.EntryVehicle("b", 9300, 19.6, 1.3, 0.0, 6), "earth", 11_000, -6.0)
    lift = E.simulate_entry(E.CAPSULE_ORION_CLASS, "earth", 11_000, -6.0, bank=0.0)
    assert lift.peak_g < base.peak_g


def test_trip_time_trade_monotonic_in_energy():
    t = trip_time_trade(tofs=range(100, 201, 50))
    assert t[0].tmi_dv > t[-1].tmi_dv
    assert t[0].arrival_entry_speed > t[-1].arrival_entry_speed


def test_conjunction_class_is_long_stay():
    rt = conjunction_class()
    assert rt.stay_days > 300 and 800 < rt.total_days < 1100
    assert rt.earth_entry_speed < 12_500


def test_abort_from_early_outbound_costs_more_than_two_km_s():
    rt = conjunction_class()
    pts = AB.trans_mars_abort(rt.outbound, dv_budget=2_000, max_return_days=400, step=30)
    assert AB.coverage(pts) == 0.0
    assert pts[0].best_dv > 2_000


def test_spin_radius_formula():
    s = GR.spin_design(1.0, 2.0)
    assert s.radius_m == pytest.approx(9.80665 / (2 * math.pi * 2 / 60) ** 2)


def test_ntp_lighter_than_chemical_for_high_dv():
    assert PR.stage_mass(PR.NTP_LH2, 100, 8000)[1] < PR.stage_mass(PR.CHEM_CH4, 100, 8000)[1]


def test_nep_more_power_is_faster():
    slow = PR.nep_trip(PR.NEPSystem("a", 2, 20, 4000, 0.6), 80)
    fast = PR.nep_trip(PR.NEPSystem("b", 10, 5, 4000, 0.6), 80)
    assert fast.trip_days < slow.trip_days
