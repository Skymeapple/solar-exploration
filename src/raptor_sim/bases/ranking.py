"""Multi-criteria ranking of transit-base sites, with a weight-sensitivity check.

Each criterion is scored 0..1 (higher is better) from the models, not by hand:

propellant   share of a full methane/oxygen load made on site (isru)
access       cargo per ship from LEO along the best hub route (network)
trip         exp(-trip time from LEO in years / 3)
energy       power-system mass to make 10,000 t/yr of propellant, best site over this site
radiation    1 / (1 + dose / 200 mSv/yr)
launch       mean one-hop cargo from this site to every other node, over the cap:
             a hub must be able to send full ships onward
gateway      number of other sites whose best route passes through this one
settlement   resource breadth (water, carbon, nitrogen, metals) and gravity for health
The weights are a judgement; the Monte Carlo run shows how stable the order is.

Two rankings come out. The transit-hub ranking multiplies the weighted sum by a
gate, min(1, launch / LAUNCH_GATE), because a hub that cannot send ships onward
is not a transit base however pleasant it is (Venus aerostats, Mercury). The
settlement ranking uses SETTLEMENT_WEIGHTS and no gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .isru import isru_plan
from .network import Network, Route
from .power import best_power
from .sites import SITES

WEIGHTS = {
    "propellant": 0.15,
    "access": 0.10,
    "trip": 0.10,
    "energy": 0.10,
    "radiation": 0.15,
    "launch": 0.10,
    "gateway": 0.10,
    "settlement": 0.20,
}

SETTLEMENT_WEIGHTS = {
    "propellant": 0.15,
    "access": 0.10,
    "trip": 0.15,
    "energy": 0.10,
    "radiation": 0.20,
    "settlement": 0.30,
}
LAUNCH_GATE = 0.3  # estimate: mean onward cargo fraction a hub needs to count fully


@dataclass(frozen=True)
class SiteScore:
    site: str
    scores: dict[str, float]
    total: float
    rank: int
    mean_rank_mc: float
    p_top3_mc: float


def criteria(net: Network, routes: dict[str, Route]) -> dict[str, dict[str, float]]:
    def power_t(s):
        kwe = 10_000 * isru_plan(s).best.energy_kwh_per_t / 8766.0
        return best_power(s, kwe).mass_t

    p_t = {k: power_t(s) for k, s in SITES.items()}
    best_p = min(p_t.values())
    through = {k: 0 for k in SITES}
    for r in routes.values():
        if r.cargo_t > 0:
            for hop in r.path[1:-1]:
                through[hop] += 1
    max_through = max(max(through.values()), 1)
    cap = net.ship.max_payload_t
    out = {}
    for k, s in SITES.items():
        res = s.resources
        onward = [max(min(net.payload[(k, d)], cap), 0.0) / cap for d in net.nodes if d != k]
        breadth = (
            min(res.water_frac / 0.1, 1.0)
            + (1.0 if res.carbon_source in ("atmosphere", "native_ch4") else min(res.carbon_frac / 0.02, 1.0))
            + (1.0 if res.nitrogen else 0.0)
            + res.metals
        ) / 4
        gravity = min(s.surface_g / 3.7, 1.0)  # Mars-level gravity or more scores 1 (estimate)
        out[k] = {
            "propellant": isru_plan(s).best.local_fraction,
            "access": max(min(routes[k].cargo_t / net.ship.max_payload_t, 1.0), 0.0),
            "trip": math.exp(-routes[k].tof_days / 365.25 / 3) if routes[k].cargo_t > 0 else 0.0,
            "energy": best_p / p_t[k],
            "radiation": 1 / (1 + s.radiation_msv_yr / 200),
            "launch": sum(onward) / len(onward),
            "gateway": through[k] / max_through,
            "settlement": 0.7 * breadth + 0.3 * gravity,
        }
    return out


def rank_sites(
    net: Network,
    routes: dict[str, Route],
    n_mc: int = 4000,
    seed: int = 1,
    weights: dict[str, float] | None = None,
    gate: bool = True,
) -> list[SiteScore]:
    """Transit-hub ranking by default; pass SETTLEMENT_WEIGHTS and gate=False for settlements."""
    weights = weights or WEIGHTS
    crit = criteria(net, routes)
    keys = list(crit)
    names = list(weights)
    mat = np.array([[crit[k][c] for c in names] for k in keys])
    g = np.array([min(1.0, crit[k]["launch"] / LAUNCH_GATE) if gate else 1.0 for k in keys])
    w0 = np.array([weights[c] for c in names])
    totals = (mat @ w0) * g
    order = np.argsort(-totals)
    rank = {keys[i]: r + 1 for r, i in enumerate(order)}

    rng = np.random.default_rng(seed)
    ws = rng.dirichlet(w0 * 20, size=n_mc)  # weights jittered around the base case
    ranks = np.argsort(np.argsort(-((ws @ mat.T) * g), axis=1), axis=1) + 1
    mean_rank = ranks.mean(axis=0)
    p_top3 = (ranks <= 3).mean(axis=0)
    out = [
        SiteScore(k, crit[k], float(totals[i]), rank[k], float(mean_rank[i]), float(p_top3[i]))
        for i, k in enumerate(keys)
    ]
    return sorted(out, key=lambda s: s.rank)
