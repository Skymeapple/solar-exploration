"""Public anchors used by the roadmap. Checked 2026-10-31."""
from __future__ import annotations

SOURCES = {
    "artemis_iii": "https://www.iflscience.com/artemis-iii-has-already-been-pushed-back-to-late-2027-just-2-months-after-nasa-announced-ambitious-new-moon-plan-83377",
    "starship_refuel_2027": "https://newspaceeconomy.ca/2026/10/21/spacex-targets-weekly-starship-launches-in-2027-and-early-orbital-refueling-tests/",
    "prop_transfer_demo": "https://en.wikipedia.org/wiki/Starship_Propellant_Transfer_Demonstration",
    "lunar_fission": "https://aviationweek.com/space/budget-policy-regulation/nasa-aims-launch-lunar-fission-reactor-2030",
    "iss_water": "https://newatlas.com/space/nasa-converts-pee-to-drinkable-water-on-international-space-station",
    "starship_wiki": "https://en.wikipedia.org/wiki/SpaceX_Starship",
    "msr_cost": "https://spacepolicyonline.com/news/nasa-wants-new-ideas-fast-on-how-to-return-samples-from-mars-affordably/",
    "hls_total": "https://www.teslarati.com/spacex-nasa-finalize-second-starship-moon-landing-contract",
}

# External reference points: where the rest of the industry is. These are not
# our schedule; they show how far ahead or behind our plan sits.
EXTERNAL = [
    ("Starship orbital refuelling attempt (SpaceX target)", "early 2027", "starship_refuel_2027"),
    ("Starship weekly flight cadence (SpaceX target)", "H1 2027", "starship_refuel_2027"),
    ("Starship propellant transfer demo (NASA HLS milestone)", "NET late 2026, not scheduled as of Sep 2026", "prop_transfer_demo"),
    ("Artemis III, crewed lander test in LEO", "late 2027 at earliest", "artemis_iii"),
    ("Artemis IV, first crewed landing since 1972", "2028 planned, likely later", "artemis_iii"),
    ("NASA lunar fission reactor, at least 20 kW", "fly by 2030", "lunar_fission"),
    ("ISS closed-loop water recovery", "98% demonstrated 2023", "iss_water"),
    ("NASA Mars Sample Return cost", "$8-11B", "msr_cost"),
]

# Mars launch windows recur every synodic period. The anchor is the Nov-Dec 2026
# window opening (estimate, within about a month); later windows follow from
# the synodic period, which is computed from the two orbital periods.
EARTH_YEAR_D = 365.256
MARS_YEAR_D = 686.980
JUPITER_YEAR_D = 4332.59
MARS_SYNODIC_D = 1 / (1 / EARTH_YEAR_D - 1 / MARS_YEAR_D)        # 779.9 d
JUPITER_SYNODIC_D = 1 / (1 / EARTH_YEAR_D - 1 / JUPITER_YEAR_D)  # 398.9 d
