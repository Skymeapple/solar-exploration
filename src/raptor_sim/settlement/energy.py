"""Energy: demand per resident, propellant-plant energy, and supply options by site.

Demand per resident = life support + habitat + food production + industry.
Food is grown under LEDs by default (crop area x light level / LED efficacy,
plus the heat pump work to remove that heat). Industry is the largest and least
known term; the study runs it as a range.

Propellant: the overall Mars reaction is CO2 + 2 H2O -> CH4 + 2 O2. Sabatier
needs 0.5 kg of electrolysed H2 per kg of CH4; the same electrolysis gives
4 kg of O2 per kg of CH4, more than the 3.6 mixture ratio needs.

Supply: solar arrays sized for the site's average surface flux with batteries
for the night (and optionally oversized to ride out a dust storm), or fission
units at the FSP 40 kWe class.
"""
from __future__ import annotations

from dataclasses import dataclass

from .inputs import v

MIXTURE_RATIO = 3.6  # O/F of the engine model (raptor_sim.engine reference design)
CO2_CAPTURE_KWH_PER_KG = 0.2  # estimate: freeze-out or compression from 6 mbar


def food_power_per_person(area_m2: float | None = None, sunlit_share: float = 0.0) -> float:
    """Average electrical power (kW) to light and cool one person's crops."""
    area = v("crop_area_per_person") if area_m2 is None else area_m2
    light_w = area * v("ppfd") / v("led_efficacy") * v("photoperiod_h") / 24.0
    light_w *= 1.0 - sunlit_share
    hvac_w = light_w / v("hvac_cop")
    return (light_w + hvac_w) / 1e3


def demand_per_person(industry_kw: float | None = None, sunlit_share: float = 0.0) -> dict[str, float]:
    ind = v("industry_power_per_person") if industry_kw is None else industry_kw
    d = {
        "life_support_kw": v("eclss_power_per_person"),
        "habitat_kw": v("habitat_power_per_person"),
        "food_kw": food_power_per_person(sunlit_share=sunlit_share),
        "industry_kw": ind,
    }
    d["total_kw"] = sum(d.values())
    return d


@dataclass(frozen=True)
class PropellantPlant:
    kwh_per_kg_propellant: float
    water_kg_per_kg: float
    co2_kg_per_kg: float
    o2_surplus_kg_per_kg: float  # O2 left over after LOX at the mixture ratio


def propellant_energy(mr: float = MIXTURE_RATIO) -> PropellantPlant:
    """Energy and feedstock per kg of CH4/LOX made on Mars."""
    ch4 = 1.0 / (1.0 + mr)  # kg CH4 per kg propellant
    h2 = 0.5 * ch4  # 4 H2 per CH4: 8 g per 16 g
    water = 2.25 * ch4  # net 2 H2O per CH4
    co2 = 44.0 / 16.0 * ch4
    o2_made = 4.0 * ch4
    o2_need = mr * ch4
    kwh = (
        h2 * v("electrolysis_kwh_per_kg_h2")
        + water * v("water_mining_kwh_per_kg")
        + co2 * CO2_CAPTURE_KWH_PER_KG
        + 1.0 * v("liquefaction_kwh_per_kg")
    )
    return PropellantPlant(kwh, water, co2, o2_made - o2_need)


def propellant_plant_kw(tonnes: float, days: float) -> float:
    """Average power (kW) to make `tonnes` of propellant in `days`."""
    return tonnes * 1e3 * propellant_energy().kwh_per_kg_propellant / (days * 24.0)


@dataclass(frozen=True)
class Site:
    name: str
    sun_au: float
    atm_transmission: float  # clear-sky mean, incl. diffuse
    night_hours: float  # longest routine dark period
    storm_transmission: float  # worst routine dimming (1.0 = none)
    storm_days: float
    tracking_factor: float = 0.4  # 24 h average / peak flux for a single-axis tracker incl. night (estimate)


SOLAR_SITES = {
    "Mars equator": Site("Mars equator", 1.524, 0.6, 12.3, 0.15, 60.0),
    "Moon south pole ridge": Site("Moon south pole ridge", 1.0, 1.0, 100.0, 1.0, 0.0, tracking_factor=0.65),  # ~80% illuminated ridge, estimate
    "Moon equator": Site("Moon equator", 1.0, 1.0, 354.0, 1.0, 0.0, tracking_factor=0.3),
    "Ceres": Site("Ceres", 2.77, 1.0, 4.5, 1.0, 0.0),
    "Callisto": Site("Callisto", 5.2, 1.0, 200.0, 1.0, 0.0),
    "Titan": Site("Titan", 9.58, 0.1, 190.0, 1.0, 0.0),
}


def solar_mass_per_kwe(site: Site, storm_proof: bool = False, dod: float = 0.8) -> float:
    """Imported mass (kg) per kW of continuous load from solar plus batteries."""
    # tracking_factor is the 24-hour (or full-lunation) average over peak, so an
    # array sized to the average automatically refills the night store.
    flux = v("solar_const") / site.sun_au**2 * site.atm_transmission * site.tracking_factor
    if storm_proof:
        flux *= site.storm_transmission
    area = 1000.0 / (flux * v("pv_efficiency"))
    battery_kwh = site.night_hours * 1.0 / dod
    return area * v("pv_specific_mass") + battery_kwh / v("battery_specific_energy")


def fission_mass_per_kwe() -> float:
    return v("fission_unit_mass") / v("fission_unit_kwe")


def supply_table() -> list[dict]:
    rows = []
    for s in SOLAR_SITES.values():
        rows.append(
            {
                "site": s.name,
                "solar_kg_per_kwe": solar_mass_per_kwe(s),
                "solar_storm_proof_kg_per_kwe": solar_mass_per_kwe(s, storm_proof=True) if s.storm_transmission < 1 else solar_mass_per_kwe(s),
                "fission_kg_per_kwe": fission_mass_per_kwe(),
            }
        )
    return rows
