"""Cited reference data for crewed lunar missions.

Every value carries a source and a status:
  "cited"      taken from the named source (checked 2026-10-31)
  "derived"    arithmetic on cited values
  "estimated"  our assumption, not published; change it freely

Sources:
  [LM]   https://en.wikipedia.org/wiki/Apollo_Lunar_Module
  [ORI]  https://en.wikipedia.org/wiki/Orion_(spacecraft)
  [HLS]  https://en.wikipedia.org/wiki/Starship_HLS
  [A3]   https://en.wikipedia.org/wiki/Artemis_3
  [BM]   https://en.wikipedia.org/wiki/Blue_Moon_(spacecraft)
  [RAP]  https://en.wikipedia.org/wiki/SpaceX_Raptor
  [NRHO] NASA, "NRHO: the Artemis orbit", https://www.nasa.gov/wp-content/uploads/2023/10/nrho-artemis-orbit.pdf
  [STR]  NASA, "HLS NRHO to Lunar Surface and Back Mission Design", NTRS 20230002566
  [A2]   Live Science, Artemis II splashdown report, 2026-04-10
  [HS]   NASA, "NASA identifies cause of Artemis I Orion heat shield char loss"
  [LCR]  Colaprete et al., "Detection of water in the LCROSS ejecta plume", Science 330 (2010), PMID 20966242
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Ref:
    value: float
    unit: str
    status: str  # cited | derived | estimated
    source: str
    note: str = ""


APOLLO_LM = {
    "descent_propellant": Ref(8_200, "kg", "cited", "[LM]"),
    "descent_stage_wet": Ref(10_334, "kg", "cited", "[LM]"),
    "ascent_dry": Ref(2_150, "kg", "cited", "[LM]"),
    "ascent_propellant": Ref(2_353, "kg", "cited", "[LM]", "APS only; RCS 287 kg extra"),
    "ascent_wet": Ref(4_700, "kg", "cited", "[LM]"),
    "total_wet": Ref(15_200, "kg", "cited", "[LM]", "standard LM; extended 16,400 kg"),
    "dps_thrust": Ref(45_040, "N", "cited", "[LM]"),
    "dps_isp": Ref(311, "s", "cited", "[LM]"),
    "dps_throttle_min": Ref(0.10, "-", "cited", "[LM]", "throttleable 10% to 60%, plus full thrust"),
    "aps_thrust": Ref(16_000, "N", "cited", "[LM]"),
    "aps_isp": Ref(311, "s", "cited", "[LM]"),
    "descent_dv_capability": Ref(2_500, "m/s", "cited", "[LM]"),
    "ascent_dv_capability": Ref(2_220, "m/s", "cited", "[LM]"),
    "surface_stay_max": Ref(75, "h", "cited", "[LM]", "extended LM"),
}

ORION = {
    "cm_launch_mass": Ref(10_400, "kg", "cited", "[ORI]"),
    "cm_dry_mass": Ref(9_300, "kg", "cited", "[ORI]"),
    "cm_esm_launch_mass": Ref(26_520, "kg", "cited", "[ORI]"),
    "dv_after_upper_stage_sep": Ref(1_050, "m/s", "cited", "[ORI]", "at about 26,375 kg"),
    "crew": Ref(4, "-", "cited", "[ORI]"),
    "undocked_endurance": Ref(21, "days", "cited", "[ORI]"),
    "diameter": Ref(5.02, "m", "cited", "[ORI]"),
}

STARSHIP_HLS = {
    "payload_to_surface": Ref(100_000, "kg", "cited", "[HLS]"),
    "crew": Ref(4, "-", "cited", "[HLS]", "2 to 4"),
    "surface_stay": Ref(7, "days", "cited", "[HLS]", "with at least 5 EVAs"),
    "lunar_orbit_loiter": Ref(100, "days", "cited", "[HLS]"),
    "tanker_flights_low": Ref(4, "-", "cited", "[HLS]", "Musk 2021"),
    "tanker_flights_high": Ref(16, "-", "cited", "[HLS]", "GAO 2021: 16 launches overall; NASA 2023: high teens"),
    "raptor_engines": Ref(6, "-", "cited", "[HLS]", "3 sea-level + 3 vacuum"),
    "dry_mass": Ref(120_000, "kg", "estimated", "ours",
                    "not published; Starship dry minus heat shield and flaps, plus legs, cabin, landing thrusters"),
}

BLUE_MOON_MK2 = {
    "dry_mass": Ref(16_000, "kg", "cited", "[BM]"),
    "launch_mass": Ref(45_000, "kg", "cited", "[BM]", "more than"),
    "be7_thrust": Ref(44_000, "N", "cited", "[BM]", "three engines"),
    "be7_min_thrust": Ref(8_900, "N", "cited", "[BM]"),
}

RAPTOR = {
    "throttle_min": Ref(0.40, "-", "cited", "[RAP]", "throttle range 40 to 100%"),
}

TRAJECTORY = {
    "nrho_to_llo": Ref(705, "m/s", "cited", "[STR]", "NRHO departure plus LLO insertion, about 12 h, nominal site"),
    "nrho_llo_global_access": Ref(1_522, "m/s", "cited", "[STR]", "upper end of the site scan (1,387 to 1,522)"),
    "surface_abort_to_nrho": Ref(1_550, "m/s", "cited", "[STR]", "minimum-dv surface abort range 1,420 to 1,550"),
    "nrho_loi_plus_tei": Ref(1_000, "m/s", "cited", "[NRHO]", "Orion as built; the split between legs is not stated"),
    "llo_loi_plus_tei": Ref(2_800, "m/s", "cited", "[NRHO]", "Artemis design factors, includes global access and margin"),
    "nrho_period": Ref(6.5, "days", "cited", "[NRHO]"),
    "tli_to_nrho": Ref(500, "m/s", "estimated", "[NRHO]", "half of the cited 1,000 m/s sum"),
    "nrho_to_tei": Ref(500, "m/s", "estimated", "[NRHO]", "half of the cited 1,000 m/s sum"),
    "descent_orbit_perilune": Ref(15_240, "m", "cited", "[STR]", "100 x 15.24 km descent and ascent orbit"),
    "descent_orbit_apolune": Ref(100_000, "m", "cited", "[STR]"),
}

EARTH_RETURN = {
    "artemis2_entry_speed": Ref(11_000, "m/s", "cited", "[A2]", "about 39,600 km/h"),
    "artemis2_splashdown": Ref(2026.27, "year", "cited", "[A2]", "2026-04-10, 10-day crewed lunar flyby"),
    "artemis1_char_loss": Ref(1, "-", "cited", "[HS]",
                              "Avcoat gas could not escape during skip entry; Artemis II flew a steeper lofted entry"),
}

PROGRAM_STATUS = {
    "artemis3_leo_demo": Ref(2027.8, "year", "cited", "[A3]",
                             "changed 2026-02-27 to a crewed LEO docking test with Starship and Blue Moon, late 2027"),
    "artemis4_first_landing": Ref(2028.2, "year", "cited", "[A3]", "first crewed landing, early 2028"),
    "ship_to_ship_transfer_demo_done": Ref(0, "-", "cited", "[HLS]", "not yet flown as of September 2026"),
    "blue_moon_mk2_crewed": Ref(2030, "year", "cited", "[BM]", "Artemis V"),
}

LUNAR_RESOURCES = {
    "cabeus_water_wt_frac": Ref(0.056, "-", "cited", "[LCR]", "5.6 +/- 2.9 % by mass at the LCROSS impact site"),
}
