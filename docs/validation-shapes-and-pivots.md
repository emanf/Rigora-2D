# Shape drawing, resizing and pivots

Validated on Windows with Python 3.12 and PySide6, 2026-10-22.

## Behavior

- Shift draws equal width and height. Alt draws outward from the starting point.
  Both modifiers combine and update while the pointer remains still. The live
  guide uses the same original SVG shape generator as the committed artwork.
- Side resize handles affect only their own axis. Off-center hits no longer
  amplify perpendicular movement into a large scale change. Corners preserve
  proportions; Shift constrains side handles too. Alt uses the pivot as anchor.
- Single artwork/folder handles follow local axes, including rotated artwork
  and local resizing beneath rotated, nonuniformly scaled parents. Hover and
  active drag cursors follow those axes. Multi-selection retains scene axes.
- New images, drawn shapes and PSD/ORA image layers have centered pivots without
  changing their camera fit or layer placement. Existing authored pivots remain
  intact. Dragging the crosshair compensates translation so artwork stays still.
  Rotation uses that pivot; Center pivot resets it. Pivot edits persist and Undo.
- Pivot edits on existing object transform animation require Auto key, recording
  the pivot and compensated position together at the displayed frame. Static
  pivot edits do not insert animation keys. Bone pivots retain their base joints.
- Click-only gestures, Escape, focus cancellation and pointer coordinates at
  scene origin are covered. Complete gestures commit one history step.

## Verification

The regression run passed 109 service and GUI tests across image/asset import,
scene/FFD editing, image rigging, character ownership and existing unified tools.
The final run passed 51 checks; together these cover 125 distinct passing tests.
It adds live key transitions, constrained side resizing and the scene
origin regression, together with the existing bone snapping/parenting checks.
Held modifiers are masked as integers: Qt's enum complement could drop Alt when
releasing Shift. Drawing, scene handles and bone snapping share the corrected
key-state helper. Reports are `build/shape-pivot-regression.xml` and
`build/shape-pivot-final.xml`.

Ruff lint/format and mypy pass for the complete source tree. GUI tests isolate
the unrelated library-poster loader using `build/gesture_validation_plugin.py`;
actual SVG decoding/rendering, widgets and pointer/key events remain active.
These are Windows checks, not cross-platform certification.

The original vector screenshot is `build/shape-transform-review/pivot.png`.
No dependencies or project-format version changes were added. The existing TRS
model still rejects operations that would require storing shear.
