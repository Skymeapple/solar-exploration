"""Every input to the settlement models, with where it comes from.

Each parameter carries a basis tag:
  cited    - a published measurement or figure, source key into SOURCES
  model    - computed by this repository (mission, engine or settlement models)
  estimate - our assumption; change it here and re-run scripts/run_settlement_study.py
  unknown  - no human data exists; the value is a placeholder and the models
             run it as a range, never as a single answer

Values tagged cited were checked against the source page on 2026-10-31 where a
URL is given. "cited (approx)" in a note means the figure is quoted from a
standard reference without re-reading the full PDF; verify before relying on it.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    value: float
    unit: str
    basis: str  # cited | model | estimate | unknown
    source: str = ""  # key into SOURCES, or the repository module for model values
    note: str = ""


SOURCES = {
    "rad_mars": "Hassler et al. 2014, Science 343, 'Mars' surface radiation environment measured with the Mars Science Laboratory's Curiosity rover', https://elib.dlr.de/106090",
    "rad_cruise": "Zeitlin et al. 2013, Science 340, 'Measurements of energetic particle radiation in transit to Mars on the Mars Science Laboratory', https://www.space.com/23875-mars-radiation-life-manned-mission.html",
    "lnd_moon": "Zhang et al. 2020, Science Advances 6, Chang'e 4 Lunar Lander Neutron and Dosimetry, https://www.sci.news/space/radiation-dose-rates-lunar-surface-08893.html",
    "nasa_std_3001": "NASA-STD-3001 Vol 1 Rev B (2022) career effective dose limit 600 mSv, https://www.nasa.gov/wp-content/uploads/2023/03/radiation-protection-technical-brief-ochmo.pdf",
    "icrp103": "ICRP Publication 103 (2007), nominal risk coefficient for cancer, whole population, ~5.5 %/Sv",
    "unscear": "UNSCEAR 2008, world average natural background effective dose 2.4 mSv/yr",
    "bvad": "NASA Life Support Baseline Values and Assumptions Document, NASA/TP-2015-218570, https://ntrs.nasa.gov/citations/20180001338",
    "iss_water": "NASA 2023, ISS Water Recovery System reached 98% water recovery, https://yourstory.com/2023/06/space-sustainability-98-water-recovery-iss",
    "bone_loss": "NASA Human Research Program, Risk of Spaceflight-Induced Bone Changes, https://www.nasa.gov/reference/risk-of-spaceflight-induced-bone-changes/",
    "smith2014": "Smith 2014, Acta Astronautica 97, 'Estimation of a genetically viable population for multigenerational interstellar voyaging', https://ui.adsabs.harvard.edu/abs/2014AcAau..97...16S/abstract",
    "marin2017": "Marin 2017 / Marin & Beluffi 2018, HERITAGE Monte Carlo code (cites Moore 2003: 150-180 founders), https://arxiv.org/pdf/1708.08649",
    "franklin": "Franklin 1980 / Frankham et al. 2014, the 50/500 effective population size rule",
    "dunbar": "Dunbar 1992, J. Human Evolution 22, neocortex size and group size (~150)",
    "fsp": "NASA Fission Surface Power project, 40 kWe class lunar reactor, https://www.space.com/nasa-moon-nuclear-reactor-project-first-phase-complete",
    "wheeler": "Wheeler, NASA crop research: ~40-50 m2 of high-light crops per person for full diet and O2, https://www.frontiersin.org/journals/astronomy-and-space-sciences/articles/10.3389/fspas.2021.734343/pdf",
    "led": "Kusuma, Pattison & Bugbee 2020, Horticulture Research 7: best horticultural LED fixtures ~3 umol/J",
    "solar_const": "Total solar irradiance 1361 W/m2 at 1 AU (Kopp & Lean 2011)",
    "ost": "Outer Space Treaty 1967, Article II (no national appropriation) and Article VI (state responsibility for national activities)",
    "appendicitis": "Global appendicitis incidence on the order of 100 per 100,000 person-years (Ferris et al. 2017, Annals of Surgery)",
    "spacex_mars": "SpaceX stated aspiration: ~1 million people on Mars, ~100 people per ship (public talks 2016-2024)",
    "starship": "Starship Block 3 public figures as used in raptor_sim.mission (PR #1)",
    "mars500": "Mars-500 520-day isolation study (6 crew), Basner et al. 2013/2014 PNAS",
}


P = Param
PARAMS: dict[str, Param] = {
    # --- radiation ------------------------------------------------------------
    "dose_mars_surface": P(0.64, "mSv/day", "cited", "rad_mars", "GCR dose equivalent, Gale crater, solar maximum-ish 2012-13"),
    "dose_cruise": P(1.84, "mSv/day", "cited", "rad_cruise", "inside MSL cruise stage, light shielding"),
    "dose_moon_surface": P(1.369, "mSv/day", "cited", "lnd_moon", "Chang'e 4, far side, 2019"),
    "dose_earth_background": P(2.4, "mSv/yr", "cited", "unscear"),
    "career_limit": P(600.0, "mSv", "cited", "nasa_std_3001", "astronaut occupational limit, not a public standard"),
    "risk_per_sv": P(0.055, "1/Sv", "cited", "icrp103", "low-LET basis; heavy-ion GCR quality is the main unknown"),
    "risk_child_multiplier": P(2.5, "x", "estimate", "icrp103", "ICRP age tables show 2-3x higher risk per Sv for exposure in childhood"),
    "shield_lambda": P(150.0, "g/cm2", "estimate", "", "penetrating-component e-folding length in regolith; run at 100 and 250 as a range"),
    "gcr_quality_uncertainty": P(3.0, "x", "unknown", "", "range factor on GCR risk; NASA's own model carries roughly this spread"),
    # --- life support ---------------------------------------------------------
    "o2_per_person": P(0.82, "kg/day", "cited", "bvad", "cited (approx), nominal crew member"),
    "co2_per_person": P(1.04, "kg/day", "cited", "bvad", "cited (approx)"),
    "drink_water": P(2.5, "kg/day", "cited", "bvad", "cited (approx), drinking plus food rehydration"),
    "hygiene_water": P(5.0, "kg/day", "estimate", "bvad", "BVAD ranges 1-25 kg/day; a settlement with laundry and showers sits mid-range"),
    "food_dry": P(0.62, "kg/day", "cited", "bvad", "cited (approx), dry food solids"),
    "food_packaged": P(1.8, "kg/day", "estimate", "bvad", "as shipped incl. residual water and packaging"),
    "metabolic_heat": P(137.0, "W", "cited", "bvad", "cited (approx), nominal average"),
    "water_recovery_iss": P(0.98, "-", "cited", "iss_water"),
    "o2_recovery_sabatier": P(0.50, "-", "estimate", "", "Sabatier is hydrogen-limited to about half the O2 in CO2"),
    "o2_recovery_bosch": P(0.95, "-", "estimate", "", "Bosch or methane pyrolysis loop, not yet flown at scale"),
    "leak_per_person": P(0.1, "kg/day", "estimate", "", "cabin air leakage plus airlock losses per resident"),
    # --- food and energy ------------------------------------------------------
    "crop_area_per_person": P(45.0, "m2", "cited", "wheeler", "full diet, high light, mixed crops"),
    "ppfd": P(600.0, "umol/m2/s", "estimate", "wheeler", "high-light crop setpoint"),
    "photoperiod_h": P(16.0, "h/day", "estimate"),
    "led_efficacy": P(2.8, "umol/J", "cited", "led", "best fixtures ~3.0; 2.8 allows for ageing"),
    "hvac_cop": P(3.0, "-", "estimate", "", "heat rejection coefficient of performance for crop heat"),
    "eclss_power_per_person": P(1.0, "kWe", "estimate", "", "air, water, thermal per resident"),
    "habitat_power_per_person": P(2.0, "kWe", "estimate", "", "lighting, heating, computing, medical"),
    "industry_power_per_person": P(10.0, "kWe", "unknown", "", "manufacturing from local ore; Earth industry is ~1-3 kW/person primary"),
    "solar_const": P(1361.0, "W/m2", "cited", "solar_const"),
    "pv_efficiency": P(0.30, "-", "estimate", "", "space-grade multijunction; thin-film locally made later ~0.15"),
    "pv_specific_mass": P(1.5, "kg/m2", "estimate", "", "array, structure, wiring, ground mounted"),
    "battery_specific_energy": P(0.20, "kWh/kg", "estimate", "", "Li-ion at pack level"),
    "fission_unit_kwe": P(40.0, "kWe", "cited", "fsp"),
    "fission_unit_mass": P(6000.0, "kg", "estimate", "fsp", "FSP target is under 6 t; treat as upper bound"),
    "electrolysis_kwh_per_kg_h2": P(50.0, "kWh/kg", "estimate", "", "~80% of HHV 39.4 kWh/kg"),
    "water_mining_kwh_per_kg": P(1.0, "kWh/kg", "estimate", "", "heat and lift buried ice; regolith-bound water costs 5-10x more"),
    "liquefaction_kwh_per_kg": P(0.5, "kWh/kg", "estimate", "", "cryocooler work for CH4 and O2"),
    # --- transport (from PR #1 mission model) ----------------------------------
    "ship_cargo_mars": P(100.0, "t", "model", "raptor_sim.mission", "G0 requirement, met with 4 tankers"),
    "return_propellant_isru": P(642.0, "t", "model", "raptor_sim.mission", "Mars-made propellant to return a ship with 20 t"),
    "people_per_ship": P(100.0, "persons", "cited", "spacex_mars", "stated aspiration; habitability unproven"),
    "mass_per_passenger": P(1.0, "t", "estimate", "", "person, seat, consumables for ~6 months, personal kit"),
    # --- health ---------------------------------------------------------------
    "bone_loss_0g": P(0.0125, "1/month", "cited", "bone_loss", "1.0-1.5 %/month at weight-bearing sites, 4-6 month missions"),
    "exercise_effectiveness": P(0.5, "-", "estimate", "bone_loss", "ARED-era crews lose less; 0.5 is a middle reading"),
    "physicians_per_1000": P(2.5, "per 1000", "estimate", "", "high-income Earth average 2.5-4"),
    "appendicitis_rate": P(1.0e-3, "1/person-yr", "cited", "appendicitis"),
    "surgical_emergency_rate": P(5.0e-3, "1/person-yr", "estimate", "", "all emergency surgery incl. trauma and obstetrics"),
    # --- population -----------------------------------------------------------
    "life_expectancy": P(80.0, "yr", "estimate", "", "high-income Earth today; unknown under partial gravity"),
    "tfr_target": P(2.5, "births/woman", "estimate", "", "policy lever"),
    "smith_min_founders": P(14000.0, "persons", "cited", "smith2014", "range 14,000-44,000 with no later gene flow"),
    "moore_min_founders": P(150.0, "persons", "cited", "marin2017", "Moore 2003, 150-180, with strict mating rules"),
    "ne_short_term": P(50.0, "Ne", "cited", "franklin"),
    "ne_long_term": P(500.0, "Ne", "cited", "franklin"),
    "dunbar": P(150.0, "persons", "cited", "dunbar"),
}


def v(name: str) -> float:
    return PARAMS[name].value


def table_rows() -> list[tuple[str, str, str, str, str, str]]:
    """Rows for the cited-versus-estimated register in results/settlement."""
    rows = []
    for name, p in PARAMS.items():
        rows.append((name, f"{p.value:g}", p.unit, p.basis, p.source, p.note))
    return rows
