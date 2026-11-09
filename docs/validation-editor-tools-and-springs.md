# Editor tools and spring validation — 2026-10-20

This maintenance pass repairs shared input ownership and spring follow-through.
It preserves the existing Bone / Chain (FK) / Rig / IK selection conventions.

## Working behavior

- Mesh editing, weight paint and deformation controls toggle off on repeated
  activation. Select & transform exits specialized mesh tools and releases any
  read-only subdivision preview. FFD transform handles remain available by
  explicitly activating deformation controls.
- Bone Editor and Spring Editor toolbar buttons toggle their windows. Add bone
  and Add pin toggle independently. Closing Bone Editor restores selection;
  Escape follows the same lifecycle. Pin radius remains editable independently
  of subdivision wireframe controls.
- Editors close on project-tab changes. Their saved background drawing/pinning
  modes reset without changing the active tab's tool. Hidden editors cannot
  intercept another editor's subdivision preview input.
- Every spring preset immediately updates existing group members or assigns the
  eligible selected branch to an empty group. Roots remain kinematic. Assigned
  properties update after a 160 ms coalescing delay and support Undo. Switching
  groups finishes the former group's pending update; removal, Undo and external
  document changes cancel stale pending settings.
- Live physics can pause/re-enable. It renders skinned meshes, targets the pose
  before spring evaluation and enforces the same minimum-joint limits as playback.
  Closing the editor stops its transient simulation. Settling adds no undo entries.

## Connected spring geometry

Translate previously displaced a child's base away from its parent's endpoint.
It now produces axial strain around the existing base. Evaluated local X scale
carries artwork and attached joints; authored transforms and parenting stay intact.
Rotation and scale compensate nonzero pivots so they cannot move the base joint.
Each spring bone's target world length bounds its strain, avoiding compounded
squash/stretch through long chains. A small positive squash floor keeps the
transform invertible. Zero-scale leaves remain flat without dividing by zero.

## Checks

The complete regression suite passed **507 tests**, with one Windows symlink
capability skip and 19 existing Qt drag-event deprecation warnings. Coverage
includes actual toolbox button clicks, editor close/Escape, scene selection,
subdivision preview release, all ten presets, live controls, pending-group edits,
fixed roots, mirrored/nonuniformly scaled parents, nonzero pivots, a 12-bone full
squash stress case, deterministic seeking, bake parity, Undo and save/reopen.
Existing dense-mesh, panning and multi-document performance tests also passed.

Ruff lint/format checks pass for `src`, `tests` and `tools`; mypy passes for all
131 source files. Final background-tab cleanup is additionally checked by
`test_editor_tool_lifecycle_gui.py` and `test_multidocument_performance.py`.

Local test records:

- `build/tool-lifecycle-full-tests-final.log`
- `build/tool-lifecycle-tests.xml`
- `build/tool-lifecycle-tab-tests.log`

Save current work and restart Rigora to load the source changes. Validation uses
isolated preferences and does not restart or replace the owner's running window.
