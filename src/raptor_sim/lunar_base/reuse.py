"""Which capabilities of the overall framework the lunar base reuses, and what it gives back.

status:
  "reused in code"      imported and run by lunar_base today
  "reusable by design"  the same model applies with new inputs; not yet wired
  "new here"            built in lunar_base, offered to the rest of the project
  "gap"                 needed but not modelled anywhere yet
"""

from __future__ import annotations

CAPABILITIES: tuple[dict[str, str], ...] = (
    # From the engine and vehicle work (PR #1)
    {"capability": "NASA CEA combustion chemistry", "source": "raptor_sim.thermo (PR #1)",
     "lunar use": "CEA chemistry reused by the hydrogen engine model (raptor_sim.hydrolox)",
     "status": "reused in code"},
    {"capability": "Engine sizing and nozzle exit state", "source": "raptor_sim.engine (PR #1)",
     "lunar use": "exit Mach of the Raptor-class nozzle for the plume and pad model", "status": "reused in code"},
    {"capability": "Two-stage vehicle performance", "source": "raptor_sim.mission.vehicle_performance (PR #1)",
     "lunar use": "payload to LEO and Isp values behind every Earth-launch count", "status": "reused in code"},
    {"capability": "Patched-conic transfers and Mars mission", "source": "raptor_sim.mission (PR #1)",
     "lunar use": "Mars v-infinity, LEO refill baseline (scenario A)", "status": "reused in code"},
    {"capability": "Design optimizer (Optuna)", "source": "raptor_sim.optimize (PR #1)",
     "lunar use": "can search pad layout, plant size and power mix against the checks", "status": "reusable by design"},
    {"capability": "Verification gates G0-G7", "source": "procedure document, raptor_sim.gates (PR #1)",
     "lunar use": "same pass/fail style for checks L1-L10", "status": "reused in code"},
    # From component design (PR #2)
    {"capability": "Turbopump and cooling models, materials", "source": "raptor_sim.components (PR #2)",
     "lunar use": "throttle range for a lunar landing engine (deep throttling sets the plume load); "
                  "cryocooler and pump sizing for depots", "status": "reusable by design"},
    {"capability": "BOM, drawings and cost roll-up", "source": "raptor_sim.components, raptor_sim.econ",
     "lunar use": "cost of lunar plant, pads and tankers per tonne; spare-parts manifest for on-site engine swaps",
     "status": "reusable by design"},
    # From parallel threads
    {"capability": "Powered descent and ascent simulation", "source": "raptor_sim.crewed_lunar (crewed lunar thread)",
     "lunar use": "replaces the LLO-surface placeholders in orbits.LEGS; hover time for the erosion index",
     "status": "reusable by design"},
    {"capability": "Life support and radiation", "source": "raptor_sim.crew (crewed missions thread)",
     "lunar use": "habitat critical load, consumables, dose budget for regolith cover", "status": "reusable by design"},
    {"capability": "Solar-system base network and ranking", "source": "raptor_sim.bases (transit bases thread)",
     "lunar use": "the Moon as one node; can import lunar_base ISRU and orbits for its moon_south_pole entry",
     "status": "reusable by design"},
    {"capability": "Mission economics and financing", "source": "raptor_sim.econ (business thread)",
     "lunar use": "price of lunar propellant at NRHO and LEO versus Earth-launched propellant",
     "status": "reusable by design"},
    # Given back by the lunar base
    {"capability": "Shared lunar delta-v table with provenance", "source": "lunar_base.orbits",
     "lunar use": "single source for all lunar legs; departures to Mars from EML1, NRHO, LLO", "status": "new here"},
    {"capability": "Polar ice ISRU plant sizing", "source": "lunar_base.isru",
     "lunar use": "water, hydrolox or lunar LOX for methalox, energy chain calibrated to Kornuta 2019",
     "status": "new here"},
    {"capability": "Hourly power balance with storage sizing", "source": "lunar_base.power",
     "lunar use": "any site with an illumination series (Mars dust storms, Mercury poles, Ceres)",
     "status": "new here"},
    {"capability": "Plume-surface interaction and pad sizing", "source": "lunar_base.plume",
     "lunar use": "pads at any airless body (Phobos, Ceres, Mercury); Mars needs an atmosphere term",
     "status": "new here"},
    {"capability": "Depot boil-off and shuttle gear ratio", "source": "lunar_base.depot",
     "lunar use": "LEO, NRHO, Mars orbit depots", "status": "new here"},
    {"capability": "Earth-launch accounting for off-world propellant", "source": "lunar_base.mars_benefit",
     "lunar use": "decides where off-world propellant pays", "status": "new here"},
    {"capability": "Hydrogen-oxygen engine design", "source": "raptor_sim.hydrolox",
     "lunar use": "HL-250 expander tanker engine (450.6 s) and HL-44 lander engine (460.2 s), gates H1-H7",
     "status": "reused in code"},
    # Gaps
    {"capability": "Terrain-exact illumination from LOLA", "source": "none yet",
     "lunar use": "replace the synthetic horizon in site.illumination_series", "status": "gap"},
    {"capability": "Aerocapture into LEO for returning tankers", "source": "partly raptor_sim.crew.entry",
     "lunar use": "scenario C assumes it at 100 m/s trim", "status": "gap"},
)


def table() -> list[dict[str, str]]:
    return list(CAPABILITIES)
