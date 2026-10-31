"""Roadmap model checks: network, windows, Monte Carlo, logistics."""
import random
from datetime import date

import pytest

from raptor_sim.roadmap import logistics as L
from raptor_sim.roadmap.catalog import KEY_MILESTONES, STEPS, Step, build_program
from raptor_sim.roadmap.montecarlo import mode_plan, run_monte_carlo, sample_run, spread
from raptor_sim.roadmap.options import RECOMMENDED, apply
from raptor_sim.roadmap.schedule import WINDOWS, forward_pass, next_window, to_date, total_float
from raptor_sim.roadmap.sources import MARS_SYNODIC_D


def test_synodic_period():
    assert MARS_SYNODIC_D == pytest.approx(779.9, abs=0.2)


def test_network_is_valid_and_every_capability_used_or_terminal():
    prog = build_program()
    assert len(prog.order) == len(STEPS)
    used = {c for s in STEPS for c in s.needs + s.benefits}
    unused = set(prog.provider) - used
    assert unused <= {"self_sufficiency"}


def test_missing_capability_raises():
    with pytest.raises(ValueError):
        build_program(STEPS + [Step("X", "x", "P0", "tech", (1, 1, 1), (1, 1, 1), needs=("warp",))])


def test_window_gating():
    first, period, length = WINDOWS["mars"]
    assert next_window("mars", first - 1.0) == first
    assert next_window("mars", first + 0.5) == first + 0.5
    assert next_window("mars", first + length + 0.1) == pytest.approx(first + period)
    # PR #4 launch (2028-11-24) and return departure (2030-10-07) fall inside windows
    w = first + period
    assert to_date(w) <= date(2028, 11, 24) <= to_date(w + length)
    r = next_window("mars_return", w)
    assert to_date(r) <= date(2030, 10, 7) <= to_date(r + WINDOWS["mars_return"][2])
    assert to_date(first + 3 * period).year == 2033


def test_predecessors_finish_before_start():
    prog = build_program()
    tm = forward_pass(prog, mode_plan(prog)[0])
    for sid, preds in prog.preds.items():
        for p in preds:
            assert tm[p].finish <= tm[sid].start + 1e-9


def test_mission_failure_moves_to_next_window():
    prog = build_program()
    d = mode_plan(prog)[0]
    a = forward_pass(prog, d)
    b = forward_pass(prog, d, fail={"MARS-CARGO-1": 1})
    assert b["MARS-CARGO-1"].start - a["MARS-CARGO-1"].start == pytest.approx(WINDOWS["mars"][1], abs=0.01)


def test_float_window_lumpy():
    prog = build_program()
    d = mode_plan(prog)[0]
    fl = total_float(prog, d, ["MARS-CREW-1"], cap=30)
    assert fl["MARS-CREW-1"] == 0
    # Steps upstream of a window can slip until the window, off-path steps much more
    assert fl["ORBITAL-1"] < fl["MSR-MAV"]


def test_spread_sums_to_one():
    assert sum(s for _, s in spread(2030.5, 2033.25)) == pytest.approx(1.0)
    assert sum(s for _, s in spread(2030.2, 2030.2)) == pytest.approx(1.0)


def test_monte_carlo_ordering_and_recommended_is_faster():
    base = run_monte_carlo(build_program(), n=400, seed=1)
    rec = run_monte_carlo(build_program(apply(RECOMMENDED)), n=400, seed=1)
    for m in KEY_MILESTONES:
        r = base.milestones[m]
        assert r["p10"] <= r["p50"] <= r["p90"]
    assert rec.milestones["MARS-CREW-1"]["p50"] < base.milestones["MARS-CREW-1"]["p50"]


def test_sample_run_cost_at_least_low_bound():
    prog = build_program()
    r = sample_run(prog, random.Random(3))
    assert sum(r.cost.values()) >= sum(s.cost[0] for s in STEPS)


def test_logistics():
    a = L.LogisticsAssumptions()
    assert L.lunar_tankers(L.VEHICLE_CAMPAIGN, a) >= L.VEHICLE_CAMPAIGN.mars_tankers  # Moon landing needs more dv from LEO
    assert 400 < L.isru_power_kw(a) < 1200  # PR #6 energy, PR #12 383 days; PR #12 sizes about 1 MW
    prog = build_program(apply(RECOMMENDED))
    tm = forward_pass(prog, mode_plan(prog)[0])
    rows = L.campaign(prog, tm)
    assert sum(r.mars_ships for r in rows) > 0
    assert all(r.pads_needed >= 1 for r in rows)
    ideal = L.campaign(prog, tm, L.VEHICLE_IDEAL)
    assert sum(r.launches for r in ideal) < sum(r.launches for r in rows)
