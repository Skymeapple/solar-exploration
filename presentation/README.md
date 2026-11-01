# Project summary presentation

`Solar_Exploration_Project_Summary.pptx`: 46-slide deck summarising the project in four sections:
scientific research, master planning, commercial implementation and cutting-edge concepts.

Every figure carries a label: CITED (public source), MODEL (computed by `raptor_sim`),
ESTIMATE (planning assumption) or CONCEPT (not simulated).

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

Version 2 (2026-10-31): 46 slides covering all twelve workstreams: engine model, optimizer and vehicle (PR #1),
components (PR #2), business case (PR #3), sample return (PR #4), crewed missions (PR #5), transit bases (PR #6),
master roadmap (PR #8), lunar base (PR #9), crewed lunar missions (PR #10), settlement (PR #11) and the Mars
launch campaign (PR #12).
