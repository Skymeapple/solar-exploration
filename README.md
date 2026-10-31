# Solar exploration: engine design and verification

Design and digital verification of a Raptor-class methane/oxygen rocket engine,
leading to a vehicle and mission study for Mars and, later, the wider solar system.

The work follows a four-step plan:

1. **Design and verification procedure** (done): design flow, pass/fail gates G0 to G7,
   and a fidelity ladder. See the project's procedure document.
2. **Engine model** (done): combustion chemistry, nozzle performance and the
   full-flow staged combustion power balance, checked against public Raptor 2 figures.
3. **AI design iteration** (done): a Bayesian optimizer (Optuna TPE) proposes designs, runs them
   through the gates and logs every result to `results/optimizer_log.csv`.
4. **Vehicle and Mars mission check** (done): a Starship-class two-stage vehicle built around the
   engine, Earth to Mars transfer, LEO refilling and the Mars return with propellant made on Mars.

## Quick start

RocketCEA compiles NASA CEA, so it needs a Fortran compiler (`gfortran`). CoolProp gives real-fluid
methane properties for the cooling model; ezdxf writes the DXF drawings.

```bash
pip install -e ".[dev]"
python -m raptor_sim          # gate report for the reference design
python scripts/run_study.py   # optimizer + Mars study, writes results/
python scripts/run_component_design.py   # components, drawings, BOM, verification -> results/components/
pytest
```

## Reference design result

| Quantity | Model | Raptor 2 public figure |
| --- | --- | --- |
| Chamber pressure | 300 bar (input) | 300 bar |
| Sea-level thrust | 2,256 kN (input) | 2,256 kN (230 tf) |
| Sea-level Isp | 326.7 s | 327 s |
| Vacuum Isp | 348.0 s | 347 s |
| Nozzle exit diameter | 1.36 m | about 1.3 m |
| Propellant flow | 704 kg/s | 650 kg/s (low confidence) |

Gates G0, G1, G2, G3 and G7 pass. G4 to G6 (cooling, turbopump detail, engine mass) need
higher-fidelity models.

## Optimizer and Mars results

Full tables are in [`results/summary.md`](results/summary.md).

- Over 300 designs, the best one raises chamber pressure to 314 bar, lowers the mixture ratio to 3.46
  and widens the nozzle to area ratio 37. It gains about 1 s of Isp at sea level and 2 s in vacuum.
  The small gain says Raptor 2 already sits close to the best point under these limits.
- What limits the design: the oxygen turbine runs out of power above about 315 bar at these
  efficiencies, and the 1.40 m nozzle packaging limit caps the area ratio.
- Mars: landing 100 t needs about 550 t of propellant refilled in LEO, which is 4 tanker launches
  in the model. The return trip with 20 t needs about 640 t of propellant made on Mars.
- The model puts 155 t into LEO, while SpaceX states about 100 t for Block 3. A ship dry mass near
  150 t instead of 100 t closes that gap and raises the tanker count to 7.

## What the model does

| Module | Content |
| --- | --- |
| `thermo.py` | Equilibrium chemistry from NASA CEA (RocketCEA), plus an independent Cantera check for gate G1 |
| `engine.py` | Throat sizing from required thrust, delivered Isp with c* and thrust-coefficient efficiencies, sea-level separation check |
| `cycle.py` | Full-flow power balance: fuel-rich and oxygen-rich preburners, each turbine driving its own pump |
| `gates.py` | Gates G1, G2, G3 and G7 with the pass criteria from the procedure |
| `benchmarks.py` | Public Raptor and Starship figures with their sources and confidence |
| `optimize.py` | Design search with Optuna, gate constraints, and a per-trial log |
| `mission.py` | Two-stage vehicle sizing, patched-conic Earth to Mars transfer, refilling and return |

## Known limits

- **Efficiencies are calibrated.** c* efficiency 0.975 and thrust-coefficient efficiency 0.970 are typical
  values, chosen so ideal CEA numbers land on Raptor's published Isp. They are not predicted.
- **Thrust and chamber pressure are inputs**, so gate G7 really tests specific impulse.
- **Cycle inputs are assumptions.** SpaceX has not published preburner temperatures, component efficiencies
  or pressure drops. Every such value sits in `CycleAssumptions`.
- **Shafts are balanced separately.** The fuel pump also feeds the oxygen-rich preburner, which runs at a
  higher pressure in this model; a boost stage or a different split is needed and will be handled in G5.
- The vacuum engine variant gives 362.7 s against the quoted 380 s (4.6% low), because the
  efficiencies were calibrated on the sea-level engine.
- Mission delta-v uses minimum-energy transfers with a 10% margin; landing (700 m/s) and Mars ascent
  (4,100 m/s) are assumptions.
- Propellant flow comes out 8% above the one quoted figure, which is itself of uncertain version.

## Sources

- [SpaceX Raptor, Wikipedia](https://en.wikipedia.org/wiki/SpaceX_Raptor)
- [SpaceX Starship, Wikipedia](https://en.wikipedia.org/wiki/SpaceX_Starship)
- [Raptor 1 vs Raptor 2, Everyday Astronaut](https://everydayastronaut.com/spacex-raptor-engine-comparison/)

## Component design (step 5)

`raptor_sim.components` designs every major part of the reference engine, checks each one on its
own, then checks how they fit together, and iterates until the fixable problems are gone.
Results are in [`results/components/`](results/components/):
[`verification.md`](results/components/verification.md) (all checks, pressure ladder, iteration log,
sensitivity, vehicle impact), [`bom.md`](results/components/bom.md) / `bom.csv`, `design_data.json`,
and `drawings/` (SVG and DXF).

| Module | Content |
| --- | --- |
| `components/materials.py` | Material table (GRCop-42, IN718, oxygen-compatible superalloy, 316L, Ti-6Al-4V, Monel K-500, A-286) with strength at temperature and safety factors |
| `components/chamber.py` | Chamber from L*, conical convergent with throat arcs, Rao 80% bell nozzle |
| `components/cooling.py` | Regenerative cooling march: Bartz gas side, Gnielinski with CoolProp methane, fin ribs, film cooling, hot-wall, rib and closeout stresses |
| `components/injector.py` | Gas-gas coaxial main injector: orifice sizing, ring layout, face plate and dome |
| `components/turbopump.py` | Pumps from suction specific speed and tip speed, Gulich efficiency; turbines from u/c0, blade stress; shafts; mass estimate |
| `components/preburner.py` | Fuel-rich and oxygen-rich preburners from residence time, wall sizing |
| `components/feed.py` | Lines, hot-gas ducts and valves: sizes, walls, pressure drops, masses |
| `components/assembly.py` | Builds the whole engine, rolls up mass, makes the BOM |
| `components/verification.py` | Component checks, pressure ladder (subsystem), whole-engine checks, mapped to gates G4 to G6 |
| `components/iterate.py` | Find failures, apply fix rules (including an Optuna search of the cooling-channel layout), rebuild, repeat |
| `components/drawings.py` | Thrust chamber section, channel sections, injector face, turbopump layouts, flow schematic |

The converged design point is saved in `src/raptor_sim/components/design_point.json`, so the
report rebuilds in seconds; `--iterate` re-runs the whole iteration from the first guess.

What the iteration changed and what is still open is summarised at the top of
`results/components/verification.md`. Values derived from the models are marked *sized*;
scaling rules and allowances are marked *estimate*.

## Business case

`python scripts/run_business_case.py` costs the engine from `results/components/bom.csv`, builds vehicle,
per-flight and per-mission costs, and runs a 2027-2041 plan with bear/base/bull scenarios, a sensitivity
tornado and a financing plan. Assumptions, with cited/model/estimate tags and source links, are in
`src/raptor_sim/econ/inputs.py` and `plan.py`; results go to `results/business/`. Standard library only.

## Master roadmap (integration of all studies)

`src/raptor_sim/roadmap` joins the engine, vehicle, Mars, business and mission studies into one
program model (standard library only, runs in seconds):

| Module | Content |
| --- | --- |
| `catalog.py` | 42 steps from engine development to a crewed Jupiter-system mission: duration and cost ranges, TRL, launch windows, the capabilities each step needs and proves |
| `schedule.py` | Network forward pass with Mars, Mars-return and Jupiter launch windows; driving path; float |
| `montecarlo.py` | Correlated schedule and cost risk, development failures by TRL gap, mission failures that re-fly at the next window |
| `options.py` | Acceleration options for the first crewed Mars landing, compared by Monte Carlo |
| `logistics.py` | Launches, tankers, propellant, pads, fleet and engine production by year, Mars ISRU power |
| `report.py` | Tables, capability transfer matrix, Gantt chart (`results/roadmap/`) |

```bash
python scripts/run_roadmap.py            # writes results/roadmap/summary.md, schedule.csv, gantt.svg, roadmap.json
```

When another study delivers numbers, put them in `src/raptor_sim/roadmap/overrides.json` (step id to
field values) and re-run; the catalog estimate stays as the fallback.
