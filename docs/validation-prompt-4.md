# Prompt 4 validation — core animation engine

Validated on 2026-10-17 with Windows, CPython 3.12.14, PySide6/Qt 6.12.0,
pytest 9.1.1, Ruff 0.17.1 and mypy 1.20.2. No dependencies or storage schema
versions changed. Work used a single implementation/review agent.

## Automated checks

`Test_Rigora.bat --no-pause` passed all four stages:

- **128 passed, 1 skipped** in pytest. The existing symlink test requires Windows
  Developer Mode or a Unix host; that skip predates the animation milestone.
- Ruff lint passed.
- Ruff formatting passed across 86 files, including Python examples in Markdown.
- Strict mypy passed across 49 source files.

Numerical tests cover affine pivots/parent composition, step/linear/default and
explicit Bezier interpolation, exact keys, arbitrary/backward sampling, weighted
override/additive semantics, hidden layers, immutable poses, deep hierarchies,
cycles, missing/incompatible parents, finite overflow and negative bone lengths.
Transport tests cover inclusive boundaries, single frames, large loop advances,
pause/stop/seek and failed-evaluation rollback. Save/reopen reproduces the same
pose; authoring changes/undo rebuild runtimes without dirtying on playback.

CLI tests actively reject Qt imports and compare a loaded project evaluation
with the shared Python service. GUI tests use injected elapsed time, real widgets,
clip selection, frame fields, sliders, viewport-image changes, tab isolation and
recovery from an unsupported default clip.

Review found and resolved a Bezier exact-endpoint precision issue, finite bone
endpoint overflow, cramped track-column sizing, and outdated capability text.
New modules/classes/functions have purpose-focused docstrings. No frame cache,
solver placeholders or additional dependencies were introduced.

## Native Windows desktop

Scripted native Qt checks, with isolated preferences, passed real timer playback,
loop wrapping, scrubbing, both example clips, save/reopen equivalence and Welcome
pausing. Dark and light captures at frames 0/30 and a compact 1100 × 720 layout
were inspected. Material controls, custom title bars and neutral palettes remain
intact. The viewport shows actual evaluated object axes and bone endpoints;
artwork and key editing are explicitly deferred.

Local QA captures are under ignored `build/ui-preview/animation-*.png`; temporary
verification scripts are under `build/maintenance/`. Normal launch remains
`Run_Rigora.bat`. The historical Welcome/File example launchers and packaged
study files were removed; deterministic engine fixtures now live only in tests.

## Measured performance

`python tools/benchmark_animation.py` separates fixture construction, compilation
and evaluation. These are single-host measurements over 31 deterministic random
and backward requests, after a separate warmup. Geometry uses depth-20 chains.

| Bones | Tracks | Total keys | Curve | Compile ms | Median evaluation ms | p95 ms |
| ---: | ---: | ---: | --- | ---: | ---: | ---: |
| 100 | 100 | 1,000 | Default Bezier | 1.948 | 0.530 | 0.541 |
| 1,000 | 1,000 | 100,000 | Default Bezier | 153.038 | 6.310 | 6.765 |
| 1,000 | 1,000 | 100,000 | Linear | 47.784 | 5.833 | 5.956 |

Large-fixture construction took approximately 9.3–9.4 seconds and is excluded
from evaluation. Before removing unnecessary time inversion for default Bezier
controls, the same large workload measured 16.035 ms median / 20.728 ms p95.
General time handles still use bounded inversion. Measurements exclude disk I/O,
Qt painting and event dispatch; they do not promise a full application frame rate.

## Offline distribution

- `uv lock --check --offline` passed.
- `uv build --offline` built a wheel and source archive using the populated local
  cache. Archive inspection confirmed `.uv-cache`, `.venv` and `build` exclusion.
- The source archive includes the animation example, generator, benchmark and
  documentation. The wheel includes the engine, original app logo and bundled
  Material Icons font.
- Isolated installed-wheel core evaluation passed with Qt imports actively
  blocked. Installed-wheel GUI evaluation, two clips, viewport pose comparison
  and clean document state passed using the pinned local Qt dependency runtime.
  Imports were asserted to resolve inside each QA environment, outside editable
  source resolution.
- Batch scripts retain CRLF line endings. They install nothing at runtime.

Pytest used normal-user temporary-folder permissions on this restricted Windows
host, as described in the development guide. Prompt 5 was not started.
