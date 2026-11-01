import math

import numpy as np
import pytest

from raptor_sim.lunar_base import (
    buildup, checks, construction, depot, isru, mars_benefit, orbits, plume, power, site,
)
from raptor_sim.lunar_base.provenance import Value


def test_all_verification_checks_pass():
    failed = [c for c in checks.run_checks() if not c.passed]
    assert not failed, failed


def test_cited_value_needs_source():
    with pytest.raises(ValueError):
        Value(1.0, "m", "cited")
    with pytest.raises(ValueError):
        Value(1.0, "m", "guessed", "x")


def test_high_orbit_departures_are_cheaper_than_leo():
    leo = orbits.mars_departure("LEO")
    for o in ("EML1", "NRHO", "LLO"):
        assert orbits.mars_departure(o) < 0.5 * leo


def test_tli_is_textbook_value():
    assert orbits.tli_from_leo() == pytest.approx(3_108, abs=10)


def test_best_site_is_connecting_ridge():
    assert site.rank_sites()[0][0].name.startswith("Connecting Ridge")


def test_storage_sizing_closes_and_smaller_storage_fails():
    s = site.illumination_series(site.SITES[0])
    arch = [a for a in power.size_architectures(s, 40.0) if a[0].storage == "liion"][0][0]
    assert power.simulate(arch, s, 40.0).unmet_kwh < 1.0
    small = power.PowerSystem("x", arch.solar_kw, 0.0, "liion", 0.8 * arch.storage_kwh, arch.storage_kw)
    assert power.simulate(small, s, 40.0).unmet_kwh > 100.0


def test_isru_mass_balance():
    p = isru.water_plant(1_000.0, 0.056, "hydrolox")
    assert p.o2_t_yr + p.h2_t_yr == pytest.approx(1_000.0, rel=1e-6)
    m = isru.plant_for_production(500.0, 0.056, "methalox")
    assert m.o2_t_yr == pytest.approx(500.0, rel=1e-6)
    assert m.imported_ch4_t_yr == pytest.approx(500.0 / 3.6, rel=1e-6)


def test_richer_ice_needs_less_heat():
    assert isru.sublimation_heat_per_kg_water(0.30) < isru.sublimation_heat_per_kg_water(0.04)


def test_lunar_carbon_cannot_supply_methane():
    assert isru.lunar_carbon_coverage() < 0.1


def test_plume_pressure_scales_with_thrust():
    n1 = plume.Nozzle(1e5, 4.0, 1.22, height_m=3.0)
    n2 = plume.Nozzle(2e5, 4.0, 1.22, height_m=3.0)
    r = np.array([0.0, 1.0, 5.0])
    p1, _ = plume.surface_loads([n1], r, np.zeros(3))
    p2, _ = plume.surface_loads([n2], r, np.zeros(3))
    assert np.allclose(p2, 2 * p1)


def test_ejecta_range_matches_flat_moon_at_low_speed():
    v, a = 50.0, 30.0
    flat = v**2 * math.sin(math.radians(2 * a)) / orbits.G_MOON / 1e3
    assert plume.ejecta_range_km(v, a) == pytest.approx(flat, rel=0.01)
    assert math.isinf(plume.ejecta_range_km(plume.ESCAPE_SPEED + 1, 1.0))


def test_liftoff_sets_the_pad_size():
    rows = buildup.pad_summary()
    liftoff = [r for r in rows if r["lander"].startswith("Liftoff")][0]
    assert liftoff["pad_radius_m"] == max(r["pad_radius_m"] for r in rows)


def test_shielding_meets_limit():
    t = construction.cover_for_dose()
    assert 1.0 < t < 4.0
    assert construction.dose_msv_yr(t) < construction.SPEC["dose_limit_msv_yr"].value


def test_hydrogen_boils_off_faster_than_oxygen():
    assert depot.depot("LH2", 150, "orbit").boiloff_pct_per_month > depot.depot("LOX", 150, "orbit").boiloff_pct_per_month


def test_hydrolox_isp_from_cea():
    assert 420 < depot.hydrolox_isp() < 470


def test_lunar_lox_to_leo_beats_baseline_and_nrho_methalox_does_not():
    a, b, c = mars_benefit.mars_scenarios()
    assert c.earth_launches < a.earth_launches < b.earth_launches


def test_surface_refill_halves_sortie_launches():
    full, lox, _ = mars_benefit.lunar_sorties()
    assert lox.earth_launches < 0.65 * full.earth_launches


def test_buildup_monotonic():
    r = buildup.evaluate()
    assert [x.phase.crew for x in r] == sorted(x.phase.crew for x in r)
    assert all(x.cargo_landings >= 1 for x in r)
