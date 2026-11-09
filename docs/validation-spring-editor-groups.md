# Spring Editor group workflow validation

Validated on 2026-10-21 in the local Windows/PySide6 environment.

The editor now has a group/bone tree with at least five visible rows, a native
vertical splitter, compact add/remove controls, assignment actions, independent
Presets/Property disclosures, and a fixed Body/Face + Play/Repeat footer. Ten original
solver-driven examples remain available alongside the real scene transport.

Validated behavior:

- Creating groups chooses the next unique name without a dialog. Inline renaming
  updates all references while retaining spring rule identities. Invalid names,
  collisions and renaming Default leave the project untouched.
- Tree member selection selects stage bones. Multi-selection across two groups
  survives refresh and removes the selected memberships as one undoable edit.
  Assignment moves each bone to one group; roots remain kinematic.
- Memberships, names and physics settings survive project saving/reopening. Group
  removal and renaming support Undo. Pending control changes cannot leak between
  groups or reassign removed bones.
- Resizing the tree, collapsing sections, and preview-region changes do not change
  project history. The list height survives reopening. Collapsing Presets stops its
  illustration timer; closing the editor releases preview scope and input modes.
- Body/Face scopes the actual live simulation rules for explicitly grouped facial
  bones. It does not replace timeline physics or rewrite constraints. Closing the
  editor restores the ordinary all-rig live preview.

The final primary spring/editor suite passed 34 tests. Eleven subsequent edge
checks passed, including the added invalid-name test and expanded multi-group
selection test. Ruff lint/format and strict mypy passed (133 source files).
Reports: `build/spring-editor-final-tests.xml` and
`build/spring-group-edge-final-tests.xml`.

The actual editor screenshot is `build/props-review/spring-editor.png`; the catalog
screenshot is `build/props-review/rigora-prop-browser.png`. Both were visually
reviewed. The catalog capture verifies all 289 saved posters are loaded and the
Balls filter displays twelve vector props.

The compact transport revision removes the separate Preview button, progress
slider and frame readout. Play/Pause and Repeat use the existing shared Timeline
actions beside Body/Face. Playback still releases live simulation ownership, and
closing the editor pauses animation started there. Timeline remains available for
seeking. The five focused transport/group checks passed, along with Ruff and
mypy. Regression report: `build/spring-editor-compact-focused-tests.xml`. A broader
native GUI run stalled in an unrelated Bone Editor check and was stopped; only
the completed focused run is reported as passing for this revision.

Selected-bone assignment now includes root anchors as explicit members instead of
omitting them from the group tree. Include child bones adds descendants to that
selection. Root membership persists in bone metadata; simulation constraints
remain restricted to child bones. Rename, unassign and group removal update both
types of membership atomically. Reconfiguring a former root after reparenting
clears its old anchor metadata, so removing its new spring cannot restore a stale
membership. Twenty-two spring/group checks and two additional parenting checks
passed, including save/reopen and Undo/Redo. Reports:
`build/spring-group-selected-root-tests.xml` and
`build/spring-anchor-parenting-tests.xml`. Ruff and mypy passed.

## Independent spring preview — 2026-10-23

The footer's Play/Pause and Repeat controls now belong to Spring Editor. They
run the same live angular/axial release used by presets, repeating that test
every three seconds when enabled. The existing live solver remains the only
physics clock; a single-shot timer schedules the next release or completion.
Pause retains solver state. Closing, external edits, region/group changes,
timeline seeking/playback and project switching release local ownership.

Opening the editor and toggling Repeat leave timeline looping unchanged. Preview
does not seek, create tracks or keys, or add undo entries, including with Auto key
enabled. The separately labeled Create timeline motion test command retains its
explicit clip-creation behavior and uses the main timeline controls.

Validation: 51 spring preview, group, tool lifecycle, preset visibility,
playback performance and physics tests passed offscreen. Report:
`build/spring-local-preview-regression.xml`.

The final 11 preview/group checks also passed after timeline snapping integration,
including starting presets and local Play at a fractional timeline frame without
moving it. Report: `build/spring-frame-isolation-final.xml`.
