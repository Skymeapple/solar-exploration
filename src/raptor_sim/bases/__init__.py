"""Transit bases across the solar system.

Site data, power and ISRU balances, a delta-v network with refuelling at each
hub, base build-up logistics, a site ranking and a reusable-capability map.

Every input value carries a basis tag (see :mod:`raptor_sim.bases.sites`):

* ``cited``      checked against the named source during this study
* ``literature`` a standard published value with its source named, not re-checked here
* ``estimate``   an engineering assumption made for this study
"""

from .sites import SITES, Site, get_site
from .power import power_options, best_power
from .isru import isru_plan, ISRUPlan
from .network import Ship, leg_dv, build_network, stepping_stone_routes
from .logistics import base_buildup
from .ranking import rank_sites
from .capabilities import capability_matrix

__all__ = [
    "SITES", "Site", "get_site", "power_options", "best_power", "isru_plan", "ISRUPlan",
    "Ship", "leg_dv", "build_network", "stepping_stone_routes", "base_buildup",
    "rank_sites", "capability_matrix",
]
