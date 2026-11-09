# Preserve the edited Object when deleting its contents

Date: 2026-10-28.

Select All and marquee selection could include the edited container, including
an outside scene folder whose bounds enclosed the visible parts. Whole-object
deletion then removed the Object and forced Object Editor to close.

Object Editor selection now excludes its container and identities outside its
scope. The shared deletion service independently preserves the current editing
owner even if an explicit command selects it. A solid SceneObject is promoted
to a Group with the same identity before deleting its artwork; promotion and
deletion share one Undo step. Legacy Character editing keeps an empty skeleton
record so ownership remains valid. Main Scene deletion continues to remove the
complete Object, including an empty Object.

`build/object-contents-final.xml`: **27 passing headless tests**. Coverage includes
actual Ctrl+A/Delete for a solid shape, compound Object inside a scene folder,
legacy character and Human landmarks template; a second Delete on an empty
Object; atomic Undo/Redo; retained editor mode and outside Objects; explicit
container deletion; subsequent whole-Object deletion from Scene; and existing
bindings, scene-reference and Object Editor workflows. Ruff lint/format and
mypy pass for both changed source modules. Preferences and test files are
isolated, and Qt uses the offscreen platform throughout.

The compile-only Windows build passed. The resulting executable passes **seven
headless workflow checks**, including the actual Ctrl+A/Delete path with a
template rig, retained empty Object/editor mode, one-step Undo, and subsequent
whole-object deletion from Scene. Report:
`build/object-contents-compiled-headless/run-1.json`.

Updated executable:
`dist/windows-amd64-20261028-143746-768f00/Rigora/Rigora.exe`.
Keep the complete bundle folder together. Example plugins are included, and the
temporary validation plugin is not shipped. All final testing remained headless.

Review: **9/10**. Criteria: contents-versus-owner behavior **4/4**; identity and
Undo/Redo **2/2**; selection/scope isolation **2/2**; platform coverage **1/2**.
Native foreground interaction and Linux/macOS execution are untested.
