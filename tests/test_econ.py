from raptor_sim.econ.costs import VehicleCost, engine_cost, lunar_tankers, missions, wright
from raptor_sim.econ.plan import BASE, BEAR, BULL, ROUNDS, cap_table, cash_balance, value


def test_engine_cost_covers_every_bom_line():
    e = engine_cost()
    assert len(e.parts) == 42
    assert abs(sum(p.mass_kg for p in e.parts) - 2320) < 5
    assert 1.5e6 < e.t1 < 4e6
    assert e.unit(1000) < e.unit(10) < e.t1


def test_wright_halves_on_doubling():
    assert abs(wright(100, 2, 0.85) - 85) < 1e-9


def test_flight_cost_and_missions():
    vc = VehicleCost(engine_cost())
    assert vc.flight_cost() < vc.flight_cost(ship_expended=True)
    _, n = lunar_tankers()
    assert n > 4  # Moon landing from LEO needs more delta-v than the Mars cargo case
    ms = missions(vc, 100.0)
    assert ms[1].flights == 5 and ms[0].usd_per_kg < ms[1].usd_per_kg


def test_scenarios_ordered_and_funded():
    bear, base, bull = value(BEAR), value(BASE), value(BULL)
    assert bear.npv_musd < base.npv_musd < bull.npv_musd
    assert min(c for _, c in cash_balance(BASE)) > 0  # financing plan covers the base trough
    founders = cap_table()[-1][1]["Founders"]
    assert 0.1 < founders < 0.4
    assert abs(sum(cap_table()[-1][1].values()) - 1) < 1e-9
    assert sum(r.raise_musd for r in ROUNDS) > -base.trough_musd
