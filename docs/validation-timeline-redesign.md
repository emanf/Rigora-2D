# Timeline redesign validation

Date: 2026-10-18. This is a focused usability/correctness increment after Prompt
12, not the start of the next numbered milestone. Workflow and developer contracts
are documented in [timeline.md](timeline.md).

## Changes and evidence

The old ruler painted viewport-fixed text inside `QGraphicsView.drawForeground`,
while Qt could scroll/copy those pixels with scene content. Frame/marker labels
could leave stale marks in key rows. The ruler is now a separate fixed widget;
key painting fills an opaque background and uses full viewport updates. The tree
and key body have identical header/row/scroll-bar geometry. A 35-owner replay tests
partial-row offsets, full-range scrolling and return to zero, compares header
images and verifies visible key centers against actual tree row coordinates.

Persistent bottom key/tangent/property forms were replaced by a compact top
toolbar and a contextual custom-chrome Key details window. The Dope sheet fills
the remaining height. Native captures inspect 1600×1000 and 1280×800 windows,
scrolling, track picker, precision controls and light/dark palettes. The precision
window is shown before its contextual resize so native minimum-size recalculation
does not retain the hidden tangent form's old height.

The searchable picker adds supported Position/Scale/etc. lanes without altering
the pose. Double-clicking cells or dropping groups captures actual numeric keys.
MIME carries bounded owner/path references and a document-session identity, never
executable code. Drop feedback is translucent and transient; cross-session drags
are rejected. Collapsed keys select/move their constituent channels together,
preserving relative subframe offsets and committing once on release.

The new Qt-free channel descriptions and `AnimationEditingService.add_channels`
share normal command history, evaluation and storage. Capturing existing weighted
tracks uses raw samples, preserving blend semantics. Tests cover empty lanes,
duplicate prevention, locked-group atomic refusal, undo/redo, save/reopen and a
generated plugin with nested numeric parameters and custom display groups. Engine
sampling algorithms and project schema remain unchanged. Plugin display metadata
is transient and retained by document forks.

Search/Selected only follow stage owners and descendants. Timeline deformer/vertex
selections resolve back to their artwork object. Selecting a skeleton includes
its members. Filters do not mutate authoring records or mute hidden editing lanes.

## Checks

- `Test_Rigora.bat --no-pause`: **305 passed, 1 skipped, 5 warnings**, 272.83 seconds.
  Ruff lint/format and strict mypy passed (115 source modules).
- After final native sizing/header polish, the channel, timeline interaction and
  existing animation GUI/editor group passed **12 tests**. Static checks passed
  again. The two warnings in that group use Qt's deprecated drag-event test
  constructors; three equivalent existing warnings appear elsewhere in the full
  suite. The skip requires Windows Developer Mode for symlinks.
- Actual interaction tests cover key/curve dragging, grouped Scale axes, empty
  lane double-click keying, MIME enter/move/drop, unchanged source during preview,
  stale-session refusal, search and stage/skeleton filters, ruler scrubbing,
  scrolled row alignment, collapsed summaries and compact/graph detail sizing.
- Native verification created and closed only owned isolated windows. Final
  captures are ignored under
  `build/ui-preview/timeline-redesign-428c8ada0ea94fd1a3b3c861ff10ef84/`.
  Logs are under `build/maintenance/timeline-*` and `full-timeline-redesign.log`.

This increment exposes implemented scalar animation capabilities. It does not
claim a nonlinear clip compositor, audio/facial/camera feature parity with Cartoon
Animator, arbitrary new serialized value types or a full commercial motion library.
Existing graph editing, reusable clips and spring/FFD behavior remain covered by
the complete suite.

## Double-click drag regression

The Rotation-lane reproduction confirmed that Qt begins an item drag from
`mouseDoubleClickEvent` without passing through the view's `mousePressEvent`.
The missing origin snapshot let a diamond move vertically and prevented its
release from committing the time change. Both entry points now capture the same
origins before native item handling. Rebuilding the scene clears old snapshots
before deleting their graphics items, including when a double-click inserts a
key during a held gesture.

Regression checks cover newly inserted Rotation keys, ordinary and double-click
drags, snapping on/off, grouped Scale keys, release-time undo ownership and graph
keys retaining editable time/value axes. The failing Rotation replay is recorded
in `build/maintenance/keydrag-reproduce.log`.

The focused timeline/channel/animation suite passed **20 tests** (two existing
Qt test-constructor deprecation warnings); the **9 gesture regressions** also
passed with the native Windows Qt platform. Ruff lint/format and strict mypy
passed. Logs: `build/maintenance/keydrag-final.log` and `keydrag-native.log`.
