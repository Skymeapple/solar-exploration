"""In-situ resource utilisation: polar ice to water, oxygen and hydrogen; regolith oxygen.

Energy chain per kilogram of water from icy regolith:

1. Heat regolith from cold-trap temperature to the 220 K sublimation temperature
   (heat capacity from the Hayne et al. 2017 polynomial), heat the ice, sublimate it.
   Divided by a heating efficiency calibrated on the Colorado School of Mines
   tent-mining sizing in Kornuta et al. 2019 (two ice fractions; the check in
   :mod:`.checks` requires both within 10%).
2. Clean the water (contaminants: H2S, NH3, SO2, CO2, ... from LCROSS).
3. Electrolyse to H2 and O2.
4. Liquefy and keep cold.

Carbon: LCROSS measured CO2 and CH4 at a few percent of the water mass. That is
far too little carbon to make methane for a methane-oxygen engine, so methane is
imported from Earth and only the oxygen is local (about 78% of the propellant mass
at mixture ratio 3.6). :func:`lunar_carbon_coverage` quantifies this.
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy.integrate import quad

from .provenance import Value

KORNUTA = "Kornuta et al. 2019, Commercial lunar propellant architecture, REACH 13, 100026"
HAYNE = "Hayne et al. 2017, JGR Planets 122, regolith heat capacity polynomial"
LCROSS = "Colaprete et al. 2010, Science 330, 463 (LCROSS, 5.6 +/- 2.9 wt% H2O)"

SPEC: dict[str, Value] = {
    "ice_lcross": Value(0.056, "-", "cited", LCROSS),
    "t_coldtrap": Value(40.0, "K", "cited", KORNUTA + ", PSR surface as low as 40 K"),
    "t_sublimation": Value(220.0, "K", "cited", KORNUTA + ", tent sublimation temperature"),
    "h_sublimation": Value(2.83e6, "J/kg", "cited", "latent heat of ice sublimation near 200 K"),
    "heating_eff": Value(0.76, "-", "computed", "calibrated so the model reproduces both Kornuta 2019 Table 1 cases"),
    "regolith_density": Value(1500.0, "kg/m^3", "cited", "bulk density of the upper 0.5 m, Lunar Sourcebook"),
    "mining_depth": Value(0.5, "m", "estimated", "depth heated per tent placement; matches 25 kg/m^2 at 4 wt%"),
    "recovery": Value(0.83, "-", "estimated", "fraction of ice recovered; Kornuta cites up to 80% in breadboards"),
    "electrolysis_hhv": Value(15.87e6, "J/kg", "cited", "HHV of water, 285.8 kJ/mol"),
    "electrolysis_eff": Value(0.70, "-", "estimated", "PEM electrolyser at 80 bar output (Kornuta), HHV basis"),
    "cleanup_kwh_per_kg": Value(0.1, "kWh/kg", "estimated", "cold-trap distillation of contaminants"),
    "liq_lox_kwh_per_kg": Value(0.6, "kWh/kg", "estimated", "large reverse-Brayton cryocooler, about 25% of Carnot"),
    "liq_lh2_kwh_per_kg": Value(12.0, "kWh/kg", "estimated", "terrestrial plants are 10-13 kWh/kg"),
    "liq_lch4_kwh_per_kg": Value(0.5, "kWh/kg", "estimated", ""),
    "c_per_water_co2": Value(0.0217 * 12 / 44, "kg/kg", "computed", KORNUTA + " Table 2: CO2 2.17% of H2O"),
    "c_per_water_ch4": Value(0.0065 * 12 / 16, "kg/kg", "computed", KORNUTA + " Table 2: CH4 0.65% of H2O"),
    "mre_kwh_per_kg_o2": Value(15.0, "kWh/kg", "estimated", "molten regolith electrolysis, literature range 10-25"),
    "plant_kg_per_kw": Value(25.0, "kg/kW", "estimated", "electrolysers, liquefiers, radiators, excluding power"),
    "miner_t_per_kt_water": Value(10.0, "t per kt/yr", "estimated", "tent-mining rovers and haulers"),
}

KORNUTA_CASES = (
    # ice mass fraction, water t/yr, sublimation power kW, area mined m^2/yr
    Value(0.04, "-", "cited", KORNUTA + " Table 1"),
    Value(0.30, "-", "cited", KORNUTA + " Table 1"),
)
KORNUTA_POWER_KW = {0.04: 580.0, 0.30: 370.0}
KORNUTA_WATER_T = 2_450.0
KORNUTA_TOTAL_MW = Value(2.8, "MW", "cited", KORNUTA + ": 2 MW electrical plus 0.8 MW thermal")

SECONDS_PER_YEAR = 365.25 * 86400


def cp_regolith(t: float) -> float:
    """Regolith specific heat, J/(kg K), Hayne et al. 2017."""
    c = (-3.6125, 2.7431, 2.3616e-3, -1.2340e-5, 8.9093e-9)
    return sum(ci * t**i for i, ci in enumerate(c))


def cp_ice(t: float) -> float:
    """Water ice specific heat, J/(kg K), roughly 7.5 T below 250 K (estimated fit)."""
    return 7.5 * t + 90.0


def sublimation_heat_per_kg_water(ice_frac: float, t0: float | None = None, eff: float | None = None) -> float:
    """Heat (J) delivered to the ground per kg of water extracted."""
    t0 = SPEC["t_coldtrap"].value if t0 is None else t0
    t1 = SPEC["t_sublimation"].value
    eff = SPEC["heating_eff"].value if eff is None else eff
    rec = SPEC["recovery"].value
    regolith_per_ice = (1 - ice_frac) / ice_frac
    h_reg = quad(cp_regolith, t0, t1)[0]
    h_ice = quad(cp_ice, t0, t1)[0] + SPEC["h_sublimation"].value
    # Heat all ice in the heated volume; only `rec` of it is captured.
    # All ice in the heated volume is sublimated; only `rec` of it reaches the cold trap.
    return (regolith_per_ice * h_reg + h_ice) / (rec * eff)


@dataclass(frozen=True)
class Plant:
    product: str
    ice_frac: float
    water_t_yr: float
    o2_t_yr: float
    h2_t_yr: float
    propellant_t_yr: float  # usable propellant delivered to storage
    imported_ch4_t_yr: float  # methane from Earth to pair with lunar oxygen
    thermal_kw: float  # sublimation heat
    electric_kw: dict[str, float]
    electric_total_kw: float
    total_kw: float  # thermal supplied electrically, worst case
    regolith_t_yr: float
    area_m2_yr: float
    plant_mass_t: float  # excluding the power system

    def summary(self) -> dict[str, float | str]:
        return {
            "product": self.product,
            "ice_wt_pct": 100 * self.ice_frac,
            "water_t_yr": self.water_t_yr,
            "o2_t_yr": self.o2_t_yr,
            "h2_t_yr": self.h2_t_yr,
            "propellant_t_yr": self.propellant_t_yr,
            "imported_ch4_t_yr": self.imported_ch4_t_yr,
            "thermal_kw": self.thermal_kw,
            "electric_kw": self.electric_total_kw,
            "total_kw": self.total_kw,
            "regolith_kt_yr": self.regolith_t_yr / 1e3,
            "area_km2_yr": self.area_m2_yr / 1e6,
            "plant_mass_t": self.plant_mass_t,
        }


def water_plant(water_t_yr: float, ice_frac: float, product: str = "hydrolox", hydrolox_mr: float = 6.0,
                methalox_mr: float = 3.6, capacity_factor: float = 1.0) -> Plant:
    """Size a plant that turns `water_t_yr` of mined water into propellant.

    product:
      "water"     stop after cleanup (life support, radiation shielding, trade good)
      "hydrolox"  LOX and LH2 at engine mixture ratio `hydrolox_mr`; spare O2 is kept
      "methalox"  LOX only, paired with imported CH4 at `methalox_mr`; H2 is kept for other uses
    capacity_factor < 1 raises the rated power so the annual output is still met.
    """
    kg_s = water_t_yr * 1e3 / SECONDS_PER_YEAR / capacity_factor
    thermal_kw = kg_s * sublimation_heat_per_kg_water(ice_frac) / 1e3
    e: dict[str, float] = {"cleanup": kg_s * SPEC["cleanup_kwh_per_kg"].value * 3600}
    o2 = h2 = prop = ch4 = 0.0
    if product != "water":
        e["electrolysis"] = kg_s * SPEC["electrolysis_hhv"].value / SPEC["electrolysis_eff"].value / 1e3
        o2_s, h2_s = kg_s * 16 / 18.015, kg_s * 2.015 / 18.015
        o2, h2 = o2_s * SECONDS_PER_YEAR * capacity_factor / 1e3, h2_s * SECONDS_PER_YEAR * capacity_factor / 1e3
        if product == "hydrolox":
            ox_used = min(o2_s, h2_s * hydrolox_mr)
            e["liquefy_lox"] = ox_used * SPEC["liq_lox_kwh_per_kg"].value * 3600
            e["liquefy_lh2"] = h2_s * SPEC["liq_lh2_kwh_per_kg"].value * 3600
            prop = (ox_used + h2_s) * SECONDS_PER_YEAR * capacity_factor / 1e3
        elif product == "methalox":
            e["liquefy_lox"] = o2_s * SPEC["liq_lox_kwh_per_kg"].value * 3600
            ch4 = o2 / methalox_mr
            prop = o2 + ch4
        else:
            raise ValueError(product)
    elec = sum(e.values())
    regolith = water_t_yr / ice_frac / SPEC["recovery"].value
    area = regolith * 1e3 / (SPEC["regolith_density"].value * SPEC["mining_depth"].value)
    mass = (elec + thermal_kw) * SPEC["plant_kg_per_kw"].value / 1e3 + water_t_yr / 1e3 * SPEC["miner_t_per_kt_water"].value
    return Plant(product, ice_frac, water_t_yr, o2, h2, prop, ch4, thermal_kw, e, elec, elec + thermal_kw,
                 regolith, area, mass)


def plant_for_production(target_t_per_yr: float, ice_wt_frac: float = 0.056, product: str = "hydrolox",
                         capacity_factor: float = 1.0) -> Plant:
    """Plant that delivers `target_t_per_yr` of lunar-made propellant (the shared ISRU entry point).

    For "methalox" the target counts only the lunar oxygen; methane comes from Earth.
    For "water" the target is water.
    """
    if product == "water":
        return water_plant(target_t_per_yr, ice_wt_frac, product, capacity_factor=capacity_factor)
    unit = water_plant(1_000.0, ice_wt_frac, product, capacity_factor=capacity_factor)
    lunar = unit.propellant_t_yr - unit.imported_ch4_t_yr
    return water_plant(1_000.0 * target_t_per_yr / lunar, ice_wt_frac, product, capacity_factor=capacity_factor)


def lunar_carbon_coverage(methalox_mr: float = 3.6) -> float:
    """Fraction of the methane needed for lunar-oxygen methalox that lunar ice carbon could supply."""
    c_per_water = SPEC["c_per_water_co2"].value + SPEC["c_per_water_ch4"].value
    o2_per_water = 16 / 18.015
    ch4_needed = o2_per_water / methalox_mr
    c_needed = ch4_needed * 12 / 16
    return c_per_water / c_needed


def regolith_oxygen_power_kw(o2_t_yr: float) -> float:
    """Molten regolith electrolysis: oxygen anywhere on the Moon, no ice needed."""
    return o2_t_yr * 1e3 * SPEC["mre_kwh_per_kg_o2"].value / (SECONDS_PER_YEAR / 3600)


def kornuta_check() -> dict[str, dict[str, float]]:
    """Model sublimation power versus Kornuta 2019 Table 1 (2,450 t water per year)."""
    out = {}
    for f, ref in KORNUTA_POWER_KW.items():
        kg_s = KORNUTA_WATER_T * 1e3 / SECONDS_PER_YEAR
        model = kg_s * sublimation_heat_per_kg_water(f) / 1e3
        out[f"{f:.0%}"] = {"model_kw": model, "kornuta_kw": ref, "error": model / ref - 1}
    p = water_plant(KORNUTA_WATER_T, 0.056, "hydrolox", hydrolox_mr=8.0)
    out["total"] = {"model_kw": p.electric_total_kw + p.thermal_kw, "kornuta_kw": KORNUTA_TOTAL_MW.value * 1e3,
                    "error": (p.electric_total_kw + p.thermal_kw) / (KORNUTA_TOTAL_MW.value * 1e3) - 1}
    return out


def heating_eff_fit() -> float:
    """Least-squares heating efficiency against the two Kornuta cases (for the record)."""
    kg_s = KORNUTA_WATER_T * 1e3 / SECONDS_PER_YEAR
    ideal = {f: kg_s * sublimation_heat_per_kg_water(f, eff=1.0) / 1e3 for f in KORNUTA_POWER_KW}
    num = sum(ideal[f] ** 2 for f in ideal)
    den = sum(ideal[f] * KORNUTA_POWER_KW[f] for f in ideal)
    return num / den


__all__ = ["Plant", "plant_for_production", "water_plant", "lunar_carbon_coverage", "kornuta_check"]
