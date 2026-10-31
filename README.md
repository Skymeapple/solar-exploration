# Solar exploration: engine design and verification

Design and digital verification of a Raptor-class methane/oxygen rocket engine,
leading to a vehicle and mission study for Mars and, later, the wider solar system.

The work follows a four-step plan:

1. **Design and verification procedure** (done): design flow, pass/fail gates G0 to G7,
   and a fidelity ladder. See the project's procedure document.
2. **Engine model** (this package): combustion chemistry, nozzle performance and the
   full-flow staged combustion power balance, checked against public Raptor 2 figures.
3. **AI design iteration**: an optimizer that proposes designs, runs them through the gates
   and logs every result.
4. **Vehicle and Mars mission check**: size a two-stage vehicle and check delta-v and transfers.

## Quick start

RocketCEA compiles NASA CEA, so it needs a Fortran compiler (`gfortran`).

```bash
pip install -e ".[dev]"
python -m raptor_sim   # gate report for the reference design
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

Gates G1, G2, G3 and G7 pass. G0 and G4 to G6 need models from later steps.

## What the model does

| Module | Content |
| --- | --- |
| `thermo.py` | Equilibrium chemistry from NASA CEA (RocketCEA), plus an independent Cantera check for gate G1 |
| `engine.py` | Throat sizing from required thrust, delivered Isp with c* and thrust-coefficient efficiencies, sea-level separation check |
| `cycle.py` | Full-flow power balance: fuel-rich and oxygen-rich preburners, each turbine driving its own pump |
| `gates.py` | Gates G1, G2, G3 and G7 with the pass criteria from the procedure |
| `benchmarks.py` | Public Raptor 2 figures with their sources and confidence |

## Known limits

- **Efficiencies are calibrated.** c* efficiency 0.975 and thrust-coefficient efficiency 0.970 are typical
  values, chosen so ideal CEA numbers land on Raptor's published Isp. They are not predicted.
- **Thrust and chamber pressure are inputs**, so gate G7 really tests specific impulse.
- **Cycle inputs are assumptions.** SpaceX has not published preburner temperatures, component efficiencies
  or pressure drops. Every such value sits in `CycleAssumptions`.
- **Shafts are balanced separately.** The fuel pump also feeds the oxygen-rich preburner, which runs at a
  higher pressure in this model; a boost stage or a different split is needed and will be handled in G5.
- Propellant flow comes out 8% above the one quoted figure, which is itself of uncertain version.

## Sources

- [SpaceX Raptor, Wikipedia](https://en.wikipedia.org/wiki/SpaceX_Raptor)
- [Raptor 1 vs Raptor 2, Everyday Astronaut](https://everydayastronaut.com/spacex-raptor-engine-comparison/)
