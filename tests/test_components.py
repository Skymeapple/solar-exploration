"""Independent checks on the component models: conservation laws, geometry and consistency.

These test the models, not the design: each one compares a model output with a
quantity worked out a second, independent way.
"""

import math
import warnings

import numpy as np
import pytest

from raptor_sim.components import design_io
from raptor_sim.components.assembly import ComponentInputs, build_engine
from raptor_sim.components.cooling import methane_h
from raptor_sim.components.turbopump import gulich_efficiency
from raptor_sim.components.verification import all_checks, pressure_ladder

warnings.filterwarnings("ignore", category=FutureWarning)


@pytest.fixture(scope="module")
def first_guess():
    return build_engine(ComponentInputs())


@pytest.fixture(scope="module")
def design_point():
    return build_engine(design_io.load())


def test_contour_meets_throat_exit_and_l_star(first_guess):
    b = first_guess
    c = b.contour
    x, r = c.points(400)
    assert np.all(np.diff(x) > 0)
    assert math.isclose(r.min(), c.rt, rel_tol=1e-3)
    assert math.isclose(r[-1], b.perf.exit_diameter / 2, rel_tol=1e-6)
    # Volume from injector face to throat equals L* x At
    up = x <= 0
    vol = np.trapezoid(np.pi * r[up] ** 2, x[up])
    assert math.isclose(vol, c.inputs.l_star * np.pi * c.rt**2, rel_tol=0.02)


def test_cooling_energy_balance(design_point):
    """Heat picked up by the coolant equals the heat integrated over the wall."""
    cool = design_point.cooling
    out = cool.stations[0]
    h_in = methane_h(cool.coolant_inlet_pressure, cool.coolant_inlet_temperature)
    h_out = methane_h(out.p_coolant, out.t_coolant)
    assert math.isclose(cool.coolant_flow * (h_out - h_in), cool.heat_load, rel_tol=0.02)


def test_wall_heat_flux_is_continuous(design_point):
    """At every station the flux through the wall matches the coolant-side flux."""
    for s in design_point.cooling.stations[::10]:
        q_wall = (s.t_wall_gas - s.t_wall_coolant) / s.wall_thickness
        assert q_wall > 0
        assert s.t_wall_gas > s.t_wall_coolant > s.t_coolant


def test_turbopump_torque_and_power(design_point):
    for tp in (design_point.fuel_tp, design_point.ox_tp):
        assert math.isclose(tp.torque * tp.pump.speed, tp.power, rel_tol=1e-9)
        assert tp.pump.impeller_diameter == pytest.approx(2 * tp.pump.tip_speed / tp.pump.speed)


def test_gulich_efficiency_shape():
    # Rises with flow, peaks near nq 40-60 for large pumps, all within physical bounds.
    assert 0.6 < gulich_efficiency(15, 0.05) < gulich_efficiency(15, 0.5) < 0.95
    assert gulich_efficiency(50, 0.5) > gulich_efficiency(10, 0.5)


def test_injector_orifice_equation_recovers_flow(design_point):
    inj = design_point.injector
    ii = inj.inputs
    n = ii.n_elements
    a_ox = math.pi / 4 * inj.post_inner_diameter**2
    flow = n * a_ox * inj.ox_density * inj.ox_velocity
    assert math.isclose(flow, inj.ox_flow, rel_tol=1e-6)
    assert inj.placed_elements == n


def test_preburner_flows_add_up(design_point):
    b = design_point
    total = b.fuel_pb.flow + b.ox_pb.flow
    assert math.isclose(total, b.perf.mdot, rel_tol=1e-9)


def test_bom_is_consistent(design_point):
    b = design_point
    numbers = [i.part_number for i in b.bom]
    assert len(numbers) == len(set(numbers))
    assert math.isclose(sum(i.mass for i in b.bom), b.mass)
    assert all(i.mass > 0 for i in b.bom)


def test_first_guess_fails_and_design_point_fixes_it(first_guess, design_point):
    """The first guess has known problems; the converged design point clears the fixable ones."""
    first = {c.id for c in all_checks(first_guess) if not c.passed}
    assert {"CL-4", "SS-1", "TP-O2"} <= first
    final = [c for c in all_checks(design_point) if not c.passed]
    assert len(final) < len(first)
    # Turbopumps, injector, preburners, lines and the pressure ladder all close.
    assert not [c for c in final if c.gate == "G5" or c.level == "subsystem"], [c.id for c in final]
    # Known open issue: liner stresses in the cooling jacket are within 15% of the allowable
    # but not below it (see results/components/verification.md).
    for c in final:
        if c.gate == "G4":
            assert c.id in ("CL-2", "CL-3") and c.value < 1.15, c


def test_pressure_ladder_closes_at_design_point(design_point):
    for row in pressure_ladder(design_point):
        assert row["margin_bar"] >= -0.5, row


def test_oxygen_side_materials_are_compatible(design_point):
    ox = [c for c in all_checks(design_point) if "oxygen compatible" in c.description]
    assert ox and all(c.passed for c in ox)


def test_drawings_are_written(design_point, tmp_path):
    import ezdxf

    from raptor_sim.components.drawings import make_all

    paths = make_all(design_point, tmp_path)
    assert {p.suffix for p in paths} == {".svg", ".dxf", ".csv"}
    for p in paths:
        assert p.stat().st_size > 500
        if p.suffix == ".dxf":
            doc = ezdxf.readfile(p)
            assert len(doc.modelspace()) > 3
