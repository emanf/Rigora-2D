# Linked Objects, scene clipboard and pointer placement validation

Validated on Windows on 2026-10-28. Every GUI run used
`QT_QPA_PLATFORM=offscreen`. No native application windows, pointer movement,
foreground activation or changes to the owner's real profile were used.

## Review score: 9/10

| Criterion | Score | Evidence |
| --- | --- | --- |
| Requested behavior | 4/4 | Objects / Imports / Content; automatic and explicit save; Scene→Objects and Objects→preview drags; linked contents/actions; scene placement overrides; keyboard and right-click clipboard commands for Objects and scenes; image ghost/drop parity |
| Data safety and undo | 2/2 | Stable canonical/local identity mappings, whole-graph clone validation, saved-source retention, last-instance deletion, last-scene cut, save/reload, linked edits and Undo/Redo across scenes |
| Performance and ownership | 2/2 | Inactive scenes remain data-only; scratch previews skip publication; ghost reuse; immutable metadata sharing; 60-part move benchmark reduced from approximately 130 ms to 25 ms median |
| Platform coverage | 1/2 | Windows source and compiled app tested offscreen; interactive native docking/drag-loop verification and Linux/macOS execution were not performed |

The final affected regression run passed **107 tests**, exit code 0:
`build/objects-final-regression.xml`. It covers linked ownership, rig and action
copying, refreshed scene motion windows, metadata immutability, asset pipelines,
bindings, springs, Object Editor deletion, source ghost placement, library paste
destinations, actual clipboard shortcuts, real offscreen context menus, project
storage and automation. The suite includes the older import/ownership regression
checks rather than only tests of the new library implementation.

Ruff lint and formatting passed for source and the new tests. Mypy passed for
all **212 source modules**. The only test warnings are deprecated constructors
used to synthesize Qt drag events; no application or validation failures remain.

## Frozen application

`Build_Rigora.bat --no-pause` completed successfully. The build compiled the app;
tests were run separately. The complete bundle is:

`dist/windows-amd64-20261028-173732-83532e/Rigora/`

`build/check_objects_headless.py` launched that exact executable with a temporary
validation plugin, copied settings and the offscreen platform. All **12 end-to-end
checks passed**, exit code 0. Evidence is in
`build/objects-compiled-headless/run-1.json`, with a readable workspace capture in
`objects-workspace.png`. These checks cover source-image placement, linked Object
ghost/drop, real clipboard events, scene cloning and linked inactive edits, plus
the prior ownership/deletion/binding/context regressions. The validation plugin is
not shipped. The ordinary example plugins are included in the bundle's plugins
folder and were not enabled or trusted in the real owner profile.

## Practical boundaries

The library and clipboard are project-local; use content packs for cross-project
exchange. Scene folders, external parents/layers and bindings to objects outside
the saved Object are not embedded into definitions. Nested parts are owned by
their containing Object rather than independently synchronized nested symbols.
Duplicating a library card creates an independent definition; duplicating a scene
placement keeps its link. Source thumbnails use existing asynchronously decoded
artwork rather than eagerly rendering every stored Object. Native platform drag
feedback was not tested interactively while the owner was gaming.
