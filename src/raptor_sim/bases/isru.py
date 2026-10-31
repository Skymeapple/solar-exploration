"""In-situ propellant production (ISRU) for a methane/oxygen vehicle.

For each site the model lists the production chains the local resources allow,
works out the energy and the mass of raw feedstock per tonne of propellant,
and picks the chain that makes the largest share of the propellant locally
(ties go to the lower energy). Chains:

``sabatier``      CO2 + 4 H2 -> CH4 + 2 H2O, water electrolysis. Net CO2 + 2 H2O -> CH4 + 2 O2.
                  Carbon from the air (Mars, Venus) or from ice or rock.
``native_ch4``    Titan: methane is pumped from the lakes, oxygen from electrolysed ice.
``imported_h2``   Carbon from the air but no water: bring hydrogen (5.4% of propellant mass),
                  run Sabatier and make the remaining oxygen by CO2 electrolysis.
``o2_water``      Oxygen only, from electrolysed ice; methane is imported (Moon, Europa).
``o2_regolith``   Oxygen only, from molten regolith electrolysis.

Energies are electrical-equivalent kWh per tonne of propellant. Values are
estimates unless stated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .sites import Site

M_C, M_H2, M_H2O, M_CH4, M_O2, M_CO2 = 12.011, 2.016, 18.015, 16.043, 31.998, 44.009


@dataclass(frozen=True)
class ISRUAssumptions:
    mixture_ratio: float = 3.6  # O/F of the reference engine (raptor_sim.engine.EngineDesign)
    e_electrolysis_kwh_per_kg_h2: float = 55.0  # estimate: PEM/alkaline stack + balance of plant
    e_co2_air_kwh_per_kg: float = 0.6  # estimate: freeze/compress CO2 from thin air (Mars)
    e_co2_electrolysis_kwh_per_kg_o2: float = 8.0  # estimate: solid-oxide, scaled-up MOXIE
    e_mre_kwh_per_kg_o2: float = 13.0  # estimate: molten regolith electrolysis 10-15 kWh/kg
    e_pump_native_ch4_kwh_per_kg: float = 0.02  # estimate: lake pumping and filtering
    e_liquefy_kwh_per_kg: float = 0.4  # estimate: cryocoolers at ~250 K environment
    cp_regolith_kj: float = 0.8  # kJ/(kg K)
    cp_ice_kj: float = 2.0
    l_fusion_kj: float = 334.0
    l_sublimation_kj: float = 2_830.0
    carbon_release_temp_k: float = 900.0  # estimate: pyrolysis of organics and carbonates
    heat_recovery: float = 0.5  # estimate: fraction of heating energy not recovered
    overhead: float = 1.2  # estimate: pumps, controls, purification
    feed_limit_t_per_t: float = 30.0  # estimate: most mined feedstock per tonne propellant
    plant_t_per_t_day: float = 6.0  # estimate: plant mass per (t/day) output, without power


@dataclass(frozen=True)
class Chain:
    name: str
    local_fraction: float  # share of propellant mass made on site
    energy_kwh_per_t: float  # per tonne of total propellant loaded
    feed_t_per_t: float  # raw feedstock mined per tonne of propellant
    imported: str = ""  # what is still brought in
    surplus_o2_t_per_t: float = 0.0
    practical: bool = True


@dataclass(frozen=True)
class ISRUPlan:
    site: str
    best: Chain
    options: list[Chain] = field(default_factory=list)
    passive_cryo: bool = False  # site cold enough to keep LOX/CH4 with radiators alone

    def production_t_per_day(self, power_kwe: float) -> float:
        """Propellant loaded per day (local share plus matching imports)."""
        if self.best.energy_kwh_per_t <= 0:
            return float("inf")
        return power_kwe * 24.0 / self.best.energy_kwh_per_t

    def days_to_fill(self, propellant_t: float, power_kwe: float) -> float:
        return propellant_t / self.production_t_per_day(power_kwe)


def _water_energy_kwh_per_kg(site: Site, a: ISRUAssumptions) -> float:
    """Heat to free 1 kg of water from feedstock at the site's mean temperature."""
    f = max(site.resources.water_frac, 1e-9)
    t = site.t_mean_k
    if f >= 0.5:  # mostly ice: warm and melt it
        kj = a.cp_ice_kj * max(273 - t, 0) / 1 + a.l_fusion_kj
        kj += (1 / f - 1) * a.cp_regolith_kj * max(273 - t, 0)
    else:  # icy regolith: warm the soil and sublime the ice
        kj = a.l_sublimation_kj + (1 / f) * a.cp_regolith_kj * max(273 - t, 0)
    return kj / 3600 / a.heat_recovery


def _carbon_energy_kwh_per_kg_c(site: Site, a: ISRUAssumptions) -> tuple[float, float]:
    """(energy per kg C, feedstock per kg C) for the site's carbon source."""
    r = site.resources
    if r.carbon_source == "atmosphere":
        return a.e_co2_air_kwh_per_kg * M_CO2 / M_C, 0.0
    if r.carbon_source in ("ice", "regolith") and r.carbon_frac > 0:
        feed = 1 / r.carbon_frac
        dt = (a.carbon_release_temp_k if r.carbon_source == "regolith" else 250.0) - site.t_mean_k
        return feed * a.cp_regolith_kj * max(dt, 0) / 3600 / a.heat_recovery, feed
    return float("inf"), float("inf")


def _liquefaction(site: Site, a: ISRUAssumptions) -> float:
    """Cryocooling energy per kg, falling to a small value at cold outer-system sites."""
    scale = min(max((site.t_mean_k - 80.0) / (250.0 - 80.0), 0.1), 1.2)
    return a.e_liquefy_kwh_per_kg * scale


def isru_plan(site: Site, a: ISRUAssumptions = ISRUAssumptions()) -> ISRUPlan:
    mr = a.mixture_ratio
    f_ch4 = 1 / (1 + mr)
    f_o2 = mr / (1 + mr)
    r = site.resources
    e_liq = _liquefaction(site, a)
    e_w = _water_energy_kwh_per_kg(site, a)
    w_feed = 1 / max(r.water_frac, 1e-9)
    opts: list[Chain] = []

    # Per tonne of propellant (kg below are per 1,000 kg propellant)
    ch4 = 1000 * f_ch4
    o2_need = 1000 * f_o2
    n_ch4 = ch4 / M_CH4  # kmol

    # --- Sabatier with local carbon and water
    e_c, c_feed_per_kg = _carbon_energy_kwh_per_kg_c(site, a)
    if e_c < float("inf") and r.water_frac > 0:
        h2_gross = 4 * n_ch4 * M_H2  # kg electrolysed (half comes back as Sabatier water)
        water_net = 2 * n_ch4 * M_H2O
        o2_made = 2 * n_ch4 * M_O2
        extra_o2 = max(o2_need - o2_made, 0.0)
        extra_water = extra_o2 * M_H2O / (0.5 * M_O2)
        e = (h2_gross + extra_water * M_H2 / M_H2O) * a.e_electrolysis_kwh_per_kg_h2
        e += (water_net + extra_water) * e_w + n_ch4 * M_C * e_c + 1000 * e_liq
        feed_w = (water_net + extra_water) * w_feed / 1000
        feed_c = n_ch4 * M_C * c_feed_per_kg / 1000
        same_rock = r.carbon_source == "regolith"
        feed = max(feed_w, feed_c) if same_rock else feed_w + feed_c
        opts.append(Chain("sabatier", 1.0, e * a.overhead, feed,
                          surplus_o2_t_per_t=max(o2_made - o2_need, 0) / 1000,
                          practical=feed <= a.feed_limit_t_per_t))

    # --- Titan: native methane plus oxygen from ice
    if r.carbon_source == "native_ch4":
        water = o2_need * M_H2O / (0.5 * M_O2)
        e = ch4 * a.e_pump_native_ch4_kwh_per_kg + water * (M_H2 / M_H2O) * a.e_electrolysis_kwh_per_kg_h2
        e += water * e_w + o2_need * e_liq
        feed = water * w_feed / 1000
        opts.append(Chain("native_ch4", 1.0, e * a.overhead, feed, practical=feed <= a.feed_limit_t_per_t))

    # --- Carbon from the air, hydrogen imported
    if r.carbon_source == "atmosphere":
        h_in = 2 * n_ch4 * M_H2  # net H in the methane
        o2_sab = n_ch4 * M_O2  # CO2 + 2 H2 -> CH4 + O2 (water recycled)
        h2_gross = 4 * n_ch4 * M_H2
        o2_rest = max(o2_need - o2_sab, 0.0)
        e = (h2_gross - h_in) * a.e_electrolysis_kwh_per_kg_h2 + o2_rest * a.e_co2_electrolysis_kwh_per_kg_o2
        e += n_ch4 * M_CO2 * a.e_co2_air_kwh_per_kg * (1 + o2_rest / max(o2_sab, 1)) + 1000 * e_liq
        opts.append(Chain("imported_h2", 1 - h_in / 1000, e * a.overhead, 0.0, imported=f"H2 {h_in / 1000:.3f} t/t"))

    # --- Oxygen only
    if r.water_frac > 0:
        water = o2_need * M_H2O / (0.5 * M_O2)
        e = water * (M_H2 / M_H2O) * a.e_electrolysis_kwh_per_kg_h2 + water * e_w + o2_need * e_liq
        feed = water * w_feed / 1000
        opts.append(Chain("o2_water", f_o2, e * a.overhead, feed, imported=f"CH4 {f_ch4:.3f} t/t",
                          practical=feed <= a.feed_limit_t_per_t))
    if r.oxide_regolith:
        e = o2_need * (a.e_mre_kwh_per_kg_o2 + e_liq)
        opts.append(Chain("o2_regolith", f_o2, e * a.overhead, o2_need / 0.4 / 1000,
                          imported=f"CH4 {f_ch4:.3f} t/t"))

    practical = [c for c in opts if c.practical] or [Chain("none", 0.0, 0.0, 0.0, imported="all")]
    best = sorted(practical, key=lambda c: (-round(c.local_fraction, 3), c.energy_kwh_per_t))[0]
    return ISRUPlan(site.key, best, opts, passive_cryo=site.t_mean_k < 100.0)


def sabatier_mass_balance(ch4_kg: float = 1000.0) -> dict[str, float]:
    """Element balance (kg) for CO2 + 2 H2O -> CH4 + 2 O2; every value should be ~0."""
    n = ch4_kg / M_CH4
    co2, h2o = n * M_CO2, 2 * n * M_H2O
    o2 = 2 * n * M_O2
    c_in, c_out = co2 * M_C / M_CO2, ch4_kg * M_C / M_CH4
    h_in, h_out = h2o * 2 * 1.008 / M_H2O, ch4_kg * 4 * 1.008 / M_CH4
    o_in = co2 * 2 * 15.999 / M_CO2 + h2o * 15.999 / M_H2O
    return {"C": c_in - c_out, "H": h_in - h_out, "O": o_in - o2, "mass": co2 + h2o - ch4_kg - o2}
