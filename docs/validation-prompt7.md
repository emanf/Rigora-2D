# Prompt 7 validation

The full gate passed with **225 tests passed**, one existing Windows symlink skip,
Ruff lint/format clean (139 files), and strict mypy clean across 75 source files.
The log is `build/maintenance/prompt7-full.log`. Subsequent review added an exact
reverse-step event check, retained hierarchy expansion, and direct cubic graph
drawing; focused animation regression checks are recorded in
`build/maintenance/prompt7-reviewed.log`.

Tests exercise subframe edits, multi-key movement, key collisions, locking,
layered playback, explicit and generated Bézier handles, clip duplication,
retiming/reversal, unkeyed root offsets, real FFD geometry changes, marker
annotations, compatible action exchange, atomic failure and project round trips.

Native Windows interaction checks passed key dragging, Bézier handle dragging,
clipboard commands, track locking, range selection, optional evaluated previews,
and dragging the body of the last IK bone. The latter moves the actual IK target,
keeps the root anchored and commits one undo command. The implementation does not
disable or remove the existing constraint to achieve movement.

An offline wheel/sdist build and archive audits passed. The installed wheel passed
the same native checks. Native captures are under ignored
`build/ui-preview/prompt7-91489f519f5f483fbd5a8fb07c35cc96/`.
Source purpose-docstrings and root batch CRLF audits passed. Test windows and
preferences were isolated from the owner's application sessions.

See `animation-editing.md` for the explicit bounds on frame-sampled blending,
compatible-rig action reuse and optional CPU visualization tools.
