import math

import pytest

from raptor_sim import CycleAssumptions, EngineDesign, run_all_gates, size_engine, solve_cycle
from raptor_sim import thermo


@pytest.fixture(scope="module")
def reference():
    return run_all_gates()


# The selected design point (295 bar, the highest chamber pressure that passes every
# check) clears every gate. At 300 bar G4 and G6 fail: see the chamber pressure sweep in
# results/components/verification.md.
KNOWN_OPEN: set[str] = set()


def test_reference_design_gates(reference):
    _perf, _cycle, results = reference
    assert [r.gate.split()[0] for r in results] == ["G0", "G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert all(r.passed is not None for r in results)
    failed = {r.gate.split()[0]: r.detail for r in results if not r.passed}
    assert set(failed) <= KNOWN_OPEN, failed


def test_selected_design_is_the_component_design_point(reference):
    perf, _cycle, _results = reference
    assert perf.design.pc < 300e5  # 300 bar does not close; see the chamber pressure sweep
    assert perf.design.pc >= 285e5  # G7 keeps chamber pressure within 5% of the public figure


def test_cea_matches_cantera_within_one_percent():
    gas = thermo.chamber(300e5, 3.6)
    t, mw = thermo.cantera_chamber(300e5, 3.6)
    assert math.isclose(t, gas.temperature, rel_tol=0.01)
    assert math.isclose(mw, gas.molecular_weight, rel_tol=0.01)


def test_thrust_equals_flow_times_isp(reference):
    perf, _cycle, _results = reference
    assert math.isclose(perf.mdot * perf.isp_sl * 9.80665, perf.design.thrust_sl, rel_tol=1e-9)
    assert perf.isp_vac > perf.isp_sl


def test_flow_split_conserves_mass(reference):
    perf, cycle, _results = reference
    total = cycle.fuel_shaft.turbine_flow + cycle.ox_shaft.turbine_flow
    assert math.isclose(total, perf.mdot, rel_tol=1e-9)


def test_overexpanded_nozzle_fails_g3():
    from raptor_sim.gates import gate_g3

    perf = size_engine(EngineDesign(eps=150.0))
    result = gate_g3(perf)
    assert perf.separation_margin < 1.0
    assert result.passed is False


def test_cycle_does_not_close_with_poor_turbomachinery():
    perf = size_engine(EngineDesign())
    weak = CycleAssumptions(eta_turbine_ox=0.2, eta_turbine_fuel=0.2, eta_pump_ox=0.3, eta_pump_fuel=0.3)
    cycle = solve_cycle(perf, weak)
    assert not cycle.closed
