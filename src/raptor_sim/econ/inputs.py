"""Assumptions for the business case.

Every number carries a basis tag:
  cited    - taken from a public source, URL in SOURCES
  model    - computed by this repository (engine, BOM, vehicle, mission models)
  estimate - our assumption; change it here and re-run scripts/run_business_case.py

Money is in 2026 US dollars, no inflation.
"""
from __future__ import annotations

SOURCES = {
    "space_economy": "https://www.spacefoundation.org/2025/07/22/the-space-report-2025-q2/",
    "hls_option_b": "https://www.nasa.gov/humans-in-space/nasa-awards-spacex-second-contract-option-for-artemis-moon-landing",
    "hls_total": "https://www.teslarati.com/spacex-nasa-finalize-second-starship-moon-landing-contract",
    "falcon9_price": "https://keeptrack.space/deep-dive/how-much-does-a-falcon-9-launch-cost",
    "cld_budget": "https://aerospaceamerica.aiaa.org/proposed-fiscal-2027-funding-could-support-two-commercial-space-stations-developers-say/",
    "msr_cost": "https://spacepolicyonline.com/news/nasa-wants-new-ideas-fast-on-how-to-return-samples-from-mars-affordably/",
    "stoke_round": "https://www.geekwire.com/2025/stoke-space-reportedly-raising-funding-nova-rocket/",
}

# --- Cited market anchors -------------------------------------------------
MARKET_CITED = {
    "space_economy_2024_busd": 613.0,      # cited: space_economy
    "space_economy_growth_2024": 0.078,    # cited: space_economy
    "government_space_2024_busd": 132.0,   # cited: space_economy
    "falcon9_list_price_2026_musd": 74.0,  # cited: falcon9_price
    "falcon9_internal_cost_musd": 15.0,    # cited (outside estimate reported): falcon9_price
    "rideshare_usd_per_kg_2026": 7_000.0,  # cited (secondary estimate): falcon9_price
    "hls_spacex_total_busd": 4.2,          # cited: hls_total (Option A + B ceiling)
    "hls_option_b_busd": 1.15,             # cited: hls_option_b
    "cld_fy2026_musd": 300.0,              # cited: cld_budget
    "cld_fy2027_musd": 400.0,              # cited: cld_budget (House proposal)
    "msr_low_busd": 8.0,                   # cited: msr_cost
    "msr_high_busd": 11.0,                 # cited: msr_cost
    "stoke_series_d_musd": 510.0,          # cited: stoke_round
}

# --- Engineering figures from this repository (model) ----------------------
MODEL = {
    "engine_mass_kg": 2_320.0,           # model: PR #2 BOM
    "payload_leo_model_t": 155.0,        # model: PR #1 vehicle, 100 t ship dry
    "payload_leo_stated_t": 100.0,       # cited by PR #1 summary as SpaceX Block 3 statement
    "mars_prop_in_leo_t": 546.0,         # model: PR #1 Mars study
    "mars_tankers": 4,                   # model: PR #1 Mars study
    "mars_payload_t": 100.0,             # model: G0 requirement
    "booster_propellant_t": 3_650.0,     # public figure used by PR #1
    "ship_propellant_t": 1_600.0,        # public figure used by PR #1
    "booster_dry_t": 275.0,
    "ship_dry_t": 100.0,
    "booster_engines": 33,
    "ship_engines_sl": 3,
    "ship_engines_vac": 3,
    "mixture_ratio": 3.6,
    "ship_isp_vac_s": 362.7,             # model: PR #1
    "mars_dv_from_leo_ms": 3_951.0 + 700.0,  # model: TMI + landing
}

# --- Engine manufacturing (estimate) ---------------------------------------
# Raw-material price per kg (powder or forging stock) and buy-to-fly ratio.
MATERIAL_USD_PER_KG = {
    "GRCop-42": 180.0, "IN718": 70.0, "OXSA": 150.0, "Ti64": 60.0,
    "MonelK500": 45.0, "A286": 35.0, "SS316L": 10.0, "various": 150.0,
}
BUY_TO_FLY = {"sized": 2.5, "estimate": 1.5}

# Fabrication hours per finished kg, keyed by part-number prefix or full number.
FAB_HOURS_PER_KG = {
    "RC": 3.0,       # channel milling, closeout, braze
    "IN": 10.0,      # 300 coaxial elements
    "TP-rot": 25.0,  # impellers, discs, shafts: five-axis, balance
    "TP-hsg": 2.0,   # housings
    "PB": 6.0,
    "FL": 3.0,
    "GM": 4.0,
}
TP_ROTATING = {"TP-301", "TP-302", "TP-303", "TP-401", "TP-402", "TP-403", "TP-406"}
PURCHASED_USD_PER_KG = {"TP-306": 400.0, "TP-407": 400.0, "VA": 800.0}
PURCHASED_EACH_USD = {"EC-820": 150_000.0, "IG-830": 10_000.0}
LABOUR_USD_PER_HOUR = 160.0          # fully burdened, US aerospace
ASSEMBLY_TEST_T1_USD = 250_000.0     # integration plus acceptance hot fire
VAC_ENGINE_FACTOR = 1.30             # large radiatively cooled nozzle extension

LEARNING_LABOUR = 0.85               # Wright curve slope for touch labour
LEARNING_MATERIAL = 0.95             # volume discounts on material and purchased parts
LEARNING_VEHICLE = 0.90

# --- Vehicle manufacturing (estimate) --------------------------------------
STRUCTURE_USD_PER_KG_T1 = 60.0       # 304L stainless, welded barrels and domes
BOOSTER_OTHER_T1_USD = 12e6          # avionics, grid fins, plumbing, chill-down
SHIP_TILES = 18_000
TILE_USD_T1 = 1_000.0
SHIP_OTHER_T1_USD = 10e6             # avionics, flaps, actuators, header tanks

# --- Operations (estimate) --------------------------------------------------
CH4_USD_PER_KG = 0.40                # liquefied natural gas, about $7/MMBtu plus liquefaction
LOX_USD_PER_KG = 0.12
LAUNCH_OPS_USD = 3.0e6               # pad turnaround, range, recovery, per flight
BOOSTER_LIFE_FLIGHTS = 50
SHIP_LIFE_FLIGHTS = 20
BOOSTER_REFURB_FRACTION = 0.02       # of build cost, per flight
SHIP_REFURB_FRACTION = 0.05          # tiles dominate
FLEET_UNIT_INDEX = 100               # vehicle unit number used for mature per-flight cost
ENGINE_UNIT_INDEX = 2_000            # engine unit number at maturity
MISSION_OPS_MARS_USD = 40e6          # cruise operations, surface ops for one cargo landing
MISSION_OPS_MOON_USD = 15e6
LUNAR_DV_FROM_LEO_MS = 3_200 + 900 + 2_000  # TLI + lunar orbit insertion + landing, estimate
