# Scene character movement validation

Windows validation, 2026-10-26. The scene movement defect was reproduced with
premades from Character Creation: a drag of (100, 50) moved body vertices by
(200, 100), while constrained feet moved by (100, 50).

## Cause and correction

Whole-Object transforms already carry skinned artwork through the owning Object
coordinate space. Part-edit handling also moved the internal rig root because
helper controls added after skin binding were absent from the skin snapshots.
The shared transform service now recognizes all bones in an owned skinned rig as
belonging to that coordinate space, including those helper controls. Individual
part edits and legacy rigs keep their existing contact-control behavior.

Actual robot creation also exposed coincident gait/contact beats that multiplied
to identical key times in Mallow's relaxed walk. The motion generator now merges
beat times at nanoframe precision before creating keys. Timeline validation
continues to reject duplicate keys.

## Evidence

- The focused regression group passed **106 tests**, recorded in
  `build/feet-regression-tests.xml`.
- Ren, Rin, Mina, Milo and Mallow were assembled through the production creator
  services. Every body/clothing mesh vertex, including hidden alternatives and
  both feet, was checked against one common scene transform. Checks cover base
  placement, Auto key, a nested scene folder, rotation and nonuniform scaling.
- Idle, walk and run were placed as Scene action instances and sampled before
  and after movement. Their source skeletons and animation timelines remained
  unchanged. Existing individual foot, legacy floor-contact and Object Editor
  tests also passed.
- Milo, Mina and Mallow were inserted through the actual Character Creation
  window and dragged with viewport mouse events. Checks include live preview,
  unchanged source data during preview, release and one-step Undo.
  A final three-case GUI recheck also waits for original SVGs to load and fits
  each complete character for inspection (`build/feet-rendered-gui-tests.xml`).
  These cases overlap the 106-test group. The rendered results in
  `build/feet-review/` were visually inspected: both feet remain attached, the
  complete figures fit the viewport, and the artwork is visible after movement.
- Mallow's complete 18-action preview catalog builds with strictly increasing
  key times. These checks exercise generated actions rather than bundled packs.
- Ruff lint and format checks passed for `src`, `tests`, `tools` and `examples`
  (348 files formatted). Strict mypy passed all 194 source files.

Review score: **9/10**, based on attachment correctness, preserved actions,
Undo/Auto key behavior, legacy compatibility and real-window coverage. The checks
use isolated offscreen Qt on Windows; other desktop platforms were not tested.
This correction does not infer or reset intentional poses in previously saved
projects.
