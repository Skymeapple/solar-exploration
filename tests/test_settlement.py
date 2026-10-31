"""Verification tests for the settlement models (fast; no rocketcea needed)."""
import math

import pytest

from raptor_sim.settlement import capabilities, energy, growth, health, inputs, life_support, population, radiation


def test_every_input_has_a_known_basis_and_source_key():
    for name, p in inputs.PARAMS.items():
        assert p.basis in {"cited", "model", "estimate", "unknown"}, name
        if p.basis == "cited":
            assert p.source in inputs.SOURCES, name


def test_genetics_matches_wright_fisher_theory():
    sim, ana = population.wright_fisher_check(n=50, generations=20, loci=200, reps=6)
    assert sim == pytest.approx(ana, rel=0.03)


def test_gompertz_fit_reproduces_life_expectancy():
    a = population.gompertz_a(80.0)
    assert 1e-6 < a < 1e-3


def test_small_closed_colony_loses_more_diversity_than_large():
    small = population.simulate(population.PopulationScenario(founders=30, capacity=60, years=150, loci=40, seed=2))
    large = population.simulate(population.PopulationScenario(founders=300, capacity=600, years=150, loci=40, seed=2))
    assert small.heterozygosity[-1] < large.heterozygosity[-1]
    assert small.inbreeding[-1] > large.inbreeding[-1]


def test_gamete_bank_keeps_population_alive_without_men():
    s = population.PopulationScenario(founders=40, capacity=80, years=60, loci=20, bank_share=1.0, seed=4)
    r = population.simulate(s)
    assert r.population[-1] > 0


@pytest.mark.parametrize("stage", list(life_support.STAGES))
def test_life_support_mass_balance_closes(stage):
    for b in life_support.person_year(life_support.STAGES[stage]):
        assert b.closes
        assert b.imported_kg >= 0 and b.local_kg >= 0


def test_closure_improves_with_maturity():
    c = [life_support.closure(life_support.STAGES[k]) for k in ("outpost", "isru", "bioregen")]
    assert c[0] < c[1] < c[2] < 1.0


def test_propellant_stoichiometry():
    p = energy.propellant_energy(3.6)
    assert p.water_kg_per_kg == pytest.approx(2.25 / 4.6)
    assert p.o2_surplus_kg_per_kg == pytest.approx(0.4 / 4.6)
    assert 4.0 < p.kwh_per_kg_propellant < 10.0


def test_fission_beats_solar_far_from_sun_and_through_mars_dust_storms():
    mars = energy.SOLAR_SITES["Mars equator"]
    assert energy.solar_mass_per_kwe(mars, storm_proof=True) > energy.fission_mass_per_kwe()
    assert energy.solar_mass_per_kwe(energy.SOLAR_SITES["Callisto"]) > energy.fission_mass_per_kwe()


def test_unshielded_mars_dose_equals_rad_measurement():
    assert radiation.annual_dose_msv(radiation.Exposure("Mars", 0.0, 0.0)) / 365.25 == pytest.approx(0.64)


def test_shielding_is_monotonic_and_outdoor_time_sets_a_floor():
    xs = [0, 50, 100, 300, 600, 1000]
    f = [radiation.shield_factor(x) for x in xs]
    assert all(a > b for a, b in zip(f, f[1:]))
    assert math.isinf(radiation.shield_needed("Mars", 2.0, hours_outside=4.0))
    assert math.isfinite(radiation.shield_needed("Mars", 2.4, hours_outside=0.0))


def test_crew_round_trip_exceeds_nasa_career_limit_on_transit_alone():
    transit = 2 * 180 * inputs.v("dose_cruise")
    assert transit > inputs.v("career_limit")


def test_bone_hypotheses_bracket_and_converge_at_zero_g():
    g = health.GRAVITY_G["Mars"]
    vals = {h: health.bone_fraction(10, g, h) for h in health.HYPOTHESES}
    assert vals["threshold"] >= vals["linear"] >= vals["sqrt"]
    z = {h: health.bone_fraction(10, 0.0, h) for h in health.HYPOTHESES}
    assert max(z.values()) - min(z.values()) < 1e-12


def test_synodic_period_and_light_time():
    assert growth.synodic_period_days() == pytest.approx(779.9, abs=1.0)
    lo, hi = health.comms_delay_minutes()
    assert 3 < lo < 4.5 and 20 < hi < 22.5


def test_growth_needs_both_fleet_and_local_industry():
    base = growth.milestones(growth.run(growth.GrowthScenario()))
    slow = growth.milestones(growth.run(growth.GrowthScenario(n_half=100_000)))
    small = growth.milestones(growth.run(growth.GrowthScenario(fleet_cap=100)))
    assert base["final_population"] > 10 * slow["final_population"]
    assert base["final_population"] > 10 * small["final_population"]


def test_early_earth_cutoff_collapses_and_late_cutoff_survives():
    early = growth.run(growth.GrowthScenario(cutoff_window=10))
    late = growth.run(growth.GrowthScenario(cutoff_window=30))
    assert early[-1].population < 1
    assert late[-1].population > 100_000


def test_capability_matrix_values_and_universal_reuse():
    m = capabilities.matrix()
    assert all(x in {"same", "adapt", "new"} for row in m.values() for x in row.values())
    everywhere = capabilities.reusable_everywhere()
    assert "Fission power (40 kWe class)" in everywhere
    assert "Closed-loop ECLSS (water 98%, O2 from CO2)" in everywhere
    s = capabilities.reuse_scores()
    assert s["Mars"] == max(s.values())
