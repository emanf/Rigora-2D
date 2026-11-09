# Object actions and appearance choices

Validated on Windows with Python 3.12 and PySide6, 2026-10-23.

## Delivered workflow

- Scene lists whole Objects and scene folders. Bones, parts and mesh editing live
  in Object Editor. Bone/mesh tools opened from Scene focus the selected Object.
  Layered PSD/ORA placement creates one compound Object and retains its folders.
- Empty Objects can gain shapes, imported parts, folders, skeletons and blank
  named actions. A single animated image can gain a container without changing
  its identity, keys or sampled poses.
- Object animations have independent timelines and remembered playheads. Scene
  restores its own clip, frame and view on exit. Tab changes release editor
  ownership and suspend the previous transport without retaining a stale target.
- Object Editor skips unrelated mesh deformation and spring rules. Skin and
  owner descriptors are cached by document revision rather than rebuilt per tick.
- Object Editor defines named skin/color groups and clothing variations, along
  with their defaults. Solid Objects can have these options without bones. Main
  Scene exposes the same lists at the top of Inspector → Transform.
- Skin and clothing choices can be keyed in both workspaces. They switch
  discretely from their first key, preserving the default/source action before
  that key. Scene choices override an action without modifying its source keys.
  Both skin lists and clothing checkboxes follow scrubbing. Use default applies
  the group's saved default using the same key/base edit policy.
- Dropping an Object onto either timeline canvas opens the animation picker.
  Placement validates the document identity and lets the user choose action,
  frame, duration, speed and repeat. Motion blocks retain their trim/speed while
  source edits propagate to instances.
- Whole-Object translation, rotation and scale preserve skinned source motion.
  Skin binding retains the Object's coordinate space, including pin anchors and
  deformation-cache dependencies, so Scene transforms do not replace animated
  root-bone channels.
- Spring group height is measured after font/style polish, preserving its
  minimum of five readable rows.

## Evidence

The combined targeted suite is recorded in
`build/scene-object-appearance-final.xml`: **185 tests passed**. It covers object/character services,
real widget gestures, scoped timelines, default choice selection, same-document
drag/drop, speed/trim, Undo, save/reopen, source propagation, skinned coordinate
composition, SVG/raster appearance, deformation, springs, rigging, layered
imports and multi-project lifecycle/performance checks.

Readable offscreen UI captures are `build/object-choices/scene.png` and
`build/object-choices/object-editor.png`. The narrow Object sidebar is checked
for horizontal overflow. Host fonts are registered before widget construction
for these captures; the application continues to use native platform UI fonts.

All GUI checks run with `QT_QPA_PLATFORM=offscreen`; they do not open or focus the
owner's running app. Tests isolate the unrelated ContentShelf poster decoder
using `build/gesture_validation_plugin.py`. Actual widgets, event delivery,
original artwork decoding and asynchronous imports remain enabled. This is
Windows validation, not certification of other operating systems or that poster
decoder. Qt reports deprecation warnings for some test-only drag-event constructors.

Ruff lint and format checks cover source and tests. Mypy checks all 147 source
modules. No new dependency or online runtime service was introduced.

The workflow guide is [Objects, Scene and Object Editor](object-character-workflow.md).
Automatic crossfades, motion matching, arbitrary SVG contour matching and cloth
simulation are outside this change; existing source actions require actual keys.
