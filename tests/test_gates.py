import math

import pytest

from raptor_sim import CycleAssumptions, EngineDesign, run_all_gates, size_engine, solve_cycle
from raptor_sim import thermo


@pytest.fixture(scope="module")
def reference():
    return run_all_gates()


def test_reference_design_passes_every_gate_that_runs(reference):
    _perf, _cycle, results = reference
    ran = [r for r in results if r.passed is not None]
    assert [r.gate.split()[0] for r in ran] == ["G1", "G2", "G3", "G7"]
    failed = [f"{r.gate}: {r.detail}" for r in ran if not r.passed]
    assert not failed, failed


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
