"""Lunar transit base and spaceport feasibility models.

Every numeric input carries a provenance tag through :class:`Value`:
"cited" (published source, given in ``source``), "computed" (derived in this
package from physics and cited inputs) or "estimated" (engineering judgement,
to be replaced by better data). The study report lists them all.

Modules:
    orbits        Earth-Moon delta-v legs and departures to Mars (shared with crewed_lunar)
    site          South-pole site candidates, scoring and a synthetic illumination series
    power         Hourly power balance through the lunar night (solar, fission, storage)
    isru          Ice mining, electrolysis, liquefaction and regolith oxygen
    construction  Radiation shielding, habitat cover, pad sintering and berms
    plume         Landing plume pressure on the surface, pad sizing and ejecta ranges
    depot         Cryogenic storage boil-off and surface-to-orbit propellant shuttling
    mars_benefit  Mars departure with Moon-sourced propellant versus LEO refilling
    buildup       Phased buildup manifest and cargo flights
    reuse         Map of reused capabilities across the project
    checks        Verification checks with pass/fail criteria
"""

from .provenance import Value

__all__ = ["Value"]
