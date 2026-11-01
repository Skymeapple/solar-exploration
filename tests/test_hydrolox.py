"""Hydrogen/oxygen engine model: gates H1-H4, H7 and the lunar study hand-off."""

import pytest

from raptor_sim.hydrolox import STUDY_ISP_S, cycles, design, gates
from raptor_sim.hydrolox.benchmarks import RL10B_2, RS_25, VINCI
from raptor_sim.hydrolox.engine import reference_design, size


def test_h1_thermochemistry():
    assert gates.gate_h1().passed


def test_h2_cycle_balance():
    g = gates.gate_h2()
    assert g.passed, g.detail


def test_h3_performance():
    g = gates.gate_h3()
    assert g.passed, g.detail


def test_rs25_calibration_exact():
    assert size(reference_design(RS_25)).isp_vac == pytest.approx(RS_25.isp_vac, rel=1e-6)


def test_expander_wall_falls_with_thrust():
    small = design.expander_wall(44e3, 6.0, 100)
    large = design.expander_wall(250e3, 6.0, 100)
    assert small > large
    assert design.expander_wall(VINCI.thrust_vac, VINCI.mixture_ratio, VINCI.eps) == pytest.approx(60, rel=0.10)


def test_heat_margin_sign():
    a = design.expander_assumptions()
    assert cycles.heat_margin(size(reference_design(RL10B_2)), a) > 0.15
    past_wall = size(design.design(90e5, 6.0, 100, 250e3))
    assert cycles.heat_margin(past_wall, a) < 0


def test_design_points_and_handoff():
    rep = gates.run_all(n_trials=40)
    assert all(g.passed is not False for g in rep.gates), [g for g in rep.gates if g.passed is False]
    for key, name in (("HL-44", "HL-44"), ("HL-250", "HL-250 (expander)")):
        # pinned study value stays within 1 s of a fresh 40-trial search
        assert rep.points[name]["isp_vac_for_studies_s"] == pytest.approx(STUDY_ISP_S[key], abs=1.5)


def test_lunar_studies_use_model():
    from raptor_sim.crewed_lunar.architecture import LunarAssumptions
    from raptor_sim.lunar_base import depot

    assert depot.hydrolox_isp() == STUDY_ISP_S["HL-250"]
    assert LunarAssumptions().hydrolox_isp == STUDY_ISP_S["HL-44"]
