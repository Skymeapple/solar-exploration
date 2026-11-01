"""Hourly power balance through the lunar night: solar towers, fission and storage.

Two kinds of load:

* critical load (habitats, life support, comms, cryocoolers): must be met every hour;
* flexible load (ISRU processing): runs only when surplus power exists, up to its rating.

Storage is sized with the sequent-peak method: the largest cumulative deficit
over the series, divided by discharge efficiency and usable depth. A system
"closes" when the critical load has no unmet hour over two years of the
synthetic illumination series from :mod:`.site`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .provenance import Value

FSP_NETS = "NASA FSP 40 kWe concept, NETS 2022, NTRS 20220007008"

SPEC: dict[str, Value] = {
    "solar_flux": Value(1361.0, "W/m^2", "cited", "solar constant"),
    "cell_eff": Value(0.30, "-", "estimated", "space multi-junction cells at end of life"),
    "packing": Value(0.85, "-", "estimated", "array packing and wiring losses"),
    "solar_w_per_kg": Value(30.0, "W/kg", "estimated", "vertical tracking tower incl. 10-20 m mast, gimbal, PMAD"),
    "fsp_kwe": Value(40.0, "kWe", "cited", FSP_NETS),
    "fsp_mass_kg": Value(10_046.0, "kg", "cited", FSP_NETS + " (mass summary; 6 t goal not met)"),
    "fsp_life_yr": Value(10.0, "yr", "cited", FSP_NETS),
    "mw_reactor_w_per_kg": Value(15.0, "W/kg", "estimated", "megawatt-class reactor, specific power improves with size"),
    "liion_wh_per_kg": Value(150.0, "Wh/kg", "estimated", "space-rated Li-ion pack level"),
    "liion_dod": Value(0.80, "-", "estimated", "usable depth of discharge"),
    "liion_eff": Value(0.95, "-", "estimated", "one-way charge or discharge efficiency"),
    "rfc_wh_per_kg": Value(600.0, "Wh/kg", "estimated", "regenerative fuel cell, tanks and reactants, multi-day"),
    "rfc_kg_per_kw": Value(15.0, "kg/kW", "estimated", "electrolyser plus fuel cell stack"),
    "rfc_eff": Value(0.71, "-", "estimated", "one-way, round trip about 0.5"),
}


@dataclass(frozen=True)
class PowerSystem:
    name: str
    solar_kw: float  # array output at full Sun
    fission_kwe: float
    storage: str  # "liion", "rfc" or "none"
    storage_kwh: float = 0.0  # usable energy
    storage_kw: float = 0.0  # power rating of the storage


def solar_area_m2(kw: float) -> float:
    return kw * 1e3 / (SPEC["solar_flux"].value * SPEC["cell_eff"].value * SPEC["packing"].value)


def system_mass_t(p: PowerSystem) -> dict[str, float]:
    solar = p.solar_kw * 1e3 / SPEC["solar_w_per_kg"].value / 1e3
    if p.fission_kwe <= 0:
        fission = 0.0
    elif p.fission_kwe <= 200:
        units = int(np.ceil(p.fission_kwe / SPEC["fsp_kwe"].value))
        fission = units * SPEC["fsp_mass_kg"].value / 1e3
    else:
        fission = p.fission_kwe * 1e3 / SPEC["mw_reactor_w_per_kg"].value / 1e3
    if p.storage == "liion":
        store = p.storage_kwh / SPEC["liion_dod"].value / SPEC["liion_wh_per_kg"].value
    elif p.storage == "rfc":
        store = p.storage_kwh / SPEC["rfc_wh_per_kg"].value + p.storage_kw * SPEC["rfc_kg_per_kw"].value / 1e3
    else:
        store = 0.0
    return {"solar_t": solar, "fission_t": fission, "storage_t": store, "total_t": solar + fission + store}


def _eff(storage: str) -> float:
    return {"liion": SPEC["liion_eff"].value, "rfc": SPEC["rfc_eff"].value}.get(storage, 1.0)


def required_storage_kwh(gen_kw: np.ndarray, load_kw: float, storage: str, dt_h: float = 1.0) -> float:
    """Usable storage that meets a constant load every hour (sequent peak). inf if impossible."""
    eta = _eff(storage)
    net = gen_kw - load_kw
    # Energy in or out of storage, referred to the storage side.
    flow = np.where(net >= 0, net * eta, net / eta) * dt_h
    if flow.sum() < 0:
        return float("inf")
    # Sequent peak over two passes of the series, so the end wraps to the start.
    flow2 = np.concatenate([flow, flow])
    need, deficit = 0.0, 0.0
    for f in flow2:
        deficit = max(0.0, deficit - f)
        need = max(need, deficit)
    return need


@dataclass(frozen=True)
class SimResult:
    unmet_kwh: float
    flexible_kwh: float
    flexible_capacity_factor: float
    min_soc: float


def simulate(
    p: PowerSystem,
    sun: np.ndarray,
    critical_kw: float,
    flexible_kw: float = 0.0,
    dt_h: float = 1.0,
) -> SimResult:
    """Hourly dispatch: critical first, then recharge storage, then flexible load."""
    eta = _eff(p.storage)
    cap = p.storage_kwh
    soc = cap
    unmet = flex = 0.0
    min_soc = 1.0
    rate = p.storage_kw if p.storage_kw > 0 else float("inf")
    for s in sun:
        gen = p.solar_kw * s + p.fission_kwe
        net = gen - critical_kw
        if net < 0:
            draw = min(-net, rate, soc * eta / dt_h)
            soc -= draw * dt_h / eta
            unmet += (-net - draw) * dt_h
        else:
            charge = min(net, rate, (cap - soc) / (eta * dt_h)) if cap > 0 else 0.0
            soc += charge * eta * dt_h
            flex += min(net - charge, flexible_kw) * dt_h
        if cap > 0:
            min_soc = min(min_soc, soc / cap)
    hours = len(sun) * dt_h
    cf = flex / (flexible_kw * hours) if flexible_kw > 0 else 0.0
    return SimResult(unmet, flex, cf, min_soc)


def size_architectures(sun: np.ndarray, critical_kw: float) -> list[tuple[PowerSystem, dict[str, float]]]:
    """Lowest-mass design of each architecture that carries the critical load through every night.

    Solar options search the array size; storage follows from the sequent-peak sizing.
    """
    lit = float(sun.mean())
    out: list[tuple[PowerSystem, dict[str, float]]] = []

    for storage in ("liion", "rfc"):
        best = None
        for mult in np.linspace(1.02, 3.0, 60):
            solar_kw = mult * critical_kw / lit
            kwh = required_storage_kwh(solar_kw * sun, critical_kw, storage)
            if not np.isfinite(kwh):
                continue
            p = PowerSystem(f"solar + {storage}", solar_kw, 0.0, storage, kwh, critical_kw)
            m = system_mass_t(p)
            if best is None or m["total_t"] < best[1]["total_t"]:
                best = (p, m)
        assert best is not None
        out.append(best)

    # Fission sized for the whole critical load with one spare unit (single fault tolerance).
    units = int(np.ceil(critical_kw / SPEC["fsp_kwe"].value)) + 1
    p = PowerSystem("fission (n+1)", 0.0, units * SPEC["fsp_kwe"].value, "none")
    out.append((p, system_mass_t(p)))

    # Fission with no spare unit: lowest mass, but one reactor fault drops the base.
    units = int(np.ceil(critical_kw / SPEC["fsp_kwe"].value))
    p = PowerSystem("fission (no spare)", 0.0, units * SPEC["fsp_kwe"].value, "none")
    out.append((p, system_mass_t(p)))
    return sorted(out, key=lambda t: t[1]["total_t"])


def isru_power_trade(sun: np.ndarray, critical_kw: float, isru_kw: float) -> list[dict[str, float | str]]:
    """Two ways to run a propellant plant: fission baseload, or solar with ISRU idling in the dark.

    Both carry the critical load with the lowest-mass architecture from size_architectures.
    The result gives mass of the power system and the plant's capacity factor, so the
    plant can be oversized by 1 / capacity factor to hit an annual target.
    """
    base_sys, base_m = size_architectures(sun, critical_kw)[0]
    rows: list[dict[str, float | str]] = []

    # Fission covers ISRU continuously (megawatt-class reactor).
    p = PowerSystem("ISRU on fission", 0.0, isru_kw, "none")
    m = system_mass_t(p)["total_t"]
    rows.append({"option": p.name, "power_mass_t": m + base_m["total_t"], "capacity_factor": 1.0,
                 "mass_per_effective_kw_kg": (m + base_m["total_t"]) * 1e3 / isru_kw})

    # Solar towers sized for the ISRU rating; ISRU stops when the Sun is down.
    for oversize in (1.0, 1.1, 1.25):
        solar_kw = oversize * isru_kw
        p = PowerSystem("ISRU on solar", solar_kw, 0.0, "none")
        r = simulate(PowerSystem("x", solar_kw, 0, "none"), sun, 0.0, isru_kw)
        m = system_mass_t(p)["total_t"] + base_m["total_t"]
        rows.append({"option": f"ISRU on solar ({oversize:.2f}x array)", "power_mass_t": m,
                     "capacity_factor": r.flexible_capacity_factor,
                     "mass_per_effective_kw_kg": m * 1e3 / (isru_kw * r.flexible_capacity_factor)})
    return rows
