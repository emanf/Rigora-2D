# Scene and Object Editor validation

Validated on Windows with Python 3.12 and PySide6, 2026-10-22.

## Delivered interaction

- Scene represents a complete character as one expandable object. Its parts retain
  their image thumbnails and independent order inside Object Edit.
- Double-click in the preview or Scene, or use the shared context menu, to open
  the dedicated Parts / Bones / Skin / Clothing / Motions workspace.
- Unrelated geometry and authoring docks are hidden temporarily. The preview is
  framed on the object, the timeline is scoped to its channels, and the sidebar
  has a resizable Layers area. Scene restores the previous camera view, dock
  visibility, search text and timeline height.
- Parts and clothing import use native multi-file pickers and the existing
  asynchronous importer. Adoption and ownership are one undoable transaction.
  Project sources and external files can also be dropped onto character rows
  and their parts folders. Solid objects keep their separate conversion action.
- Skin has detected SVG color swatches, border width, tint and Auto key controls.
  Clothing has grouped, checkable variations and exclusive/stacked visibility.
  Motions has a visible action list, looping preview, source authoring and block
  placement with trim, speed and repeat controls.
- Appearance and motion pages hide the bone overlays for a clean artwork preview,
  without changing the Scene overlay preference or authored visibility.

## Checks

The final editor run passed **52 tests**. Combined with the impact run and the
recheck of its repaired pinning regression, **192 distinct targeted tests passed**.
Ruff lint/format passed; mypy passed for all **142 source modules**.

The final editor suite covers isolation, all five pages, repeated entry/exit,
project tab restoration, solid/character target switching, native batch adoption,
part/clothing ownership, character grouping and deletion, Undo, visibility, locks,
roots, selected-bone pinning, spring follow-through, bone parenting/snapping,
image deformation, SVG appearance, color/shape keys and motion block timing.

The impact suite covers the shared asset pipeline, scene/FFD services, rigging,
mesh operations, content placement, workspace state, unified tools, existing GUI
gestures and bundled character performances. Its initial selected-bone pinning
failure was traced to automatically isolating legacy skinned artwork whose
character record lacked image ownership. Automatic focus now follows explicit
ownership and preserves an existing bone selection. Both legacy pinning and
registered-character focus have regression checks.

Test reports are
saved as `build/object-redesign-final.xml` and `build/object-redesign-impact.xml`.

The GUI runs isolate `ContentShelf.load_thumbnails` with
`build/gesture_validation_plugin.py` because the unrelated library-poster decoder
can stall this host's Qt tests. Original character artwork, viewport rendering,
widgets, event delivery and asynchronous asset import remain active. These checks
do not certify the separate library-poster decoder or other operating systems.

## Visual evidence and limits

Actual bundled Milo side-view vector artwork was rendered on every page. Screenshots
are in `build/scene-object-redesign/`: `parts.png`, `bones.png`, `skin.png`,
`clothing.png`, `motions.png` and `scene.png`.

The redesign reuses the existing Qt-free authoring services and document format.
It adds no dependencies. It does not add arbitrary SVG path correspondence,
automatic garment creation or automatic walk generation for unconfigured rigs.
Generated shapes support compatible shape tweening; custom character actions
still require real keys or compatible retargeting. Motion instances retain their
independent timing and follow source edits. Automatic transitions between
overlapping actions are outside this change. The follow-up Scene/Object split,
saved appearance lists and validation are documented in
[Object actions and appearance choices](validation-object-actions-and-choices.md).

## Bone overlay and direction follow-up — 2026-10-23

Actual hierarchy double-clicks followed by Add bone and viewport gestures now
verify rendering above opaque artwork on Parts and Skin pages, with the normal
bone overlay enabled and hidden. Comparing viewport pixels with and without the
armature confirms that artwork does not cover it. Unrelated objects stay isolated,
and the overlay preference remains unchanged after leaving drawing.

Direction checks exercise all eight Shift-constrained rays at two zoom levels,
including Shift+Alt, immediate key transitions, preserved parenting, independent
Alt magnets, rejection of off-angle joint snapping and single-step Undo.
