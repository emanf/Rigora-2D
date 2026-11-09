# Template objects, scene naming and field selection

Date: 2026-10-28.

Skeleton templates already created an Object container, but bare rigs had no
artwork polygons and their bones were excluded from main-scene picking. They
therefore had no stage selection area or transform handles. The picker now uses
visible bone endpoints for bare-object bounds. Main-scene drops retain object
selection and do not automatically enter Object Editor.

Drops on empty space create an independent container even when another object
is selected. Drops on an unlocked existing object adopt the new rig container
under it, preserving world placement. Solid artwork is promoted through the
existing object service, retaining its identity, animation and rendered position.
Rig identities and semantic mappings remain independent. Placement and adoption
are one undo step. The shared Qt-free ContentService.place accepts an optional
object_id; locked or invalid destinations roll back the entire operation.

The scene-name root row supports Rename scene in its context menu and ordinary
inline editing. Renames use SceneEditingService.rename_scene, reject empty names,
retain the scene ID/settings, and support Undo.

Text selection previously reused the dark field background as its highlight.
Dedicated neutral selection colors now provide a distinct background and legible
selected text across single-line, multiline, numeric, date/time and editable combo
editors. The change does not alter field geometry or global list selection colors.

## Validation

`build/template-object-field-regressions.xml`: 18 passing tests. These cover actual
Qt drops on an empty scene, a miss beside an existing object, an empty object and
solid artwork; whole-object movement; unchanged target artwork; atomic Undo;
ownership after save/reload; locked-target rollback; the real scene-name context
menu and inline editor; and Ctrl+A rendering in seven field types in both themes.
Existing content/specimen, placement, and main-scene appearance checks also pass.
Ruff lint/format and mypy pass for the changed source files.

Selected field captures were visually reviewed in dark and light themes. Tests
use isolated preferences and offscreen Qt, without moving the OS pointer.

`build/template-object-fields-compiled-windows/run-1.json`: the compiled app passes
seven native Windows checks covering all four drop destinations with actual
pointer-event movement and Undo, context-menu scene renaming, and painted text
selection across all seven editor types in both themes. Native testing uses a
copied profile and a separate Windows desktop that is never activated. Real
preferences and the user's foreground app remain untouched.

Compile-only output:
`dist/windows-amd64-20261028-123139-c9634e/Rigora/Rigora.exe`.
Keep its whole bundle together. Example plugins are included with their normal
trust/enablement requirements; the validation plugin is not shipped.

## Review

**9/10.** Criteria: template ownership and interaction **4/4**; scene rename and
text-selection behavior **2/2**; atomicity, Undo and persistence **2/2**; platform
coverage **1/2**. Native Linux/macOS and manual foreground mouse interaction are
not tested.
