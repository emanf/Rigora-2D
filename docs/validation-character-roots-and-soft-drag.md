# Character roots, image binding and Soft Drag

Validated against the installed source on 2026-10-21.

The placement-marker UI described in this historical report was removed on
2026-11-03. Drawing uses viewport positions and real bone joints; the selectable
Rig Root is the skeleton control. See [current workflow](object-character-workflow.md).

## Implementation and behavior

- `RigService.origin/move_origin` expose placement controls in scene/character
  metadata. They are not skeleton bones, do not alter the transform graph, and
  cannot be passed to ordinary bone deletion as bone identities. The native
  viewport renders constant-size root dots and retains them when hiding bones.
- `RigOrigins` owns transient root gestures, per-tab ownership, joint alignment,
  Alt bypass, deletion protection and one-step Undo. Existing move/length tools,
  Ctrl selection and locked/hidden joint behavior remain intact.
- `ImageRigService` composes existing bone, subdivision and skinning services in
  one command group. A new image rig receives a separate skeleton; future bones
  extend its binding. Only an untouched coarse import grid may be refined.
- Soft Drag captures quintic falloff weights in screen space once at press and
  uses existing vertex/control channels, evaluation and Undo/Auto key commands.
  Finite-difference drag frames invert the evaluated skinning/deformation stack
  once at press. A 90-degree posed image still follows a horizontal pointer drag.
  Near-singular local mappings freeze instead of producing unbounded coordinates.

## Validation

The final focused runs cover source preservation and PNG/SVG skinning, separate
characters, root save/Undo, root persistence after deleting every bone, explicit
root-to-character placement, snapping/Alt, FFD and vertex area dragging, fixed
gesture influence, cancellation, tab isolation, and existing bone/mesh/selection/
spring editor gestures. Reports are retained at:

- `build/root-image-mesh-regressions.xml`
- `build/root-image-gesture-regressions.xml`
- `build/root-alt-final.xml`

The headless regression run passed 75 checks. The broad native GUI/engine run
passed 64 checks. A final targeted Alt run passed nine checks covering physical
Alt press/release, cancelled root gestures, and the new pointer workflows.
There are 134 distinct passing checks across these runs. Ruff lint/format and
strict mypy also passed. Six headless checks overlap the broad run.
The existing drag/drop test emits a Qt constructor deprecation warning.

Native content-poster decoding stalled an initial GUI test fixture. The stalled
process was stopped after verifying its exact pytest command line; the owner's
running application was left open. Geometry gesture runs isolate library-poster
loading with `build/gesture_validation_plugin.py`; original artwork decoding and
actual widgets/paint/input remain active. This is not a claim to have fixed or
validated that separate poster-decoder issue.

The actual UI was visually inspected at
`build/root-soft-review/soft-drag.png`. A headless 2,461-vertex / 4,668-triangle
skinned image took 15.201 ms to prepare drag mappings once and 5.804 ms median
per geometry update (5.985 ms p95 over 60 updates). These measurements exclude
viewport painting and are retained in
`build/root-soft-review/geometry-performance.json`.
