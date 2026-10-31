# Project summary presentation

`Solar_Exploration_Project_Summary.pptx`: 30-slide deck summarising the project in four sections:
scientific research, master planning, commercial implementation and cutting-edge concepts.

Every figure carries a label: CITED (public source), MODEL (computed by `raptor_sim`),
ESTIMATE (planning assumption), CONCEPT (not simulated) or PLACEHOLDER (study still running).

## Rebuilding

`build/build.js` (pptxgenjs) reads the model outputs from the project files folder
(`components/`, `business/`) plus `build/data.json` (optimizer log and iteration history extracted
from `results/`). `build/render.js` renders the SVG drawings to PNG with Playwright.

```bash
cd presentation/build
npm install pptxgenjs sharp
node render.js && node orbit.js
node build.js ../Solar_Exploration_Project_Summary.pptx
```

Version 1 (2026-10-31): engine, component, vehicle, business, sample return (PR #4), crewed missions (PR #5) and transit bases (PR #6) are in. The remaining mission,
base, settlement and roadmap studies are placeholders and will be filled in as they finish.
