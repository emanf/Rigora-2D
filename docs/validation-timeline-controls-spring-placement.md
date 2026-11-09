# Timeline controls and live spring placement validation

Date: 2026-11-03

## Behavior

- Timeline Eye now mutes the row in shared animation evaluation, including preview,
  playback, rendering, action layers, Object View and source-motion event routing.
  It retains the stored keys. Re-enabling restores their contribution.
- Linked actions retain independent Scene eye state when their source keys change.
  A disabled source lane also disables its contribution to placed actions.
- Lock blocks key editing, deletion, pasting and insertion into existing grouped
  Transform, Spring and deformation lanes. Clothing and camera action services
  reject insertions into their locked rows.
- Animation spans expose a user editing lock separately from their protected
  linked source keys. Locked spans cannot move, trim, change speed, delete or
  accept another placed action through the same row. Timeline dragging uses an
  arrow cursor and does not start a timing preview for locked spans.
- Long ponytail and other rig-only spring specimens now apply Scene placement in
  both canonical evaluation and live spring previews. Previously the live timer
  displayed authored coordinates near the origin until its four-second timeout
  restored the canonical pose. Shared post-simulation placement fixes that mismatch.
- Live placement retains opacity once and preserves the distinct bind-space path
  used by skinned characters.

## Evidence

The original failures were reproduced before implementation: a disabled rotation
lane still evaluated to 45 degrees, locked Transform allowed another channel,
and Long ponytail jumped from the intended `(760, 432)` to `(0, -48)` in its live
viewport pose.

Regression coverage includes all 20 current spring templates during multiple
Scene drag updates, release, live settling and timeout; inherited opacity; a
skinned character; real offscreen timeline checkbox and span input; source edit
synchronization; Undo; save/reopen; camera output and clothing insertion locks.
The spring activation and performance fixtures now use current catalog content
instead of a retired animal identity and a removed resource pack.

Validation covered 156 focused regression cases. The combined run initially
passed 155 and exposed an appearance guard that confused protected linked source
keys with a manually locked appearance lane. Excluding linked source tracks fixed
that regression; all 11 affected appearance/action cases passed on recheck.
The additional final lock-path and persistence checks passed as well.

Ruff lint and formatting checks pass across source and tests. Mypy passes for all
267 source files.

Validation runs use `QT_QPA_PLATFORM=offscreen` and dedicated temporary folders.
No executable bundle was compiled and no visible application was opened.

## Review

Score: **9/10**.

- Functional behavior and shared evaluation: 4/4.
- Data retention, source synchronization, Undo and persistence: 2/2.
- Regression coverage, including all spring specimens and skinned placement: 2/2.
- Static checks: 1/1.
- Owner's interactive desktop confirmation: 0/1; validation was offscreen.

This is a focused change review, not a claim that the entire application's test
suite was executed or that every historical fixture was migrated.
