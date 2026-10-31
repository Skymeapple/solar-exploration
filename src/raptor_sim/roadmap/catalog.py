"""Program catalog: every development step, mission and infrastructure build in
the campaign, with duration, cost, readiness, dependencies and the
capabilities each one proves.

Units: months from the program start (1 November 2026) and $M in 2026 dollars.
Durations and costs are (low, most likely, high) triangular ranges.

Dependencies come from two places. `needs` lists capabilities; the step that
`provides` a capability becomes a predecessor, so the capability transfer
matrix and the schedule network are the same data. `after` lists explicit
predecessors where order matters but no capability changes hands.

Basis for every row is "estimate" unless the note says otherwise. Model values
from other parts of this repository and cited anchors are named in `basis`.
The step `owner` names the project thread whose detailed study should replace
the estimate; load that thread's numbers with an overrides file
(see `load_overrides`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

Tri = tuple[float, float, float]

PHASES = {
    "P0": "Engine and vehicle development",
    "P1": "Orbital operations: reuse, refuelling, crew",
    "P2": "Moon: landings, base, spaceport",
    "P3": "Mars robotic: cargo, ISRU, sample return",
    "P4": "Mars crewed: first crews and return",
    "P5": "Settlement and transit network",
    "P6": "Outer solar system",
}


@dataclass(frozen=True)
class Step:
    id: str
    name: str
    phase: str
    kind: str                     # tech | build | mission | ops
    dur: Tri                      # months
    cost: Tri                     # $M
    needs: tuple = ()             # capabilities required
    provides: tuple = ()          # capabilities proven by this step
    after: tuple = ()             # explicit predecessors (step ids)
    benefits: tuple = ()          # capabilities reused without waiting for them (transfer only)
    trl: tuple | None = None      # (now, at completion), NASA TRL scale
    window: str | None = None     # "mars", "mars_return", "jupiter": start only in a window
    p_success: float = 1.0        # mission success; a failure re-flies (next window if gated)
    retry_dur: Tri = (3, 6, 9)    # months to re-fly a failed non-window mission
    owner: str = ""               # project thread that owns the detailed study
    basis: str = "estimate"
    note: str = ""


STEPS: list[Step] = [
    # ---------------- P0 Engine and vehicle --------------------------------
    Step("ENG-DEV", "Raptor-class engine: component tests to full-duration hot fire", "P0", "tech",
         (24, 30, 48), (800, 1100, 1700), provides=("engine",), trl=(3, 6),
         owner="Design engine components with drawings and BOMs",
         basis="model: PR #2 design at 295 bar passes all 53 checks and gates G0-G7; 1,935 kg, "
               "sea-level T/W 119, Isp 324 s SL; duration estimate",
         note="Paper design only, so TRL 3. Cooling margin is thin: +20% heat flux or rougher channels "
              "breaks the jacket, so hot-fire rework is likely (TRL-gap failure model covers it)."),
    Step("ENG-QUAL", "Engine qualification and production line", "P0", "build",
         (9, 12, 18), (400, 600, 900), needs=("engine",), provides=("engine_production",), trl=(6, 8)),
    Step("VAC-ENG", "Vacuum engine variant", "P0", "tech",
         (12, 18, 30), (200, 300, 500), needs=("engine",), provides=("vac_engine",), trl=(4, 7),
         basis="model: PR #1 gives 363 s against 380 s quoted, so the nozzle model needs work first"),
    Step("BOOSTER-DEV", "Booster structure, avionics, grid fins", "P0", "tech",
         (24, 30, 42), (600, 900, 1400), provides=("booster",), trl=(4, 7),
         basis="model: PR #1 vehicle (3,650 t propellant, 33 engines, public Block 3 figures)"),
    Step("SHIP-DEV", "Ship structure and heat shield", "P0", "tech",
         (30, 36, 48), (700, 1000, 1600), provides=("ship",), trl=(4, 7),
         basis="model: PR #1 vehicle; dry mass 100 t public vs 150 t that matches the 100 t payload"),
    Step("LAUNCH-SITE", "Factory, launch pad and tank farm", "P0", "build",
         (24, 30, 42), (800, 1100, 1600), provides=("launch_site",),
         basis="model: PR #3 business case development budget"),

    # ---------------- P1 Orbital operations --------------------------------
    Step("ORBITAL-1", "Integrated stack and first orbital flight", "P1", "mission",
         (6, 9, 18), (200, 300, 500),
         needs=("engine_production", "vac_engine", "booster", "ship", "launch_site"),
         provides=("orbit",), p_success=0.6, retry_dur=(2, 4, 6),
         basis="model: PR #3 assumes first orbital flight in 2031"),
    Step("REUSE", "Booster catch and ship recovery, reflight", "P1", "tech",
         (9, 15, 24), (300, 500, 800), needs=("orbit",), provides=("reuse",), trl=(5, 8)),
    Step("CADENCE", "Second pad and weekly launch cadence", "P1", "build",
         (6, 12, 18), (300, 500, 800), needs=("reuse",), provides=("cadence",),
         note="SpaceX targets about one Starship flight per week in H1 2027 (cited, starship_refuel_2027)."),
    Step("PROP-XFER", "Ship-to-ship propellant transfer in orbit", "P1", "tech",
         (6, 12, 24), (200, 350, 600), needs=("orbit",), provides=("prop_transfer",), trl=(4, 7),
         note="SpaceX aims for its first attempt in early 2027 (cited); our own hardware starts at TRL 4."),
    Step("DEPOT", "LEO depot with long-duration cryogenic storage", "P1", "tech",
         (12, 18, 30), (400, 600, 1000), needs=("prop_transfer",), provides=("depot",), trl=(3, 7),
         note="Holds tanker loads through a Mars window surge; boil-off target 0.1%/day (estimate)."),
    Step("EDL-TEST", "High-energy Earth entry test (Mars-class heating)", "P1", "tech",
         (3, 6, 9), (100, 200, 300), needs=("reuse", "prop_transfer"), provides=("hypersonic_edl",), trl=(4, 6)),
    Step("CREW-SHIP", "Crew-rated ship: cabin, abort, life support integration", "P1", "tech",
         (24, 36, 48), (800, 1200, 2000), needs=("ship",), provides=("crew_vehicle",), trl=(4, 7),
         owner="Research and simulate crewed missions and return"),
    Step("CREW-LEO", "First crewed orbital flight", "P1", "mission",
         (2, 3, 6), (150, 250, 400), needs=("crew_vehicle", "reuse"), provides=("crew_leo",), p_success=0.9),
    Step("ECLSS-LD", "Closed-loop life support for 900-day missions", "P1", "tech",
         (36, 48, 72), (300, 500, 900), provides=("eclss_long",), trl=(6, 8),
         basis="cited: ISS recovers 98% of water (iss_water); model: PR #5 ISS-class loop is 19.7 t for "
               "6 crew and 950 days and beats open loop beyond 215 days; 900-day reliability is the gap"),
    Step("LONG-DUR", "Year-long crewed test of the Mars cabin in Earth or lunar orbit", "P1", "mission",
         (12, 14, 18), (300, 500, 800), needs=("crew_leo", "eclss_long"), provides=("crew_long_duration",),
         p_success=0.9, owner="Research and simulate crewed missions and return"),
    Step("RAD-HEALTH", "Radiation shielding and crew health for 900-day Mars missions", "P1", "tech",
         (48, 60, 84), (400, 700, 1200), provides=("rad_protection",), trl=(3, 6),
         owner="Research and simulate crewed missions and return",
         basis="model: PR #5 conjunction-class chemical mission gives 737-1,228 mSv against a 600 mSv limit",
         note="PR #5: 40 g/cm2 polyethylene allows 193 days of transit with a 500-day stay; a storm shelter of "
              "1.6-6.8 g/cm2 extra covers solar events. Needs shorter transits, heavier walls or a waiver."),

    # ---------------- P2 Moon ----------------------------------------------
    Step("LUNAR-LANDER", "Lunar ship variant: landing engines, legs, no flaps", "P2", "tech",
         (18, 24, 36), (400, 600, 900), needs=("ship", "engine_production", "landing_thrusters"),
         provides=("lunar_lander",), trl=(5, 7),
         owner="Research and simulate crewed lunar missions",
         basis="cited scale: SpaceX HLS awards total about $4.2B (hls_total)"),
    Step("LAND-THRUST", "Lunar landing thrusters for the final descent", "P2", "tech",
         (18, 24, 36), (150, 250, 400), provides=("landing_thrusters",), trl=(4, 7),
         owner="Research and simulate crewed lunar missions",
         basis="model: PR #10 Raptor at minimum throttle still gives 2.2 times the lander's lunar weight"),
    Step("TPS-LUNAR", "Heat shield qualified for crewed lunar-return entry", "P2", "tech",
         (12, 18, 30), (150, 300, 500), needs=("reuse",), provides=("lunar_return_tps",), trl=(4, 7),
         owner="Research and simulate crewed lunar missions",
         basis="model: PR #10 lunar return at 10,988 m/s heats the shield about 5 times more than a LEO return"),
    Step("LUNAR-CARGO-1", "First lunar cargo landing", "P2", "mission",
         (1, 2, 3), (200, 300, 500), needs=("lunar_lander", "prop_transfer", "cadence"),
         provides=("lunar_landing",), p_success=0.8,
         basis="model: PR #3 lunar cargo, 100 t landed, about $96M at maturity; first flight costs more"),
    Step("LUNAR-CREW-1", "First crewed lunar landing", "P2", "mission",
         (1, 1, 2), (400, 600, 1000), needs=("crew_leo", "lunar_landing", "lunar_return_tps"), provides=("deep_space_crew",),
         p_success=0.95, owner="Research and simulate crewed lunar missions",
         basis="model: PR #10 lander refuelled in LEO needs 11-16 tanker launches; a single ship cannot fly "
               "LEO-surface-Earth (2,044 t needed vs 1,600 t tank); PR #10 baseline is Orion to NRHO",
         note="NASA's first crewed landing is now Artemis IV, planned 2028 and likely later (cited, artemis_iii)."),
    Step("SURF-POWER", "Surface fission power, 40 kWe class", "P2", "tech",
         (36, 48, 72), (300, 600, 1200), provides=("surface_power",), trl=(5, 7),
         basis="cited: NASA plans a reactor of at least 20 kW on the Moon by 2030 (lunar_fission); our share estimated"),
    Step("LUNAR-ISRU", "Lunar ice mining and oxygen production pilot", "P2", "tech",
         (24, 36, 54), (400, 700, 1200), needs=("surface_power", "lunar_landing"), provides=("lunar_isru",), trl=(4, 7),
         owner="Design a lunar transit base and spaceport"),
    Step("LUNAR-BASE-1", "Lunar base phases 1-2: outpost for 4-8 crew, oxygen plant", "P2", "build",
         (36, 48, 72), (2000, 3500, 6000), needs=("deep_space_crew", "surface_power", "lunar_landing"),
         provides=("surface_habitat",), owner="Design a lunar transit base and spaceport",
         basis="model: PR #9 Shackleton-de Gerlache ridge; phases 1-2 land 240 t in 15 Earth launches; cost estimate"),
    Step("LUNAR-SPACEPORT", "Lunar base phase 3: transit spaceport, 24 crew, 4 MW ISRU", "P2", "build",
         (48, 72, 96), (1500, 3000, 5000), needs=("lunar_isru", "depot", "surface_habitat"),
         provides=("lunar_propellant",), owner="Design a lunar transit base and spaceport",
         basis="model: PR #9 phase 3 lands 611 t in 38 Earth launches, fission plus solar; cost estimate",
         note="PR #9: lunar ice has about 6% of the carbon needed for methane, so the base sells oxygen, "
              "not full methalox. Pads need about 28 m radius plus blast berms."),
    Step("HYDROLOX-ENG", "Hydrogen-oxygen engine for all-lunar tankers", "P2", "tech",
         (36, 48, 72), (600, 1000, 1600), provides=("hydrolox_engine",), trl=(3, 7),
         owner="Design a lunar transit base and spaceport",
         basis="model: PR #9 (all-lunar tankers) and PR #10 (ice-fuelled lander) both need it; RL10-class "
               "engines exist in industry, ours does not"),
    Step("LUNAR-TANKER", "Lunar oxygen to LEO by hydrogen-oxygen tankers", "P2", "build",
         (18, 24, 36), (1000, 1800, 3000), needs=("hydrolox_engine", "lunar_propellant", "depot"),
         provides=("lunar_oxygen_leo",), owner="Design a lunar transit base and spaceport",
         basis="model: PR #9 cuts Earth launches per Mars cargo mission from 4.3 to 1.7"),
    Step("LUNAR-SETTLE", "Lunar base phase 4: settlement of about 100 residents", "P5", "build",
         (96, 132, 180), (6000, 12000, 24000), needs=("lunar_propellant",), provides=("lunar_settlement",),
         owner="Design a lunar transit base and spaceport",
         basis="model: PR #9 phase 4 lands 1,193 t in 74 Earth launches, 1.5 MW critical power; cost estimate"),

    # ---------------- P3 Mars robotic --------------------------------------
    Step("MARS-ISRU-DEV", "Mars propellant plant: water mining, Sabatier, electrolysis", "P3", "tech",
         (36, 48, 72), (500, 800, 1400), provides=("isru_plant",), trl=(4, 6),
         basis="model: PR #1 needs 642 t of propellant made on Mars per returning ship",
         owner="Plan human settlement on other planets"),
    Step("MARS-POWER", "Mars surface power, about 1 MW: solar arrays plus 360 kW fission", "P3", "tech",
         (18, 24, 36), (400, 700, 1200), needs=("surface_power",), provides=("mars_power",), trl=(5, 7),
         basis="model: PR #12 needs about 1 MW to make return propellant in 383 days: 40,000 m2 of solar "
               "plus 360 kW fission so a dust storm cannot stop it"),
    Step("SHIP-MARS-MOD", "Mars ship changes: 4th sea-level engine, ablative shield, steep thin-air entry", "P3", "tech",
         (12, 18, 30), (250, 450, 800), needs=("ship",), provides=("mars_ship",), trl=(5, 7),
         owner="Plan and simulate Mars launch campaign",
         basis="model: PR #12 fixes not yet in the main design: engine-out landing needs a 4th sea-level engine, "
               "steeper entry when the air is thin, ablative heat shield (+6 t) for 12.3 km/s Earth return"),
    Step("MARS-CARGO-1", "First Mars cargo landings (2 ships)", "P3", "mission",
         (10, 10.5, 11), (500, 800, 1200), needs=("prop_transfer", "cadence", "hypersonic_edl", "depot", "mars_ship"),
         provides=("mars_landing",), benefits=("lunar_landing",), window="mars", p_success=0.8,
         owner="Plan and simulate Mars launch campaign",
         basis="model: PR #12 one ship plus 9 tankers at 103 t to LEO; 2028-12-02 to 2029-10-18 (321 days); "
               "landing burns 115 t; 13/13 goals pass, about 98% success in simulation (0.8 held for a first attempt)"),
    Step("MARS-CARGO-2", "Power and ISRU pilot plant to Mars", "P3", "mission",
         (6, 7, 9), (500, 800, 1200), needs=("mars_landing", "isru_plant", "mars_power"),
         provides=("isru_delivered",), window="mars", p_success=0.85,
         owner="Plan and simulate Mars launch campaign"),
    Step("ISRU-RUN", "ISRU pilot makes its first full ship load", "P3", "ops",
         (12, 18, 30), (100, 200, 400), needs=("isru_delivered",), provides=("isru_proven",), trl=(6, 8)),
    Step("MSR-MAV", "Sample return lander, 335 kg ascent rocket, Earth entry capsule", "P3", "tech",
         (18, 22, 30), (500, 900, 1600), provides=("sample_ascent",), trl=(4, 6),
         owner="Research and simulate planetary sample return",
         basis="model: PR #4 passes gates SR-1 to SR-8 in simulation; cost estimate, NASA MSR was $8-11B (cited, msr_cost)",
         note="Flies on a commercial launcher in the 2028 window, before our own vehicle exists."),
    Step("SR-CONTAIN", "Sample receiving facility and break-the-chain containment", "P3", "tech",
         (36, 48, 60), (300, 500, 800), provides=("sample_containment",), trl=(3, 6),
         owner="Research and simulate planetary sample return",
         basis="model: PR #4 release probability 6.6e-7 vs 1e-6 limit, all estimated until tested; top open risk"),
    Step("MSR-LAND", "Sample return lander to Mars (launch Nov 2028 in PR #4)", "P3", "mission",
         (9.5, 10, 10.5), (200, 300, 500), needs=("sample_ascent",), window="mars", p_success=0.85,
         owner="Research and simulate planetary sample return",
         basis="model: PR #4 Lambert arc 2028-11-24 to 2029-09-22"),
    Step("MSR-COLLECT", "Sample collection and ascent to Mars orbit", "P3", "ops",
         (3, 6, 12), (50, 100, 200), after=("MSR-LAND",), owner="Research and simulate planetary sample return"),
    Step("MSR-RETURN", "Samples cruise to Earth and land (Aug 2031 in PR #4)", "P3", "mission",
         (10.5, 10.8, 11.2), (100, 200, 300), after=("MSR-COLLECT",), needs=("sample_containment",),
         provides=("earth_return",), window="mars_return", p_success=0.9,
         owner="Research and simulate planetary sample return",
         basis="model: PR #4 return 2030-10-07 to 2031-08-29, entry 12.0 km/s",
         note="PR #4: one entry capsule covers Moon, Mars, asteroid and comet returns (405-635 W/cm2); "
              "Europa and Enceladus need a stronger heat shield."),

    # ---------------- P4 Mars crewed ---------------------------------------
    Step("MARS-CREW-1", "First crewed Mars landing (2 crew ships, 2 cargo ships)", "P4", "mission",
         (6, 7, 8), (1500, 2500, 4000),
         needs=("crew_long_duration", "rad_protection", "isru_proven", "deep_space_crew", "mars_landing"),
         provides=("crew_mars",), window="mars", p_success=0.95,
         owner="Research and simulate crewed missions and return",
         note="A failure here means a scrubbed window (crew safety), not a loss; the crew flies next window. "
              "PR #5: no abort-to-Earth coverage with a 2 km/s budget, so ISRU and cargo must be proven first."),
    Step("MARS-STAY-1", "First surface expedition (conjunction class)", "P4", "ops",
         (12, 14, 16), (200, 400, 700), after=("MARS-CREW-1",)),
    Step("MARS-CREW-RETURN", "First crew returns on Mars-made propellant", "P4", "mission",
         (6, 7, 9), (100, 200, 400), after=("MARS-STAY-1",), needs=("mars_ship",),
         benefits=("earth_return", "lunar_return_tps"),
         provides=("crew_round_trip",), window="mars_return", p_success=0.95,
         owner="Research and simulate crewed missions and return"),

    # ---------------- P5 Settlement and transit network --------------------
    Step("MARS-BASE-1", "Mars outpost: permanent crew, greenhouse, scaled ISRU", "P5", "build",
         (36, 48, 72), (3000, 5000, 9000), needs=("crew_mars", "surface_habitat"), provides=("mars_outpost",),
         benefits=("lunar_isru",),
         owner="Plan human settlement on other planets"),
    Step("TRANSIT-NET", "Transit hubs at Mars (Arcadia) and Phobos, full refuelling", "P5", "build",
         (36, 48, 72), (3000, 5000, 9000), needs=("depot", "isru_proven"), benefits=("lunar_propellant", "lunar_oxygen_leo"),
         provides=("transit_network",), owner="Design transit bases across the solar system",
         basis="model: PR #6 ranks Mars Arcadia, Phobos and Ceres as the top hubs; Mars outpost 1.8 MWe, "
               "299 t imported, 12 Earth launches; cost estimate",
         note="PR #6: the lunar south pole ranks 5th and its refill misses a yearly cycle, so the Moon is a "
              "feeder, not the trunk route. Phobos siting depends on JAXA MMX samples (return 2031, cited in PR #4); "
              "fission power at every base, and 9 capabilities are reused at 10 or more of the 12 sites."),
    Step("CERES-HUB", "Ceres refuelling hub, gateway to the outer planets", "P6", "build",
         (60, 84, 120), (5000, 8000, 15000), needs=("transit_network",), provides=("outer_gateway",),
         owner="Design transit bases across the solar system",
         basis="model: PR #6 route LEO > Phobos > Ceres (833 days), 2.2 MWe outpost; cost estimate"),
    Step("DEEP-SHIELD", "Shielding and health for multi-year deep-space crews", "P6", "tech",
         (72, 96, 144), (1000, 2000, 4000), needs=("rad_protection",), provides=("deep_shielding",), trl=(2, 5),
         owner="Research and simulate crewed missions and return",
         basis="model: PR #5 every Callisto case gives 1.6-3.9 Sv against a 600 mSv limit",
         note="Feasibility gate: crewed Jupiter missions may not close on radiation even with this step."),
    Step("REGOLITH-SHIELD", "Regolith shielding 3-5 m overhead for lifelong residents", "P5", "tech",
         (24, 36, 60), (200, 400, 800), needs=("mars_outpost",), provides=("lifelong_shielding",), trl=(4, 7),
         owner="Plan human settlement on other planets",
         basis="model: PR #11 someone born on Mars needs 3-5 m of regolith to stay near 500-1,000 mSv lifetime"),
    Step("SETTLEMENT-100", "Mars settlement reaches 1,000 residents", "P5", "build",
         (96, 132, 180), (15000, 25000, 45000), needs=("mars_outpost", "crew_round_trip", "lifelong_shielding"),
         provides=("settlement",), benefits=("transit_network", "lunar_oxygen_leo", "lunar_settlement"),
         owner="Plan human settlement on other planets",
         basis="model: PR #11 baseline reaches 1,000 people about 15 years after the first landing; 22 kW per "
               "person, fission backbone; cost estimate"),
    Step("MARS-SELF", "Mars settlement makes 98% of its needs, Earth supply optional", "P5", "ops",
         (300, 456, 700), (5000, 10000, 20000), needs=("settlement",), provides=("self_sufficiency",),
         owner="Plan human settlement on other planets",
         basis="model: PR #11 baseline reaches 98% local production about 53 years after first landing and "
               "1 million people at about 77; with slow industry it stalls near 18,000; cutting Earth supply "
               "before 98% collapses it. Earth-side cost only, estimate",
         note="Beyond the program horizon; shown so the dependency is explicit."),
    # ---------------- P6 Outer solar system ---------------------------------
    Step("OUTER-ROBOTIC-1", "Refuelled-ship robotic mission to the Jupiter system", "P6", "mission",
         (30, 36, 48), (800, 1200, 2000), needs=("depot", "cadence"),
         window="jupiter", p_success=0.85, owner="Design transit bases across the solar system",
         note="Direct high-energy transfer using a refilled ship in LEO; arrival counts as finish."),
    Step("NUC-PROP", "Megawatt-class nuclear electric propulsion", "P6", "tech",
         (72, 96, 144), (2500, 4000, 7000), needs=("surface_power",), provides=("nuclear_propulsion",), trl=(3, 7),
         basis="model: PR #5 a 10 MWe, 5 kg/kWe NEP ship reaches Mars in 130 days and keeps a 290-day "
               "mission under 600 mSv"),
    Step("OUTER-CREW-1", "First crewed mission to the Jupiter system (Callisto)", "P6", "mission",
         (48, 60, 84), (15000, 25000, 45000),
         needs=("nuclear_propulsion", "outer_gateway", "crew_round_trip", "deep_shielding"),
         window="jupiter", p_success=0.95, owner="Design transit bases across the solar system",
         basis="model: PR #5 Callisto by nuclear thermal is 1,430-2,024 days and a 1,900-3,600 t stack in LEO; "
               "PR #6 route via Phobos and Ceres; cost estimate"),
]

KEY_MILESTONES = [
    "MSR-RETURN", "ORBITAL-1", "REUSE", "PROP-XFER", "CREW-LEO", "LUNAR-CARGO-1", "LUNAR-CREW-1",
    "MARS-CARGO-1", "MARS-CREW-1", "MARS-CREW-RETURN", "LUNAR-SPACEPORT",
    "LUNAR-TANKER", "MARS-BASE-1", "TRANSIT-NET", "OUTER-ROBOTIC-1", "CERES-HUB", "LUNAR-SETTLE", "SETTLEMENT-100", "OUTER-CREW-1", "MARS-SELF",
]


@dataclass
class Program:
    steps: dict[str, Step]
    preds: dict[str, list[str]] = field(default_factory=dict)
    provider: dict[str, str] = field(default_factory=dict)

    @property
    def order(self) -> list[str]:
        """Topological order (raises on a cycle)."""
        seen, out, temp = set(), [], set()

        def visit(n: str) -> None:
            if n in seen:
                return
            if n in temp:
                raise ValueError(f"dependency cycle at {n}")
            temp.add(n)
            for p in self.preds[n]:
                visit(p)
            temp.discard(n)
            seen.add(n)
            out.append(n)

        for n in self.steps:
            visit(n)
        return out


def build_program(steps: list[Step] | None = None) -> Program:
    steps = steps or STEPS
    by_id = {s.id: s for s in steps}
    if len(by_id) != len(steps):
        raise ValueError("duplicate step id")
    provider: dict[str, str] = {}
    for s in steps:
        for c in s.provides:
            if c in provider:
                raise ValueError(f"capability {c} provided by {provider[c]} and {s.id}")
            provider[c] = s.id
    preds: dict[str, list[str]] = {}
    for s in steps:
        p = list(s.after)
        for c in s.needs:
            if c not in provider:
                raise ValueError(f"{s.id} needs {c}, which no step provides")
            p.append(provider[c])
        for c in s.benefits:
            if c not in provider:
                raise ValueError(f"{s.id} benefits from {c}, which no step provides")
        for q in p:
            if q not in by_id:
                raise ValueError(f"{s.id} depends on unknown step {q}")
        preds[s.id] = sorted(set(p))
    prog = Program(by_id, preds, provider)
    prog.order  # validate
    return prog


def load_overrides(path: str | Path, steps: list[Step] | None = None) -> list[Step]:
    """Replace fields of named steps from a JSON file written when a thread delivers.

    Format: {"STEP-ID": {"dur": [lo, mode, hi], "cost": [...], "basis": "model: PR #n", ...}, ...}
    """
    data = json.loads(Path(path).read_text())
    out = []
    for s in steps or STEPS:
        o = data.get(s.id)
        if o:
            o = {k: tuple(v) if isinstance(v, list) else v for k, v in o.items() if not k.startswith("_")}
            s = replace(s, **o)
        out.append(s)
    unknown = set(data) - {s.id for s in out} - {k for k in data if k.startswith("_")}
    if unknown:
        raise ValueError(f"overrides name unknown steps: {sorted(unknown)}")
    return out
