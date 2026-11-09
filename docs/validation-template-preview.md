# Template preview and SVG character validation

Date: 2026-10-18. This increment redesigns the existing content preview and fixes
template dragging. Prompt 10 follows with the owner's explicit authorization;
its acceptance record is separate.

The full `Test_Rigora.bat --no-pause` gate passed **257 tests**, with the existing
Windows symlink permission skip. Ruff lint/format and mypy passed. Three warnings
come from Qt's deprecated drag-event constructor used in GUI tests. Focused tests
also cover the final preview layout and playback refinements.

Native Windows verification used an isolated Rigora window and actual mouse
press/move/release events through Windows drag-and-drop. A character was copied
from the docked template shelf into the stage with eleven editable vector parts.
The same check captured Ari, Nova, Bolt, a walking character, and animated FFD
while changing speed/strength. Source project identity remained unchanged during
all previews. The native check also renders every installed bundled template.
Captures and raw logs are ignored under `build/ui-preview/` and `build/maintenance/`.

Regression checks exercise the item view's mouse drag threshold, native MIME and
copy-action configuration, asynchronous drop completion, unchanged source rows,
placement on Welcome, default autoplay/loop, property edits retaining playback
and relative progress, explicit pause, reopening, all standalone specimens, SVG
skinning during body animation, independent placement identities, one-command
undo, and saved-project image/geometry round trips.

The collection now has **119 original CC0 items**, including three layered SVG
characters. Sources and individual parts live in `assets/characters/`. The
characters are procedural original artwork; they do not add mocap, lipsync,
contact solving or general cross-anatomy retargeting.
