"""Which capabilities each site needs, derived from the site, power, ISRU and network models.

The result is a site-by-capability matrix. Capabilities used at many sites are
the reusable "base kit"; capabilities used at one or two are site-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .isru import isru_plan
from .network import Route
from .power import best_power
from .sites import SITES, Site

LIGHT_MIN_PER_AU = 8.317


@dataclass(frozen=True)
class Capability:
    key: str
    name: str
    group: str
    origin: str  # where in the project it is first built or proven
    needs: Callable[[Site, dict], bool]


def _ctx(site: Site, routes: dict[str, Route]) -> dict:
    plan = isru_plan(site)
    return {
        "chain": plan.best.name,
        "passive": plan.passive_cryo,
        "power_1mw": best_power(site, 1_000).kind,
        "power_100kw": best_power(site, 100).kind,
        "route": routes.get(site.key),
        "light_min": (site.a_au + 1.0) * LIGHT_MIN_PER_AU,
    }


CAPABILITIES: list[Capability] = [
    # Transport
    Capability("ch4_engine", "Raptor-class methane/oxygen engine and reusable ship", "transport",
               "PR #1/#2 engine model", lambda s, c: True),
    Capability("orbital_refill", "Ship-to-ship propellant transfer", "transport",
               "Earth LEO tanker campaign", lambda s, c: True),
    Capability("aero_entry", "Aerocapture and entry heat shield", "transport", "Earth return / Mars",
               lambda s, c: s.aero),
    Capability("propulsive_landing", "Propulsive landing on airless bodies", "transport", "Moon",
               lambda s, c: not s.aero),
    Capability("microgravity_ops", "Anchoring and docking-style operations at milli-g", "transport",
               "Phobos", lambda s, c: s.surface_g < 0.05),
    Capability("advanced_transfer", "Gravity assists or high-Isp (nuclear/electric) stages", "transport",
               "none yet", lambda s, c: c["route"] is not None and c["route"].cargo_t <= 0),
    # Energy
    Capability("fission_power", "Fission surface power (FSP 40 kWe and up)", "energy", "Moon (NASA FSP)",
               lambda s, c: c["power_1mw"] == "fission"),
    Capability("solar_power", "Solar arrays with storage", "energy", "Moon / Mars",
               lambda s, c: c["power_100kw"] == "solar+storage"),
    Capability("night_storage", "Regenerative fuel cells for long nights", "energy", "Moon",
               lambda s, c: c["power_100kw"] == "solar+storage" and s.night_h > 24),
    # Resources and propellant
    Capability("ice_mining", "Ice mining and water extraction", "ISRU", "Moon / Mars",
               lambda s, c: c["chain"] in ("sabatier", "native_ch4", "o2_water")),
    Capability("electrolysis", "Water electrolysis", "ISRU", "Moon / Mars",
               lambda s, c: c["chain"] in ("sabatier", "native_ch4", "o2_water", "imported_h2")),
    Capability("sabatier", "Sabatier methanation", "ISRU", "Mars",
               lambda s, c: c["chain"] in ("sabatier", "imported_h2")),
    Capability("co2_capture", "CO2 capture from the atmosphere", "ISRU", "Mars",
               lambda s, c: s.resources.carbon_source == "atmosphere"),
    Capability("carbon_pyrolysis", "Carbon from rock or ice (pyrolysis)", "ISRU", "Ceres / Phobos",
               lambda s, c: c["chain"] == "sabatier" and s.resources.carbon_source in ("ice", "regolith")),
    Capability("regolith_o2", "Oxygen from regolith (molten regolith electrolysis)", "ISRU", "Moon",
               lambda s, c: c["chain"] == "o2_regolith"),
    Capability("hydrocarbon_handling", "Native hydrocarbon harvesting", "ISRU", "Titan",
               lambda s, c: c["chain"] == "native_ch4"),
    Capability("methane_import", "Methane supply chain from another hub", "ISRU", "Moon",
               lambda s, c: c["chain"] in ("o2_water", "o2_regolith")),
    Capability("active_cryo", "Cryocoolers for zero boil-off storage", "ISRU", "Moon / Mars",
               lambda s, c: not c["passive"]),
    Capability("passive_cryo", "Passive cold storage (radiators only)", "ISRU", "Callisto / Titan",
               lambda s, c: c["passive"]),
    # Construction and industry
    Capability("pad_sintering", "Landing pad by regolith sintering / ice paving", "construction", "Moon",
               lambda s, c: s.key != "venus_clouds"),
    Capability("shield_burial", "Habitat shielding with regolith or ice", "construction", "Moon / Mars",
               lambda s, c: s.radiation_msv_yr > 50),
    Capability("deep_shield", "Deep burial for trapped-particle belts (>10 Sv/yr)", "construction",
               "Ganymede / Europa", lambda s, c: s.radiation_msv_yr > 10_000),
    Capability("cryo_construction", "Building on ice below 120 K", "construction", "Callisto",
               lambda s, c: s.t_mean_k < 120),
    Capability("aerostat", "Floating habitat and launch platform", "construction", "Venus",
               lambda s, c: s.key == "venus_clouds"),
    Capability("local_steel", "Steel and aluminium from local ore", "industry", "Mars",
               lambda s, c: s.resources.metals >= 0.5),
    Capability("ship_assembly", "On-site ship assembly and repair hangar", "industry", "Mars",
               lambda s, c: s.key != "venus_clouds"),
    Capability("additive_mfg", "Additive manufacturing of spares (engine parts first)", "industry",
               "PR #2 BOM", lambda s, c: True),
    # People and operations
    Capability("eclss", "Closed-loop life support", "habitation", "ISS / Moon", lambda s, c: True),
    Capability("autonomy", "Autonomous operations (light time over 20 min)", "operations", "Mars",
               lambda s, c: c["light_min"] > 20),
    Capability("relay_comms", "Relay communications network", "operations", "Mars",
               lambda s, c: True),
]


def capability_matrix(routes: dict[str, Route]) -> dict[str, dict[str, bool]]:
    """{capability key: {site key: needed}}"""
    ctx = {k: _ctx(s, routes) for k, s in SITES.items()}
    return {cap.key: {k: bool(cap.needs(s, ctx[k])) for k, s in SITES.items()} for cap in CAPABILITIES}


def reuse_summary(matrix: dict[str, dict[str, bool]]) -> list[tuple[str, int]]:
    """Capabilities sorted by how many sites use them."""
    return sorted(((k, sum(v.values())) for k, v in matrix.items()), key=lambda t: -t[1])
