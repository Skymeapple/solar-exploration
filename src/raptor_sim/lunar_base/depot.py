"""Cryogenic propellant depots and the surface-to-orbit tanker shuttle.

Depot heat leak uses a flux per tank surface area for each location; the
boil-off follows from the latent heat, and zero boil-off needs cryocooler
input power of (heat leak) x (specific power of the cooler at that temperature).

The shuttle is a reusable single-stage tanker that fills on the surface, flies to
the depot orbit, offloads, and flies back on its own reserve. The model gives the
delivered fraction ("gear ratio") and, for methane-oxygen tankers, how much
imported methane the shuttle itself burns, which decides whether lunar oxygen
pays off for a methane-oxygen engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..constants import G0
from . import orbits
from .provenance import Value

PROPS: dict[str, dict[str, float]] = {
    # density kg/m^3, latent heat J/kg, boiling point K
    "LOX": {"rho": 1141.0, "h_vap": 213e3, "t_boil": 90.2},
    "LCH4": {"rho": 422.6, "h_vap": 510e3, "t_boil": 111.6},
    "LH2": {"rho": 70.8, "h_vap": 446e3, "t_boil": 20.3},
}

SPEC: dict[str, Value] = {
    "q_surface_shaded": Value(0.15, "W/m^2", "estimated", "MLI tank in a shaded polar location with sunshade"),
    "q_orbit": Value(0.40, "W/m^2", "estimated", "MLI tank with sunshield in NRHO or EML1 (sunlit, Earth and Moon IR)"),
    "q_surface_sunlit": Value(1.0, "W/m^2", "estimated", "MLI tank on a lit ridge, low sun but warm surroundings"),
    "cooler_w_per_w_90k": Value(15.0, "W/W", "estimated", "reverse-Brayton cryocooler at 90 K"),
    "cooler_w_per_w_20k": Value(120.0, "W/W", "estimated", "reverse-Brayton cryocooler at 20 K"),
    "tanker_dry_t": Value(100.0, "t", "estimated", "Starship-class ship, Block 1 public dry mass, matches mission.Vehicle"),
    "tanker_prop_t": Value(1_600.0, "t", "cited", "Starship Block 3 ship propellant, https://en.wikipedia.org/wiki/SpaceX_Starship"),
    "hydrolox_isp": Value(450.0, "s", "computed", "replaced at run time by thermo model when CEA is available"),
}


def tank_area_m2(mass_t: float, prop: str) -> float:
    """Surface area of a sphere holding `mass_t` (a cluster of spheres would be larger)."""
    v = mass_t * 1e3 / PROPS[prop]["rho"]
    r = (3 * v / (4 * math.pi)) ** (1 / 3)
    return 4 * math.pi * r * r


@dataclass(frozen=True)
class DepotResult:
    location: str
    prop: str
    mass_t: float
    heat_leak_w: float
    boiloff_pct_per_month: float
    zbo_power_kw: float


def depot(prop: str, mass_t: float, location: str) -> DepotResult:
    q = {"surface_shaded": SPEC["q_surface_shaded"], "orbit": SPEC["q_orbit"], "surface_sunlit": SPEC["q_surface_sunlit"]}[location].value
    area = tank_area_m2(mass_t, prop)
    heat = q * area
    boil_kg_month = heat / PROPS[prop]["h_vap"] * 30 * 86400
    spec = SPEC["cooler_w_per_w_20k"].value if prop == "LH2" else SPEC["cooler_w_per_w_90k"].value
    return DepotResult(location, prop, mass_t, heat, 100 * boil_kg_month / (mass_t * 1e3), heat * spec / 1e3)


def hydrolox_isp(mr: float = 6.0, pc: float = 100e5, eps: float = 100.0, eta: float = 0.946) -> float:
    """Vacuum Isp of a hydrogen-oxygen tug engine from NASA CEA, with the project's calibrated efficiency."""
    try:
        from rocketcea.cea_obj import CEA_Obj

        c = CEA_Obj(oxName="LOX", fuelName="LH2")
        return eta * float(c.get_Isp(Pc=pc / 6894.757, MR=mr, eps=eps))
    except Exception:  # pragma: no cover - CEA not installed
        return SPEC["hydrolox_isp"].value


@dataclass(frozen=True)
class ShuttleResult:
    name: str
    isp_s: float
    dv_up: float
    dv_down: float
    delivered_t: float  # propellant offloaded at the depot per round trip
    burned_t: float  # propellant the shuttle burns per round trip
    gear_ratio: float  # delivered / (delivered + burned)
    imported_fuel_burned_t: float  # Earth methane burned by the shuttle per trip (methalox only)
    imported_fuel_per_t_lunar_ox_delivered: float


def shuttle(name: str, isp_s: float, dry_t: float, prop_t: float, dv_up: float, dv_down: float,
            mixture_ratio: float | None = None, fuel_imported: bool = False) -> ShuttleResult:
    ve = isp_s * G0
    m0 = dry_t + prop_t
    m1 = m0 / math.exp(dv_up / ve)  # at the depot, before offloading
    return_prop = dry_t * (math.exp(dv_down / ve) - 1)
    delivered = m1 - dry_t - return_prop
    if delivered <= 0:
        delivered = 0.0
    burned = prop_t - delivered
    imp = imp_per = 0.0
    if fuel_imported and mixture_ratio:
        imp = burned / (1 + mixture_ratio)
        # The cargo is delivered at the same mixture ratio; its oxygen is lunar.
        lunar_ox = delivered * mixture_ratio / (1 + mixture_ratio)
        imp_per = imp / lunar_ox if lunar_ox > 0 else math.inf
    return ShuttleResult(name, isp_s, dv_up, dv_down, delivered, burned,
                         delivered / prop_t, imp, imp_per)


def shuttle_cases() -> list[ShuttleResult]:
    from ..mission import Vehicle, vehicle_performance

    perf = vehicle_performance(Vehicle())
    up_n, down_n = orbits.surface_to_nrho(), orbits.nrho_to_surface()
    up_l, down_l = orbits.leg("surface->EML1"), orbits.leg("EML1->surface")
    dry, prop = SPEC["tanker_dry_t"].value, SPEC["tanker_prop_t"].value
    h2 = hydrolox_isp()
    return [
        shuttle("Methalox Starship-class tanker to NRHO", perf.sl_vac_isp, dry, prop, up_n, down_n, 3.6, True),
        shuttle("Methalox Starship-class tanker to EML1", perf.sl_vac_isp, dry, prop, up_l, down_l, 3.6, True),
        shuttle("Hydrolox tanker to NRHO (all lunar)", h2, 60.0, 600.0, up_n, down_n),
        shuttle("Hydrolox tanker to EML1 (all lunar)", h2, 60.0, 600.0, up_l, down_l),
    ]
