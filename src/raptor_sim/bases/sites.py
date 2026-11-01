"""Candidate transit-base sites and the bodies they sit on.

Each :class:`Site` carries its numbers plus a ``basis`` map from field name to a
tag and source:

* ``cited:<source>``      checked against the source during this study (2026-10-31)
* ``literature:<source>`` standard published value, source named, not re-checked here
* ``estimate:<reason>``   engineering assumption made for this study

Fields not listed in ``basis`` fall back to ``DEFAULT_BASIS`` (orbital and
physical constants from the NASA planetary and satellite fact sheets).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

AU = 1.495978707e11
SOLAR_CONSTANT = 1361.0  # W/m^2 at 1 AU (literature: Kopp & Lean 2011)

FACT_SHEET = "literature:NASA NSSDCA planetary/satellite fact sheets https://nssdc.gsfc.nasa.gov/planetary/factsheet/"
DEFAULT_BASIS = FACT_SHEET

# Bodies that orbit the Sun: semi-major axis (AU), GM (m^3/s^2), mean radius (m)
PLANETS: dict[str, tuple[float, float, float]] = {
    "mercury": (0.387098, 2.2032e13, 2.4397e6),
    "venus": (0.723332, 3.24859e14, 6.0518e6),
    "earth": (1.000000, 3.986004418e14, 6.371e6),
    "mars": (1.523679, 4.282837e13, 3.3895e6),
    "ceres": (2.7675, 6.26325e10, 4.697e5),
    "jupiter": (5.2044, 1.26686534e17, 6.9911e7),
    "saturn": (9.5826, 3.7931187e16, 5.8232e7),
}

# Surface galactic-cosmic-ray dose on an airless body at 1 AU (half the sky
# blocked by the body). Chang'e 4 LND measured 1,369 uSv/day on the far side.
GCR_AIRLESS_1AU = 1.369  # mSv/day, cited: https://www.sci.news/space/radiation-dose-rates-lunar-surface-08893.html
GCR_AIRLESS_OUTER = 1.6  # mSv/day beyond 2 AU, estimate: weaker solar modulation (+~20%)


@dataclass(frozen=True)
class Resources:
    """What the ground (or air) offers. Fractions are mass fractions of mined feedstock."""

    water_frac: float  # extractable water in the feedstock that is mined
    carbon_source: str | None  # "atmosphere" | "native_ch4" | "ice" | "regolith" | None
    carbon_frac: float = 0.0  # carbon mass fraction of the feedstock, for "ice" or "regolith"
    nitrogen: bool = False  # buffer gas and fertiliser for a settlement
    metals: float = 0.0  # 0..1 index: ease of making steel and aluminium locally
    oxide_regolith: bool = True  # oxygen can be pulled from rock (molten regolith electrolysis)


@dataclass(frozen=True)
class Site:
    key: str
    name: str
    body: str
    parent: str  # "sun" for planets and Ceres, else the planet the moon orbits
    radius_m: float
    gm: float
    moon_orbit_m: float = 0.0  # orbit radius about the parent planet (moons only)
    pressure_bar: float = 0.0
    aero: bool = False  # atmosphere usable for aerocapture and entry
    ascent_dv: float | None = None  # surface to low orbit incl. losses (atmosphere bodies)
    landing_dv: float | None = None  # after entry, to touchdown (atmosphere bodies)
    low_orbit_alt_m: float = 0.0  # parking orbit altitude (atmosphere bodies)
    t_min_k: float = 0.0
    t_max_k: float = 0.0
    night_h: float = 0.0  # longest regular dark period at the site
    day_fraction: float = 0.5  # share of time in sunlight
    solar_attenuation: float = 1.0  # surface flux over top-of-atmosphere flux
    rad_trapped_msv_d: float = 0.0  # trapped-particle (magnetosphere) dose at the surface
    rad_gcr_msv_d: float = GCR_AIRLESS_1AU  # cosmic-ray dose at the surface
    resources: Resources = field(default_factory=lambda: Resources(0.0, None))
    note: str = ""
    basis: dict[str, str] = field(default_factory=dict)

    # ---- derived quantities -------------------------------------------------
    @property
    def a_au(self) -> float:
        """Heliocentric distance of the body (or of its parent planet)."""
        return PLANETS[self.body if self.parent == "sun" else self.parent][0]

    @property
    def surface_g(self) -> float:
        return self.gm / self.radius_m**2

    @property
    def v_escape(self) -> float:
        return math.sqrt(2 * self.gm / self.radius_m)

    @property
    def solar_flux(self) -> float:
        """Mean sunlight at the site, W/m^2 (after any atmosphere)."""
        return SOLAR_CONSTANT / self.a_au**2 * self.solar_attenuation

    @property
    def radiation_msv_yr(self) -> float:
        return 365.25 * (self.rad_trapped_msv_d + self.rad_gcr_msv_d)

    @property
    def t_mean_k(self) -> float:
        return 0.5 * (self.t_min_k + self.t_max_k)

    def basis_of(self, name: str) -> str:
        return self.basis.get(name, DEFAULT_BASIS)


_RAD_MARS = "cited:Hassler et al. 2014 Science, RAD 0.67 mSv/day https://www.swri.org/press-release/swri-scientists-publish-first-radiation-measurements-surface-mars"
_RAD_EUROPA = "cited:5.4 Sv/day (Ringwald 2000 via Wikipedia) https://www.maproomblog.com/tag/jupiter/"
_RAD_JOVIAN = "literature:Ringwald 2000, NASA RASC study (Ganymede 8 rem/day, Callisto 0.01 rem/day)"
_MISSION = "estimate:same value as raptor_sim.mission.MissionAssumptions"


SITES: dict[str, Site] = {
    s.key: s
    for s in [
        Site(
            "moon_south_pole", "Moon, south pole crater rim", "moon", "earth",
            radius_m=1.7374e6, gm=4.9028e12, moon_orbit_m=3.844e8,
            t_min_k=40, t_max_k=250, night_h=100, day_fraction=0.85,
            rad_gcr_msv_d=GCR_AIRLESS_1AU,
            resources=Resources(0.056, "regolith", carbon_frac=0.002, nitrogen=False, metals=0.5),
            note="Template site: detailed design is in the lunar transit base thread.",
            basis={
                "t_min_k": "literature:LRO Diviner, permanently shadowed regions below 40 K",
                "night_h": "estimate:peaks of near-permanent light, longest darkness a few days",
                "day_fraction": "estimate:best rim sites lit 80-90% of the year",
                "rad_gcr_msv_d": "cited:Chang'e 4 LND 1,369 uSv/day https://www.sci.news/space/radiation-dose-rates-lunar-surface-08893.html",
                "resources.water_frac": "literature:LCROSS Cabeus 5.6 +/- 2.9 wt% (Colaprete 2010)",
                "resources.carbon_frac": "estimate:trace CO/CO2 in LCROSS plume",
            },
        ),
        Site(
            "mars_arcadia", "Mars, Arcadia Planitia (mid-latitude ice)", "mars", "sun",
            radius_m=3.3895e6, gm=4.282837e13, pressure_bar=0.006, aero=True,
            ascent_dv=4_100.0, landing_dv=700.0, low_orbit_alt_m=300e3,
            t_min_k=150, t_max_k=270, night_h=12.3, day_fraction=0.5, solar_attenuation=0.55,
            rad_gcr_msv_d=0.67,
            resources=Resources(0.5, "atmosphere", nitrogen=True, metals=0.8),
            note="Raptor-class ships already planned to land here; CO2 air plus shallow ice.",
            basis={
                "ascent_dv": _MISSION, "landing_dv": _MISSION,
                "t_min_k": "estimate:mid-latitude diurnal range",
                "solar_attenuation": "estimate:dust and atmosphere, yearly mean (storms fall to ~0.1)",
                "rad_gcr_msv_d": _RAD_MARS,
                "resources.water_frac": "estimate:SWIM maps of ice within 1 m of the surface; mined ice-rich ground",
            },
        ),
        Site(
            "phobos", "Phobos", "phobos", "mars",
            radius_m=1.108e4, gm=7.087e5, moon_orbit_m=9.376e6,
            t_min_k=160, t_max_k=270, night_h=3.8, day_fraction=0.48,
            rad_gcr_msv_d=1.2,
            resources=Resources(0.02, "regolith", carbon_frac=0.02, metals=0.3),
            note="Composition unknown until MMX; carbonaceous-like regolith is assumed.",
            basis={
                "gm": "literature:Jacobson 2010, GM 0.0007087 km^3/s^2",
                "rad_gcr_msv_d": "estimate:deep-space GCR with body and Mars shielding",
                "night_h": "literature:7.65 h rotation plus Mars eclipses",
                "resources.water_frac": "estimate:hydrated-mineral content if carbonaceous, very uncertain",
                "resources.carbon_frac": "estimate:CM-chondrite-like 2 wt% C, very uncertain",
            },
        ),
        Site(
            "deimos", "Deimos", "deimos", "mars",
            radius_m=6.2e3, gm=9.62e4, moon_orbit_m=2.34632e7,
            t_min_k=160, t_max_k=270, night_h=15.1, day_fraction=0.5,
            rad_gcr_msv_d=1.2,
            resources=Resources(0.02, "regolith", carbon_frac=0.02, metals=0.3),
            basis={
                "rad_gcr_msv_d": "estimate:deep-space GCR with body shielding",
                "resources.water_frac": "estimate:as Phobos, very uncertain",
                "resources.carbon_frac": "estimate:as Phobos, very uncertain",
            },
        ),
        Site(
            "ceres", "Ceres, mid-latitude near Occator", "ceres", "sun",
            radius_m=4.697e5, gm=6.26325e10,
            t_min_k=110, t_max_k=235, night_h=4.5, day_fraction=0.5,
            rad_gcr_msv_d=GCR_AIRLESS_OUTER,
            resources=Resources(0.2, "regolith", carbon_frac=0.05, nitrogen=True, metals=0.4),
            note="Ice-rich crust, organics and carbonates, ammoniated clays: all of C, H, O, N.",
            basis={
                "t_min_k": "literature:Dawn VIR surface temperatures",
                "rad_gcr_msv_d": "estimate:airless body beyond 2 AU",
                "resources.water_frac": "literature:Dawn GRaND, 10-30 wt% ice in the shallow subsurface at mid/high latitudes",
                "resources.carbon_frac": "literature:Dawn, carbon-rich surface (Prettyman 2019, ~up to 20 wt% C locally); 5% used",
                "resources.nitrogen": "literature:Dawn, ammoniated phyllosilicates (De Sanctis 2015)",
            },
        ),
        Site(
            "callisto", "Callisto", "callisto", "jupiter",
            radius_m=2.4103e6, gm=7.179e12, moon_orbit_m=1.8827e9,
            t_min_k=80, t_max_k=165, night_h=200, day_fraction=0.5,
            rad_trapped_msv_d=0.1, rad_gcr_msv_d=GCR_AIRLESS_OUTER,
            resources=Resources(0.4, "ice", carbon_frac=0.01, metals=0.3),
            note="Outside Jupiter's main radiation belts; the classic Jovian base site (NASA HOPE study).",
            basis={
                "rad_trapped_msv_d": _RAD_JOVIAN, "rad_gcr_msv_d": "estimate:airless body beyond 2 AU",
                "night_h": "literature:16.69-day synchronous rotation",
                "resources.water_frac": "estimate:bulk ~50% ice, dirty surface ice mined",
                "resources.carbon_frac": "estimate:CO2 ice detected by Galileo NIMS; 1% of feedstock",
            },
        ),
        Site(
            "ganymede", "Ganymede", "ganymede", "jupiter",
            radius_m=2.6341e6, gm=9.8878e12, moon_orbit_m=1.0704e9,
            t_min_k=70, t_max_k=152, night_h=86, day_fraction=0.5,
            rad_trapped_msv_d=80.0, rad_gcr_msv_d=GCR_AIRLESS_OUTER,
            resources=Resources(0.5, "ice", carbon_frac=0.005, metals=0.3),
            basis={
                "rad_trapped_msv_d": _RAD_JOVIAN, "rad_gcr_msv_d": "estimate:airless body beyond 2 AU",
                "resources.water_frac": "estimate:ice-rich crust",
                "resources.carbon_frac": "estimate:CO2 ice detected; 0.5% of feedstock",
            },
        ),
        Site(
            "europa", "Europa", "europa", "jupiter",
            radius_m=1.5608e6, gm=3.2027e12, moon_orbit_m=6.711e8,
            t_min_k=50, t_max_k=125, night_h=42.6, day_fraction=0.5,
            rad_trapped_msv_d=5_400.0, rad_gcr_msv_d=GCR_AIRLESS_OUTER,
            resources=Resources(0.95, "ice", carbon_frac=0.002, metals=0.1),
            note="Lethal surface radiation; a science destination, not a crewed hub.",
            basis={
                "rad_trapped_msv_d": _RAD_EUROPA, "rad_gcr_msv_d": "estimate:airless body beyond 2 AU",
                "resources.water_frac": "literature:water-ice shell",
                "resources.carbon_frac": "estimate:CO2 detected by JWST at Tara Regio; trace",
            },
        ),
        Site(
            "titan", "Titan, lake shore (Kraken/Ligeia Mare region)", "titan", "saturn",
            radius_m=2.5747e6, gm=8.978e12, moon_orbit_m=1.22187e9,
            pressure_bar=1.47, aero=True, ascent_dv=2_600.0, landing_dv=150.0,
            low_orbit_alt_m=1_500e3,
            t_min_k=90, t_max_k=94, night_h=191, day_fraction=0.5, solar_attenuation=0.1,
            rad_gcr_msv_d=0.01,
            resources=Resources(0.9, "native_ch4", nitrogen=True, metals=0.05),
            note="Liquid methane lies on the surface; oxygen must come from the water-ice bedrock.",
            basis={
                "pressure_bar": "literature:Huygens 1.467 bar, 93.7 K",
                "ascent_dv": "estimate:1.4 x surface circular speed (1.87 km/s) for drag and gravity losses",
                "landing_dv": "estimate:aeroshell and parachute, small terminal burn",
                "low_orbit_alt_m": "estimate:above the extended atmosphere (Cassini flybys at ~950 km)",
                "solar_attenuation": "estimate:surface sunlight ~0.1% of Earth's",
                "rad_gcr_msv_d": "estimate:~11 kg/cm^2 of atmosphere overhead",
                "resources.water_frac": "estimate:water-ice bedrock",
            },
        ),
        Site(
            "enceladus", "Enceladus, south polar terrain", "enceladus", "saturn",
            radius_m=2.521e5, gm=7.211e9, moon_orbit_m=2.37948e8,
            t_min_k=33, t_max_k=145, night_h=16.4, day_fraction=0.5,
            rad_trapped_msv_d=0.5, rad_gcr_msv_d=GCR_AIRLESS_OUTER,
            resources=Resources(0.95, "ice", carbon_frac=0.005, nitrogen=True, metals=0.02),
            basis={
                "rad_trapped_msv_d": "estimate:inside Saturn's E ring, belts far weaker than Jupiter's",
                "rad_gcr_msv_d": "estimate:airless body beyond 2 AU",
                "resources.carbon_frac": "literature:Cassini INMS plume CO2, CH4, organics at ~1% level; 0.5% used",
                "resources.nitrogen": "literature:Cassini INMS NH3 in plume",
            },
        ),
        Site(
            "venus_clouds", "Venus, aerostat at ~54 km", "venus", "sun",
            radius_m=6.0518e6, gm=3.24859e14, pressure_bar=0.5, aero=True,
            ascent_dv=7_900.0, landing_dv=100.0, low_orbit_alt_m=300e3,
            t_min_k=290, t_max_k=330, night_h=48, day_fraction=0.5, solar_attenuation=0.8,
            rad_gcr_msv_d=0.002,
            resources=Resources(0.0001, "atmosphere", nitrogen=True, metals=0.0, oxide_regolith=False),
            note="Earth-like pressure and temperature, but no ground: rockets launch from a balloon.",
            basis={
                "pressure_bar": "literature:Venus atmosphere ~0.5 bar, ~300 K near 54 km",
                "ascent_dv": "estimate:orbital speed 7.2 km/s plus losses from a balloon launch",
                "landing_dv": "estimate:entry, parachute and balloon inflation",
                "night_h": "estimate:aerostat drifts with the 4-day super-rotation",
                "solar_attenuation": "estimate:above most of the cloud deck",
                "rad_gcr_msv_d": "estimate:~500 g/cm^2 of atmosphere overhead",
                "resources.water_frac": "estimate:water bound in sulphuric-acid droplets",
            },
        ),
        Site(
            "mercury_north_pole", "Mercury, north polar crater rim", "mercury", "sun",
            radius_m=2.4397e6, gm=2.2032e13,
            t_min_k=50, t_max_k=400, night_h=48, day_fraction=0.8,
            rad_gcr_msv_d=1.5,
            resources=Resources(0.3, "regolith", carbon_frac=0.02, metals=0.6),
            note="Strong sunlight next to permanently shadowed ice; deep in the Sun's gravity well.",
            basis={
                "t_min_k": "literature:MESSENGER, polar cold traps",
                "night_h": "estimate:Sun skims the horizon; rim sites nearly always lit",
                "day_fraction": "estimate:rim site",
                "rad_gcr_msv_d": "estimate:weak magnetosphere, frequent solar particle events",
                "resources.water_frac": "literature:MESSENGER, near-pure ice in polar deposits; 30% of mined feedstock used",
                "resources.carbon_frac": "literature:MESSENGER, 1-4 wt% graphite in crust (Peplowski 2016)",
            },
        ),
    ]
}


def get_site(key: str) -> Site:
    return SITES[key]
