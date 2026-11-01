"""Which settlement capabilities carry over between sites, and which must change.

Each capability states what it needs from a site (rules over site properties).
For every site the rule returns:
  same   - reuse the design unchanged
  adapt  - same core technology, re-sized or modified (e.g. thicker shielding)
  new    - needs a different technology at this site

Site properties are cited planetary data (gravity, distance from the Sun,
atmosphere, day length) plus our reading of resource availability. Resource
entries are marked in RESOURCE_NOTES because several are inferred from orbital
data rather than proven on the ground.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .health import GRAVITY_G
from .radiation import SURFACE_DOSE


@dataclass(frozen=True)
class SiteProps:
    name: str
    g: float
    sun_au: float
    atmosphere: str  # none | thin_co2 | thick_n2
    water_ice: bool
    carbon: bool  # accessible carbon for CH4 (atmosphere CO2, carbonates, organics)
    day_hours: float
    surface_dose_msv_day: float
    one_way_light_min: float  # typical one-way delay to Earth


SITES = {
    "Mars": SiteProps("Mars", GRAVITY_G["Mars"], 1.524, "thin_co2", True, True, 24.66, SURFACE_DOSE["Mars"], 12.5),
    "Moon (south pole)": SiteProps("Moon (south pole)", GRAVITY_G["Moon"], 1.0, "none", True, False, 708.7, SURFACE_DOSE["Moon"], 0.02),
    "Ceres": SiteProps("Ceres", GRAVITY_G["Ceres"], 2.77, "none", True, True, 9.07, 1.4, 25.0),
    "Callisto": SiteProps("Callisto", GRAVITY_G["Callisto"], 5.2, "none", True, True, 400.5, 1.4, 43.0),
    "Titan": SiteProps("Titan", GRAVITY_G["Titan"], 9.58, "thick_n2", True, True, 382.7, 0.02, 80.0),
    "Free-space station": SiteProps("Free-space station", 0.0, 1.0, "none", False, False, 24.0, SURFACE_DOSE["Deep space"], 0.1),
}

RESOURCE_NOTES = {
    "Moon (south pole)": "water ice in permanently shadowed craters from LCROSS and orbital data; carbon scarce (traces in cold-trap volatiles), so CH4 fuel is imported or LOX-only ISRU",
    "Ceres": "water ice and ammoniated clays and carbonates from Dawn; surface dose estimated as Moon-like (no measurement)",
    "Callisto": "water ice crust; outside Jupiter's main radiation belts but dose not measured, Moon-like estimate",
    "Titan": "methane lakes and water-ice bedrock; thick atmosphere (1.5 bar) gives Earth-like shielding (estimate); 94 K surface",
    "Free-space station": "all mass from asteroids or the Moon; spin gravity is a design choice",
}


@dataclass(frozen=True)
class Capability:
    name: str
    group: str
    rule: Callable[[SiteProps], str]
    note: str


def _ch4_isru(s: SiteProps) -> str:
    if s.name == "Titan":
        return "adapt"  # methane is there already; needs only O2 from water ice
    if s.water_ice and s.carbon and s.atmosphere == "thin_co2":
        return "same"
    if s.water_ice and s.carbon:
        return "adapt"  # carbon from carbonates or organics, not the air
    if s.water_ice:
        return "new"  # LOX/H2 or LOX-only with imported CH4
    return "new"


def _solar(s: SiteProps) -> str:
    if s.sun_au <= 1.6 and s.day_hours < 30:
        return "same"
    if s.sun_au <= 3.0:
        return "adapt"  # bigger arrays, or ridge siting on the Moon
    return "new"  # too far from the Sun: fission only


def _landing(s: SiteProps) -> str:
    if s.atmosphere == "thin_co2":
        return "same"  # Starship aero-entry then propulsive
    if s.atmosphere == "thick_n2":
        return "adapt"  # aerobraking easy, but parachutes or wings change the design
    if s.g == 0:
        return "new"  # docking, no landing
    return "adapt"  # fully propulsive, landing pads against plume ejecta


def _shield(s: SiteProps) -> str:
    if s.surface_dose_msv_day < 0.1:
        return "adapt"  # atmosphere does most of it
    if s.g == 0:
        return "new"  # shielding mass must be brought or mined and spun up
    return "same"  # bury habitats under regolith; depth scales with dose


def _food(s: SiteProps) -> str:
    if s.sun_au <= 1.6 and s.day_hours < 30:
        return "same"  # LED farms, sunlight supplement
    return "adapt"  # LED-only farms, more power per person


def _gravity_health(s: SiteProps) -> str:
    if s.g >= 0.3:
        return "same"
    if s.g > 0.0:
        return "adapt"  # likely needs centrifuge sleeping quarters (unknown)
    return "new"  # rotating habitat


def _thermal(s: SiteProps) -> str:
    if s.name == "Titan":
        return "new"  # 94 K in a dense atmosphere: convective heat loss dominates
    if s.day_hours > 100:
        return "adapt"  # two-week nights
    return "same"


CAPABILITIES = [
    Capability("Closed-loop ECLSS (water 98%, O2 from CO2)", "life support", lambda s: "same", "physico-chemical loops are site-independent"),
    Capability("Bioregenerative crops", "life support", _food, "crop area per person is the same; light source changes"),
    Capability("Pressurised habitat modules", "habitat", lambda s: "same", "one pressure vessel design; foundations vary"),
    Capability("Regolith radiation shielding", "habitat", _shield, "depth from radiation.shield_needed"),
    Capability("Thermal control", "habitat", _thermal, ""),
    Capability("Fission power (40 kWe class)", "energy", lambda s: "same", "works anywhere; heat rejection area changes with environment"),
    Capability("Solar power with storage", "energy", _solar, "energy.solar_mass_per_kwe by site"),
    Capability("Water-ice mining", "resources", lambda s: "same" if s.water_ice else "new", "mining method varies with ice depth"),
    Capability("CH4/LOX propellant plant", "resources", _ch4_isru, "engine model propellant; energy.propellant_energy"),
    Capability("Raptor-class engine and Starship-class ship", "transport", lambda s: "same" if s.carbon or s.name == "Moon (south pole)" else "adapt", "same engine wherever CH4/LOX can be made or delivered"),
    Capability("Landing and ascent", "transport", _landing, ""),
    Capability("On-site rocket assembly and refurbishment", "industry", lambda s: "same" if s.g > 0 else "adapt", "same tooling; in free space needs orbital fixtures"),
    Capability("Medical bay and telemedicine", "health", lambda s: "same" if s.one_way_light_min < 1 else "adapt", "beyond ~1 min delay, care must be autonomous"),
    Capability("Partial-gravity health countermeasures", "health", _gravity_health, "health.bone_fraction; the science here is unknown"),
    Capability("Governance and social model", "society", lambda s: "same", "charter model is site-independent; delay drives autonomy"),
]


def matrix() -> dict[str, dict[str, str]]:
    return {c.name: {site: c.rule(p) for site, p in SITES.items()} for c in CAPABILITIES}


def reuse_scores() -> dict[str, float]:
    """Share of capabilities reused at each site (same = 1, adapt = 0.5, new = 0)."""
    m = matrix()
    w = {"same": 1.0, "adapt": 0.5, "new": 0.0}
    return {site: sum(w[m[c.name][site]] for c in CAPABILITIES) / len(CAPABILITIES) for site in SITES}


def reusable_everywhere() -> list[str]:
    m = matrix()
    return [c for c, row in m.items() if all(x == "same" for x in row.values())]
