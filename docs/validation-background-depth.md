# Independent Scene drops and Depth (Z)

Validated on 2026-10-29 in the owner's timezone. All GUI checks run with
`QT_QPA_PLATFORM=offscreen`, isolated preferences and explicit widget events.
No native foreground windows or OS pointer movements are used.

## Review: 9/10

| Criterion | Score | Evidence |
| --- | --- | --- |
| Requested behavior | 4/4 | Basketball drops from Templates, Imports and saved Objects remain independent in Main Scene over a selected full-frame background; new entries appear in front at equal Z; higher Z outranks scene order |
| Edit integrity | 2/2 | Default Z is zero, parent offsets accumulate, linked root Z stays per placement, values persist across save/reopen and each edit/drop undoes atomically |
| Integration | 2/2 | Painting and picking share engine order; explicit arrangements and slot references are preserved; property-strip Reset/scrolling, asset placement and linked Object regressions pass |
| Platform coverage | 1/2 | Windows source and packaged executable checked offscreen; native interactive input and Linux/macOS execution are untested |

Template artwork placement previously activated mesh editing with the previous
mesh still selected. Over a selected background, that entered its Object Editor.
Placeable Main Scene drops now select their fresh roots and remain in Scene.
Explicit browser artwork editing selects the newly returned mesh before enabling
the editor. Targeted motions, deformers and intentional rig adoption retain their
existing contracts.

New artwork omitted from an existing explicit order previously sorted behind
the explicitly ordered background. Importers now append to the resolved existing
arrangement. The shared base-order helper preserves default layer/explicit-rank
semantics, while stable sorting by effective Z applies depth priority afterward.
Root/part depth is persisted as bounded integer metadata; parent offsets add.
Equal-depth entries retain the scene order. The normal bone overlay remains a
separate editing aid rather than a depth-sorted artwork layer.

The property strip uses **Z** with accessible name **Depth (Z)** and a tooltip
explaining the convention. Default **0**, higher means in front, range
−1,000,000…1,000,000. Bones disable this field. Z is an authored static sorting
property; changing it does not add animation tracks or alter transform geometry.
Scene placement Z is excluded from shared Object definitions. Reset restores Z
to zero alongside the existing transform/appearance defaults.

## Validation

The affected source suite passed **88 tests**, exit code 0, recorded in
`build/background-depth-final.xml`. This includes actual viewport drops over a
selected background, preview non-mutation, independent ownership, frontmost hit
testing, actual artwork painting, Z field edits, Undo/Redo, negative/equal/default
depth, parent inheritance, invalid metadata rejection, linked copies, source/slot
reference preservation, scene persistence and narrow-window property scrolling.
An older deletion test was updated to retain the saved-Object source protection
introduced by linked Objects: saved definitions must be removed before their
source can be deleted.

Ruff lint and formatting pass. Mypy passes for all **213 source modules**.
The temporary application validation plugin extends the preceding 23 end-to-end
checks with three full-frame background drop/Z workflows and a persistence check.
It runs against copied settings, without changing owner preferences.

`Build_Rigora.bat --no-pause` succeeded. The exact executable at
`dist/windows-amd64-20261028-232842-01a69d/Rigora/Rigora.exe` passed all **27
offscreen end-to-end checks**, exit code 0, including actual Z field edits and
save/reopen. Evidence is `build/background-depth-compiled-headless/run-1.json`;
the reviewed screenshot is `background-depth-workspace.png` alongside it. Keep
the entire bundle folder together. The host generates build-folder timestamps
independently of the owner's timezone used for the review date above.
