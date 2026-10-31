"""Regenerative cooling of the thrust chamber and nozzle (gate G4).

One-dimensional marching model. Methane from the fuel pump enters at the nozzle
exit, flows toward the injector through milled channels in the liner, and
leaves to the fuel-rich preburner.

Hot gas side: Bartz correlation with the sigma property correction
(Bartz, Jet Propulsion 27, 1957; Huzel & Huang eq. 4-13). Radiation is left out;
for methane/oxygen it adds a few percent in the chamber.

Coolant side: Gnielinski correlation with real-fluid methane properties from
CoolProp, a wall-to-bulk temperature correction for heated supercritical flow,
the Norris rough-wall enhancement, and fin efficiency for the ribs.

Wall: one-dimensional conduction through the hot wall.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import brentq

from .. import thermo
from ..engine import EnginePerformance
from .chamber import Contour
from .materials import MATERIALS, allowable

_CP = None
MIN_CLOSEOUT = 1.0e-3  # m, manufacturing minimum


def _coolprop():
    global _CP
    if _CP is None:
        import CoolProp.CoolProp as CP

        _CP = CP
    return _CP


def methane_props(p: float, h: float) -> dict[str, float]:
    """Real-fluid methane properties from pressure (Pa) and specific enthalpy (J/kg)."""
    CP = _coolprop()
    out = {}
    for key, name in (("T", "T"), ("rho", "D"), ("mu", "V"), ("k", "L"), ("cp", "C")):
        out[key] = float(CP.PropsSI(name, "P", p, "H", h, "Methane"))
    return out


def methane_h(p: float, t: float) -> float:
    return float(_coolprop().PropsSI("H", "P", p, "T", t, "Methane"))


@dataclass(frozen=True)
class CoolingInputs:
    """Channel layout. Every value is a design choice; the iteration loop changes them."""

    n_channels_throat: int = 180
    hot_wall_thickness: float = 0.8e-3  # m, copper liner
    copper_nozzle_wall_thickness: float = 0.8e-3  # m, copper liner downstream of area ratio 2
    nozzle_wall_thickness: float = 0.8e-3  # m, IN718 channel-wall nozzle
    rib_width: float = 1.0e-3  # m, chamber and throat
    rib_fraction_nozzle: float = 0.5  # rib share of the channel pitch downstream of the throat
    depth_chamber: float = 4.0e-3  # m, at the chamber cylinder
    depth_throat: float = 2.5e-3  # m
    depth_exit: float = 6.0e-3  # m, at the nozzle exit
    max_channel_width: float = 4.0e-3  # m, chamber and throat; channels split in two when wider
    max_channel_width_nozzle: float = 4.0e-3  # m, downstream of area ratio 2
    roughness: float = 10e-6  # m, as-built additive manufactured channel
    copper_to_area_ratio: float = 4.0  # GRCop-42 liner up to this area ratio, IN718 channel wall beyond
    film_cooling_factor: float = 1.0  # multiplies the gas-side coefficient in the chamber (1 = no film)
    film_fraction_of_fuel: float = 0.0  # fuel used as film coolant, for the Isp penalty only
    closeout_material: str = "IN718"


@dataclass(frozen=True)
class Station:
    x: float
    r: float
    area_ratio: float
    mach: float
    material: str
    n_channels: int
    width: float
    depth: float
    rib: float
    q: float  # W/m^2 gas-side heat flux
    t_wall_gas: float  # K
    t_wall_coolant: float  # K
    t_coolant: float  # K
    p_coolant: float  # Pa
    p_gas: float  # Pa
    velocity: float  # m/s
    hg: float
    hc: float
    hot_wall_stress: float  # Pa, pressure bending of the hot wall across a channel
    hot_wall_allowable: float  # Pa
    rib_stress: float  # Pa, rib tension from coolant pressure pushing liner and closeout apart
    rib_allowable: float  # Pa
    closeout_thickness: float  # m
    wall_thickness: float = 0.0  # m, hot wall


@dataclass(frozen=True)
class CoolingResult:
    inputs: CoolingInputs
    stations: list[Station]
    coolant_flow: float  # kg/s
    coolant_inlet_pressure: float
    coolant_inlet_temperature: float
    heat_load: float  # W
    closeout_thickness: float  # m
    total_pressure_drop: float  # Pa, friction drop from inlet to outlet
    notes: list[str] = field(default_factory=list)

    @property
    def coolant_outlet_temperature(self) -> float:
        return self.stations[0].t_coolant

    @property
    def pressure_drop(self) -> float:
        return self.total_pressure_drop

    @property
    def max_wall_station(self) -> Station:
        return max(self.stations, key=lambda s: s.t_wall_gas / MATERIALS[s.material].max_service_temperature)

    def summary(self) -> dict[str, float]:
        s = self.max_wall_station
        peak_q = max(self.stations, key=lambda st: st.q)
        return {
            "coolant_flow_kg_s": self.coolant_flow,
            "heat_load_MW": self.heat_load / 1e6,
            "peak_heat_flux_MW_m2": peak_q.q / 1e6,
            "peak_heat_flux_x_mm": peak_q.x * 1e3,
            "worst_wall_temperature_K": s.t_wall_gas,
            "worst_wall_material": s.material,
            "worst_wall_x_mm": s.x * 1e3,
            "coolant_inlet_K": self.coolant_inlet_temperature,
            "coolant_outlet_K": self.coolant_outlet_temperature,
            "pressure_drop_bar": self.pressure_drop / 1e5,
            "max_coolant_velocity_m_s": max(st.velocity for st in self.stations),
            "max_closeout_thickness_mm": self.closeout_thickness * 1e3,
        }


def _mach_from_area(area_ratio: float, gamma: float, supersonic: bool) -> float:
    if area_ratio <= 1.0 + 1e-9:
        return 1.0
    g = gamma

    def f(m: float) -> float:
        return (1 / m) * ((2 / (g + 1)) * (1 + (g - 1) / 2 * m * m)) ** ((g + 1) / (2 * (g - 1))) - area_ratio

    return brentq(f, 1.0 + 1e-9, 50.0) if supersonic else brentq(f, 1e-6, 1.0 - 1e-9)


def _friction(re: float, rel_rough: float) -> tuple[float, float]:
    """Darcy friction factor (rough, smooth) from the Haaland form of Colebrook."""
    rough = (-1.8 * math.log10((rel_rough / 3.7) ** 1.11 + 6.9 / re)) ** -2
    smooth = (0.790 * math.log(re) - 1.64) ** -2
    return rough, smooth


def _depth(ci: CoolingInputs, contour: Contour, x: float, r: float) -> float:
    if x <= 0:
        frac = (r - contour.rt) / max(contour.rc - contour.rt, 1e-9)
        return ci.depth_throat + frac * (ci.depth_chamber - ci.depth_throat)
    frac = (r - contour.rt) / max(contour.re - contour.rt, 1e-9)
    return ci.depth_throat + frac * (ci.depth_exit - ci.depth_throat)


def solve_cooling(
    perf: EnginePerformance,
    contour: Contour,
    ci: CoolingInputs,
    *,
    coolant_flow: float,
    coolant_inlet_pressure: float,
    coolant_inlet_temperature: float,
    n_stations: int = 120,
    hg_scale: float = 1.0,
) -> CoolingResult:
    d = perf.design
    gas = thermo.chamber(d.pc, d.mixture_ratio)
    cp_g, mu_mp, _k, pr_g = thermo._cea().get_Chamber_Transport(Pc=d.pc, MR=d.mixture_ratio, frozen=1)
    cp_g, mu_g, pr_g = float(cp_g), float(mu_mp) * 1e-4, float(pr_g)
    gamma = gas.gamma
    t0 = gas.temperature
    dt_ = 2 * contour.rt
    r_curv = 0.5 * (contour.inputs.upstream_throat_arc + contour.inputs.downstream_throat_arc) * contour.rt
    bartz_const = (
        0.026 / dt_**0.2 * (mu_g**0.2 * cp_g / pr_g**0.6) * (d.pc / perf.cstar) ** 0.8 * (dt_ / r_curv) ** 0.1
    )
    recovery = pr_g ** (1 / 3)

    x, r = contour.points(n_stations)
    # Coolant runs from the nozzle exit (last point) to the injector face (first point).
    idx = list(range(len(x) - 1, -1, -1))
    p_c = coolant_inlet_pressure
    h_c = methane_h(p_c, coolant_inlet_temperature)
    dp_total = 0.0
    # If friction would use up the supply pressure, properties are evaluated at a floor
    # pressure so the march can finish; the full (failing) drop is still reported.
    p_floor = 0.3 * d.pc
    copper = MATERIALS["GRCop-42"]
    nozzle_mat = MATERIALS["IN718"]
    jacket = MATERIALS[ci.closeout_material]
    stations: list[Station] = []
    heat = 0.0
    prev = None
    for i in idx:
        xi, ri = float(x[i]), float(r[i])
        ar = (ri / contour.rt) ** 2
        mach = _mach_from_area(ar, gamma, supersonic=xi > 0)
        stag = 1 + (gamma - 1) / 2 * mach**2
        t_aw = t0 * (1 + recovery * (gamma - 1) / 2 * mach**2) / stag
        p_gas = d.pc * stag ** (-gamma / (gamma - 1))
        mat = copper if (xi <= 0 or ar <= ci.copper_to_area_ratio) else nozzle_mat
        k_w = mat.conductivity
        throat_zone = xi <= 0 or ar <= 2.0
        if mat is not copper:
            t_w = ci.nozzle_wall_thickness
        else:
            t_w = ci.hot_wall_thickness if throat_zone else ci.copper_nozzle_wall_thickness
        w_max = ci.max_channel_width if throat_zone else ci.max_channel_width_nozzle
        # Film coolant from the injector's outer ring protects the chamber and throat fully and
        # mixes out downstream of the throat with an e-folding length of two throat diameters
        # (estimate; film effectiveness data for this regime are not public).
        film = 1.0 - (1.0 - ci.film_cooling_factor) * (math.exp(-xi / (2 * dt_)) if xi > 0 else 1.0)

        # Channel geometry at this station
        circ = 2 * math.pi * (ri + t_w)
        n = ci.n_channels_throat
        # Channels are added (by splitting ribs) wherever the pitch would make them wider
        # than allowed; treated as a smooth increase in count rather than discrete splits.
        if xi <= 0:
            # Upstream of the throat the gas pressure is high, so ribs can be narrow.
            rib = ci.rib_width
            n = max(n, math.ceil(circ / (w_max + rib)))
            width = max(circ / n - rib, 0.1e-3)
        else:
            # Downstream of the throat the gas pressure falls away while the coolant pressure
            # stays high, so the rib is a fixed share of the pitch: channels
            # can be kept narrow (for the hot wall) while ribs stay wide (for rib tension).
            f = ci.rib_fraction_nozzle
            n = max(n, math.ceil(circ * (1 - f) / w_max))
            rib = f * circ / n
            width = (1 - f) * circ / n
        depth = _depth(ci, contour, xi, ri)
        dh = 2 * width * depth / (width + depth)
        a_ch = width * depth
        m_ch = coolant_flow / n

        props = methane_props(p_c, h_c)
        t_b = props["T"]
        vel = m_ch / (props["rho"] * a_ch)
        re = props["rho"] * vel * dh / props["mu"]
        pr_c = props["mu"] * props["cp"] / props["k"]
        f_r, f_s = _friction(re, ci.roughness / dh)
        nu_s = (f_s / 8) * (re - 1000) * pr_c / (1 + 12.7 * math.sqrt(f_s / 8) * (pr_c ** (2 / 3) - 1))
        n_norris = 0.68 * pr_c**0.215
        enh = min(f_r / f_s, 4.0) ** n_norris

        def hc_at(t_wc: float) -> float:
            hc0 = nu_s * enh * props["k"] / dh * (t_b / max(t_wc, t_b)) ** 0.55
            m = math.sqrt(2 * hc0 / (k_w * rib))
            eta_fin = math.tanh(m * depth) / (m * depth)
            return hc0 * (width + 2 * depth * eta_fin) / (width + rib)

        def hg_at(t_wg: float) -> float:
            sigma = 1.0 / ((0.5 * t_wg / t0 * stag + 0.5) ** 0.68 * stag**0.12)
            return hg_scale * film * bartz_const * (1 / ar) ** 0.9 * sigma

        def residual(t_wg: float) -> float:
            q = hg_at(t_wg) * (t_aw - t_wg)
            t_wc = t_wg - q * t_w / k_w
            return q - hc_at(t_wc) * (t_wc - t_b)

        t_wg = brentq(residual, t_b + 1e-3, t_aw - 1e-3, xtol=1e-3)
        hg = hg_at(t_wg)
        q = hg * (t_aw - t_wg)
        t_wc = t_wg - q * t_w / k_w

        # Pressure bending of the hot wall spanning one channel (fixed-fixed beam).
        dp_wall = max(p_c - p_gas, 0.0)
        stress = dp_wall * width**2 / (2 * t_w**2)
        # Ribs tie liner to closeout: the net pressure on the liner over one pitch is carried by one rib.
        rib_stress = dp_wall * (width + rib) / rib
        rib_allow = allowable(mat, 0.5 * (t_wc + t_b))
        # Closeout: local bending over the channel and hoop load from the gas pressure
        # (the coolant pressure is reacted through the ribs, so it does not load the hoop).
        sig_j = allowable(jacket, t_b)
        t_close = max(
            math.sqrt(p_c * width**2 / (2 * sig_j)), p_gas * (ri + t_w + depth) / sig_j, MIN_CLOSEOUT
        )
        stations.append(
            Station(xi, ri, ar, mach, mat.key, n, width, depth, rib, q, t_wg, t_wc, t_b, p_c, p_gas, vel, hg,
                    hc_at(t_wc), stress, allowable(mat, t_wg), rib_stress, rib_allow, t_close, t_w)
        )

        if prev is not None:
            ds = math.hypot(xi - prev[0], ri - prev[1])
            area = 2 * math.pi * 0.5 * (ri + prev[1]) * ds
            dq = 0.5 * (q + prev[2]) * area
            heat += dq
            h_c += dq / coolant_flow
            dp_total += f_r * (ds / dh) * 0.5 * props["rho"] * vel**2
            p_c = max(coolant_inlet_pressure - dp_total, p_floor)
        prev = (xi, ri, q)

    stations.reverse()  # injector face first
    return CoolingResult(
        ci, stations, coolant_flow, coolant_inlet_pressure, coolant_inlet_temperature, heat,
        max(s.closeout_thickness for s in stations), dp_total,
    )
