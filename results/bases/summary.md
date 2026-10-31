# Transit bases across the solar system: study results

Ship: 100 t dry, 1600 t propellant, Isp 362.7 s (RVac) / 348.0 s (sea-level engines in vacuum), cargo cap 150 t.
Full refuelling hubs (ISRU makes the whole methane/oxygen load): leo, mars_arcadia, phobos, deimos, ceres, callisto, titan, mercury_north_pole.

## Ranking

| Site | Hub rank | P(top 3) | Rank at 150 t dry | Settlement rank |
|---|---|---|---|---|
| mars_arcadia | 1 | 1.00 | 3 | 2 |
| phobos | 2 | 0.99 | 2 | 6 |
| ceres | 3 | 0.95 | 1 | 4 |
| deimos | 4 | 0.02 | 4 | 7 |
| moon_south_pole | 5 | 0.04 | 5 | 5 |
| callisto | 6 | 0.00 | 6 | 9 |
| ganymede | 7 | 0.00 | 7 | 11 |
| europa | 8 | 0.00 | 8 | 12 |
| titan | 9 | 0.00 | 9 | 3 |
| enceladus | 10 | 0.00 | 10 | 10 |
| mercury_north_pole | 11 | 0.00 | 12 | 8 |
| venus_clouds | 12 | 0.00 | 11 | 1 |

## Routes from LEO (refuelling at hubs)

| Site | Route | Cargo t | Direct capacity t | Trip days | Cargo t at 150 t dry |
|---|---|---|---|---|---|
| moon_south_pole | leo > moon_south_pole | 150.0 | 254.7 | 5 | 150.0 |
| mars_arcadia | leo > mars_arcadia | 150.0 | 486.6 | 259 | 150.0 |
| phobos | leo > phobos | 150.0 | 242.2 | 259 | 150.0 |
| deimos | leo > deimos | 150.0 | 237.7 | 259 | 150.0 |
| ceres | leo > phobos > ceres | 150.0 | -25.0 | 833 | 150.0 |
| callisto | leo > phobos > ceres > callisto | 91.2 | -56.9 | 2286 | 41.2 |
| ganymede | leo > phobos > ceres > callisto > ganymede | 91.2 | -67.4 | 2292 | 41.2 |
| europa | leo > phobos > ceres > callisto > europa | 91.2 | -74.0 | 2291 | 41.2 |
| titan | leo > phobos > titan | 147.4 | 78.7 | 2649 | 150.0 |
| enceladus | leo > titan > enceladus | 54.6 | -76.3 | 2227 | 4.6 |
| venus_clouds | leo > venus_clouds | 150.0 | 690.7 | 146 | 150.0 |
| mercury_north_pole | leo > mercury_north_pole | 0.0 | -89.9 | 105 | 0.0 |

## ISRU chain chosen

| Site | Chain | Local share | MWh per t | Feedstock t/t |
|---|---|---|---|---|
| moon_south_pole | o2_regolith | 0.783 | 12.35 | 2.0 |
| mars_arcadia | sabatier | 1.0 | 8.17 | 1.0 |
| phobos | sabatier | 1.0 | 12.24 | 24.4 |
| deimos | sabatier | 1.0 | 12.24 | 24.4 |
| ceres | sabatier | 1.0 | 9.79 | 3.3 |
| callisto | sabatier | 1.0 | 9.46 | 17.5 |
| ganymede | o2_regolith | 0.783 | 12.28 | 2.0 |
| europa | o2_regolith | 0.783 | 12.25 | 2.0 |
| titan | native_ch4 | 1.0 | 13.48 | 1.0 |
| enceladus | o2_regolith | 0.783 | 12.25 | 2.0 |
| venus_clouds | imported_h2 | 0.945 | 8.31 | 0.0 |
| mercury_north_pole | sabatier | 1.0 | 11.51 | 8.1 |

## Outpost refill check

| Site | Onward to | Window days | Outpost MWe | Days to fill a ship | Meets window |
|---|---|---|---|---|---|
| moon_south_pole | leo | 365 | 2.71 | 404 | False |
| mars_arcadia | leo | 780 | 1.82 | 404 | True |
| phobos | ceres | 1161 | 2.69 | 404 | True |
| deimos | leo | 780 | 2.69 | 404 | True |
| ceres | callisto | 2747 | 2.16 | 404 | True |
| callisto | leo | 399 | 2.09 | 404 | False |
| ganymede | leo | 399 | 2.7 | 404 | False |
| europa | leo | 399 | 2.69 | 366 | True |
| titan | leo | 378 | 2.95 | 366 | True |
| enceladus | leo | 378 | 2.69 | 366 | True |
| venus_clouds | leo | 584 | 1.84 | 404 | True |
| mercury_north_pole | leo | 116 | 2.53 | 404 | False |

## Build-up (Earth launches incl. LEO tankers)

| Site | Phase | MWe | Imported t | Earth launches | Without hubs |
|---|---|---|---|---|---|
| moon_south_pole | outpost | 2.71 | 327 | 20 | 20 |
| moon_south_pole | base | 17.33 | 1258 | 75 | 75 |
| moon_south_pole | city | 102.89 | 8044 | 483 | 483 |
| mars_arcadia | outpost | 1.82 | 299 | 12 | 12 |
| mars_arcadia | base | 11.72 | 1134 | 45 | 45 |
| mars_arcadia | city | 74.85 | 7196 | 288 | 288 |
| phobos | outpost | 2.69 | 326 | 20 | 20 |
| phobos | base | 17.18 | 1255 | 75 | 75 |
| phobos | city | 102.15 | 8048 | 483 | 483 |
| deimos | outpost | 2.69 | 326 | 20 | 20 |
| deimos | base | 17.18 | 1255 | 75 | 75 |
| deimos | city | 102.15 | 8048 | 483 | 483 |
| ceres | outpost | 2.16 | 310 | 19 | n/a |
| ceres | base | 13.89 | 1184 | 71 | n/a |
| ceres | city | 85.68 | 7538 | 452 | n/a |
| callisto | outpost | 2.09 | 308 | 24 | n/a |
| callisto | base | 13.44 | 1174 | 90 | n/a |
| callisto | city | 83.47 | 7502 | 576 | n/a |
| ganymede | outpost | 2.7 | 327 | 25 | n/a |
| ganymede | base | 17.23 | 1256 | 96 | n/a |
| ganymede | city | 102.39 | 8053 | 618 | n/a |
| europa | outpost | 2.69 | 326 | 25 | n/a |
| europa | base | 17.19 | 1255 | 96 | n/a |
| europa | city | 102.18 | 8068 | 619 | n/a |
| titan | outpost | 2.95 | 314 | 19 | 48 |
| titan | base | 18.84 | 1269 | 77 | 194 |
| titan | city | 110.44 | 8303 | 507 | 1,266 |
| enceladus | outpost | 2.69 | 326 | 60 | n/a |
| enceladus | base | 17.19 | 1255 | 230 | n/a |
| enceladus | city | 102.18 | 8075 | 1,479 | n/a |
| venus_clouds | outpost | 1.84 | 280 | 9 | 9 |
| venus_clouds | base | 11.9 | 1118 | 37 | 37 |
| venus_clouds | city | 75.75 | 7271 | 242 | 242 |
| mercury_north_pole | outpost | 2.53 | 322 | n/a | n/a |
| mercury_north_pole | base | 16.2 | 1234 | n/a | n/a |
| mercury_north_pole | city | 97.26 | 7837 | n/a | n/a |

## Capability reuse

| Capability | Group | Sites |
|---|---|---|
| Raptor-class methane/oxygen engine and reusable ship | transport | 12 |
| Ship-to-ship propellant transfer | transport | 12 |
| Fission surface power (FSP 40 kWe and up) | energy | 12 |
| Additive manufacturing of spares (engine parts first) | industry | 12 |
| Closed-loop life support | habitation | 12 |
| Relay communications network | operations | 12 |
| Landing pad by regolith sintering / ice paving | construction | 11 |
| On-site ship assembly and repair hangar | industry | 11 |
| Habitat shielding with regolith or ice | construction | 10 |
| Propulsive landing on airless bodies | transport | 9 |
| Cryocoolers for zero boil-off storage | ISRU | 9 |
| Autonomous operations (light time over 20 min) | operations | 9 |
| Water electrolysis | ISRU | 8 |
| Ice mining and water extraction | ISRU | 7 |
| Sabatier methanation | ISRU | 7 |
| Solar arrays with storage | energy | 5 |
| Carbon from rock or ice (pyrolysis) | ISRU | 5 |
| Oxygen from regolith (molten regolith electrolysis) | ISRU | 4 |
| Methane supply chain from another hub | ISRU | 4 |
| Building on ice below 120 K | construction | 4 |
| Aerocapture and entry heat shield | transport | 3 |
| Passive cold storage (radiators only) | ISRU | 3 |
| Steel and aluminium from local ore | industry | 3 |
| Anchoring and docking-style operations at milli-g | transport | 2 |
| Regenerative fuel cells for long nights | energy | 2 |
| CO2 capture from the atmosphere | ISRU | 2 |
| Deep burial for trapped-particle belts (>10 Sv/yr) | construction | 2 |
| Gravity assists or high-Isp (nuclear/electric) stages | transport | 1 |
| Native hydrocarbon harvesting | ISRU | 1 |
| Floating habitat and launch platform | construction | 1 |
