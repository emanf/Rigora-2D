# Artwork pin setup and attachments

Validated on 2026-11-04 with the source application and offscreen Qt. No executable
bundle was built and no window was brought into desktop focus.

## Behavior

Bone Editor now exposes an **Artwork pins** section beside its rigging controls.
Object root is the default target. It holds the pinned region while deforming
bones pose, and carries that region with the enclosing Object's placement,
rotation and scale. An explicit bone target follows the chosen bone. Target
changes capture the displayed anchor, including after Scene placement.

All visible unlocked artwork layers show their pins while Bone Editor is open.
Click selects, Ctrl-click toggles selection, dragging repositions selected pins,
and Delete releases selected pins without deleting mesh vertices, bones or the
Object. Selected pins are red and show their radius and attachment. Target,
radius and strength edit the selection; without selection they configure the next
pin. Add pin supports repeated placement. Preview / pose leaves markers visible
and protects pin setup. Add pin resumes editing. Closing the dialog releases its
viewport callbacks.

Dragging draws transient handles and commits setup once on release. Escape and
focus loss cancel without authoring changes. Time, navigation, editing context and
document revision guard pending gestures. Moving onto another anchor rolls back
without overwriting it. Relocation retains the old source vertex and its keys and
weights; a new interpolated vertex supplies the exact relocated anchor. The
surrounding deformation updates on release.

## Implementation and compatibility

`AreaPinService` owns the Qt-free setup operations; `SkinService` inherits those
same entry points. The engine prepares attachment matrices once per pin before
the vertex loop, and strength scales the radial falloff, including at the center.
Legacy pins without target-kind/strength metadata retain their bone attachment
and full strength. Generated metadata remains plain portable project data.

The visual controller caches markers by pose and navigation. Pointer movement
does not publish commands or insert vertices. Locked-owner checks apply to both
the service and the viewport. The binding inspector omits structural containment
beneath protected Rig Root, just as it omits Object-container containment; unbind
can therefore release inspected relationships without exposing an unremovable
structural edge as a user binding.

## Verification

The affected suite passed **125 tests**. Supplemental cancellation, persistence,
legacy-metadata and benchmark cases bring coverage to **130 unique tests**.
Coverage includes repeated clicks, different artwork layers, target changes,
Ctrl-selection, group property edits, Delete, real pointer dragging, Escape,
single-step Undo, locked artwork, placement/rotation/nonuniform scale, save/load,
subdivision, binding cleanup, root interactions, original SVG rendering, cache
invalidation, pan/picking and interaction work budgets. Old binding assertions
were aligned with the existing master-root hierarchy.

The real setup drag was sampled over 12 pointer-plus-repaint frames: **2.1 ms
median, 19.3 ms maximum**, with one pin, two deforming bones and vector artwork on
this host. This is an offscreen representative case, not a guarantee for dense
artwork or many pins. Raw results remain in `build/artwork-pin-performance.json`.
A bounded-work test verifies attachment matrix inverses do not grow with affected
vertex count. Broader editor/Creator profiles are retained under
`build/interaction-performance/artwork-pins*.json`.

Ruff lint/format pass for all 494 Python files; mypy passes for all 269 source
files. Visual evidence is retained in `build/artwork-pin-editor.png` and
`build/artwork-pin-controls.png`.

Review score: **9/10**, based on anchoring correctness, visual editing, undo/data
preservation, compatibility and bounded interactive work. Physical display timing
and native Linux/macOS interaction were not exercised. Very dense deformation
still needs independent performance profiling.
