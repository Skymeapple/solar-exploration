"""Base power: solar arrays with storage versus fission versus radioisotope.

All options deliver a continuous electrical load. Masses are installed masses
landed at the site (kg). Sunlight falls with the square of distance from the
Sun and with the site's atmosphere; long nights need storage, which is what
makes solar heavy at the Moon's equator, Callisto or Titan.
"""

from __future__ import annotations

from dataclasses import dataclass

from .sites import Site


@dataclass(frozen=True)
class PowerAssumptions:
    pv_efficiency: float = 0.30  # estimate: multi-junction cells, end of life
    pv_tracking_factor: float = 0.80  # estimate: mean cosine and packing with sun tracking
    pv_areal_mass: float = 2.5  # kg/m^2, estimate: deployed surface array with structure
    storage_specific_energy: float = 0.6  # kWh/kg, estimate: regenerative fuel cell with tanks
    storage_round_trip: float = 0.55  # estimate: regenerative fuel cell
    fission_ref_kwe: float = 40.0  # cited: NASA FSP 40 kWe, <6 t, 10 yr (IAC 2024)
    fission_ref_mass_kg: float = 6_000.0  # cited: same source
    fission_scale_exp: float = 0.7  # estimate: mass ~ power^0.7 toward MW-class units
    rtg_kg_per_kwe: float = 409.0  # literature: MMRTG 110 We, 45 kg
    rtg_max_kwe: float = 10.0  # estimate: Pu-238 supply limits RTGs to small loads


FSP_SOURCE = "https://ntrs.nasa.gov/api/citations/20240011694/downloads/IAC%202024%20Manuscript_FSP%20FINAL.pdf"


@dataclass(frozen=True)
class PowerOption:
    kind: str
    mass_t: float
    kg_per_kwe: float
    feasible: bool
    note: str = ""


def solar_mass_kg(site: Site, load_kwe: float, a: PowerAssumptions = PowerAssumptions()) -> float:
    """Array plus storage to carry `load_kwe` through the site's day/night cycle."""
    flux = site.solar_flux  # W/m^2 mean in daylight
    if flux <= 0:
        return float("inf")
    f_day = site.day_fraction
    t_night_h = site.night_h
    t_day_h = t_night_h * f_day / max(1 - f_day, 1e-6)
    # Daylight generation covers the load plus recharging storage for the night.
    p_array_kw = load_kwe * (1 + (t_night_h / t_day_h) / a.storage_round_trip)
    area = p_array_kw * 1e3 / (flux * a.pv_efficiency * a.pv_tracking_factor)
    storage_kg = load_kwe * t_night_h / a.storage_specific_energy
    return area * a.pv_areal_mass + storage_kg


def fission_mass_kg(load_kwe: float, a: PowerAssumptions = PowerAssumptions()) -> float:
    """Units of up to 10 MWe each, scaled from the 40 kWe FSP point."""
    unit_max = 10_000.0
    n = max(1, int(-(-load_kwe // unit_max)))
    per_unit = load_kwe / n
    return n * a.fission_ref_mass_kg * (per_unit / a.fission_ref_kwe) ** a.fission_scale_exp


def power_options(site: Site, load_kwe: float, a: PowerAssumptions = PowerAssumptions()) -> list[PowerOption]:
    sol = solar_mass_kg(site, load_kwe, a)
    fis = fission_mass_kg(load_kwe, a)
    rtg = load_kwe * a.rtg_kg_per_kwe
    return [
        PowerOption("solar+storage", sol / 1e3, sol / load_kwe, True,
                    f"{site.solar_flux:.0f} W/m^2 mean, {site.night_h:.0f} h night"),
        PowerOption("fission", fis / 1e3, fis / load_kwe, True, "FSP-class, scaled"),
        PowerOption("radioisotope", rtg / 1e3, a.rtg_kg_per_kwe, load_kwe <= a.rtg_max_kwe,
                    "Pu-238 limited"),
    ]


def best_power(site: Site, load_kwe: float, a: PowerAssumptions = PowerAssumptions()) -> PowerOption:
    return min((o for o in power_options(site, load_kwe, a) if o.feasible), key=lambda o: o.mass_t)


def solar_fission_crossover_kwe(site: Site, a: PowerAssumptions = PowerAssumptions()) -> float | None:
    """Load above which fission is lighter than solar at this site (None: solar never loses
    below 100 MWe; 0: fission always lighter above 1 kWe)."""
    lo, hi = 1.0, 1e5
    f = lambda p: solar_mass_kg(site, p, a) - fission_mass_kg(p, a)
    if f(lo) > 0:
        return 0.0
    if f(hi) < 0:
        return None
    for _ in range(80):
        mid = (lo * hi) ** 0.5
        lo, hi = (mid, hi) if f(mid) < 0 else (lo, mid)
    return hi
