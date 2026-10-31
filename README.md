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

RocketCEA compiles NASA CEA, so it needs a Fortran compiler (`gfortran`).

```bash
pip install -e ".[dev]"
python -m raptor_sim          # gate report for the reference design
python scripts/run_study.py   # optimizer + Mars study, writes results/
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

## Transit bases across the solar system

`raptor_sim.bases` extends the study from one Mars mission to a network of refuelling bases.
Run `python scripts/run_bases.py`; tables land in [`results/bases/`](results/bases/summary.md).

| Module | Content |
| --- | --- |
| `bases/sites.py` | 12 candidate sites (Moon pole, Mars, Phobos, Deimos, Ceres, Callisto, Ganymede, Europa, Titan, Enceladus, Venus aerostat, Mercury pole). Every input is tagged `cited`, `literature` or `estimate` with its source |
| `bases/power.py` | Solar arrays with night storage versus fission (scaled from NASA FSP, 40 kWe under 6 t) versus RTG |
| `bases/isru.py` | Propellant chains (Sabatier, Titan native methane, imported hydrogen, oxygen-only), energy and feedstock per tonne, element balance |
| `bases/network.py` | Patched-conic delta-v between all sites, ship payload per hop with full tanks, stepping-stone routes through refuelling hubs |
| `bases/logistics.py` | Outpost, base and city build-up, Earth launches with and without hubs, day-by-day depot refill simulation |
| `bases/ranking.py` | Transit-hub and settlement rankings with a Monte Carlo weight-sensitivity check |
| `bases/capabilities.py` | Site-by-capability matrix showing which technologies are reused where |
