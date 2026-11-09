# Prompts 13–16 validation

Implemented sequentially after the current-frame bone animation and draggable
playback-cap fix. Each increment passed focused tests before the next began.

- Prompt 13: anatomical mappings/corrections, proportional motion transfer,
  missing/locked controls, timing/subframes, constraints, save/undo and desktop
  scratch preview. Eight new cases passed.
- Prompt 14: ten original SVG visemes, keyed expressions/gaze/blinks, editable
  phoneme cues, optional local WAV waveform/envelope suggestions. Core, desktop
  and existing evaluator/domain regressions passed; dialog captures were reviewed.
- Prompt 15: configurable child springs, three original bounce presets,
  squash/stretch helpers and background deterministic baking. Six new cases
  passed, including sampled pose equivalence, repeatability, native controls,
  persistence and undo. Fifteen focused dynamics/constraint cases passed together.
- Prompt 16: all five rig templates exercised through original SVG import,
  identification, fitting, mesh generation, weights, actual skin deformation,
  portable pack reuse, save/reopen and undo. Seven new cases passed. Desktop
  coverage includes modeless guide navigation, live test viewport and weight-brush
  handoff/resume.
- Fourteen new public operations use the same services through Python/CLI/MCP;
  focused automation coverage checks dry runs, actual publication, invalid cues
  and path boundaries. The combined new feature suite passed 26 cases.

Full regression: **353 passed, 1 skipped, 6 Qt deprecation warnings** in 311.04 s
using the same offscreen Qt configuration as `Test_Rigora.bat`. The skipped test
requires Windows symlink privileges. Ruff lint/format pass and strict mypy reports
126 clean source modules.

Final integration review added regressions for editing baked FK clips, retaining
clip-specific constraint/spring filtering during bone gestures, and showing
scratch previews while bone tools are active. The related rig/physics/retargeting
suite passed 47 cases; the final preview/timeline/guide suite passed 40 cases.
Native Windows rig checks passed 16 cases. Hover tests deliver Qt pointer events
directly, avoiding dependence on OS cursor routing to a background window.
Six final native Windows character/timeline UI cases passed; all three official
MCP SDK discovery/transport/HTTP regressions passed with the expanded catalog.

Wheel/source builds pass byte-for-byte source/asset, docstring, guide-link,
archive-exclusion and batch CRLF audits. The installed wheel passed core
undo/reopen, trusted plugin and CLI smoke checks in an environment without Qt.
The complete extended workflow also ran there, producing actual vector previews,
editable projects and a reusable pack. Distribution hashes are in
`dist/release-manifest.json`.

Detailed logs and captures are retained under `build/maintenance/` and
`build/ui-preview/extended-character-workflows/`.
