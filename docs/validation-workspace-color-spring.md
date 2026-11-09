# Workspace, color and Spring workflow validation

## Changes and causes

Shared skin-color edits previously published and validated the whole project once
per matching part. A premade child girl with 59 meshes produced 30 scratch
publications for one shared paint. Appearance edits now validate each changed
stage and publish base parameters or keyed scalars in batches. Existing animation
keys still update at the playhead; unanimated colors remain base edits with Auto
key off. Original SVG bytes and atomic Undo are preserved.

The measured service preview fell from about 291–296 ms to 30–31 ms for base
colors. Actual picker signals plus viewport rendering measured about 43–74 ms
for base colors and 85–91 ms for keyed colors in the final focused run. This is
a measured improvement on the test character, not a 60 fps guarantee for every
project. Newly imported artwork can still require initial appearance-stage setup.

Clothing, saved-look cards and layer eye/lock/rename operations could rebuild
their own Qt tree items during native item event delivery. These mutations now
capture stable identities and run after event delivery, with document/context
guards. Rapid queued toggles resolve against current state. Tests exercise real
mouse and keyboard card interactions, replacement hands, visibility and Undo.

Welcome's dedicated animation/rigging studies, shortcuts and generated study
projects were removed. Deterministic numerical scenes now live only in test
fixtures. Reusable People and Animals packs remain available in Content Library.

Enabled main-menu toggles use plain trailing Material checkmarks in both themes.
Tools, Scene, Assets and Timeline are visible by default in the editing workspace;
Scene and Assets share a readable right column and Timeline starts at 280 pixels.
Normal close saves dock geometry, floating position, visibility, panel tabs and
the Timeline divider. Object Editor sizes are separate from the Scene layout.
Explicit floating rectangles avoid Qt's native caption-height offset when restoring
frameless panels. **View → Reset Workspace Layout** restores arrangement and view
defaults without modifying project content or unrelated preferences.

Spring motion-test clips now inherit their active editing context. Tagged driver
tracks appear in their own expandable Spring row, including Position X/Y and
Rotation children. The Scene filter no longer discards these bone-owned tracks.
Creating the motion selects its clip, clears stale filters and reveals the row.
Older Spring-test clips remain discoverable. This exposes real driver animation;
frequency/damping remain constraint settings rather than newly keyed channels.

## Evidence

- `tests/test_skin_responsiveness_hand_switch_gui.py`: premade child girl,
  real vector rendering, base/keyed paint, one scratch publication per preview,
  deferred native hand-card and layer toggles, exact Undo restoration.
- `tests/test_workspace_layout_menus_gui.py`: usable default bounds, native menu
  clicks and right-only mark pixels in both themes, fresh-shell preference restore,
  floating geometry, internal divider/tabs, close from Object Editor and reset.
- `tests/test_spring_timeline_channels_gui.py`: real Spring Editor assignment and
  motion creation in Scene and premade-character Object Editor, selected context,
  visible child channels/keys, evaluated spring targets and visibility/Undo.
- `tests/test_content_library_gui.py`: removed Welcome studies and retained
  reusable People/Animals content.

Captures are in `build/workspace-layout-review/`,
`build/spring-timeline-review/` and `build/welcome-cleanup-review.png`.
Timing details are in `build/skin-responsiveness.json`.

## Final results and review

`build/workspace-color-spring-regression.xml`: **161 passed** in 594.64 seconds,
covering the affected GUI workflows and shared animation, rigging, workspace,
character and CLI services. The run completed without a native crash. Four
existing Qt drag-event constructor deprecation warnings remain in tests.

`build/workspace-spring-visual-recheck.xml`: **3 passed**, additionally checking
the entire Add assets control's visible region and waiting for all premade artwork
to decode before reviewing the Spring playback capture.

Repository-wide Ruff lint and formatting pass (489 files); strict mypy passes
all 197 source files.

Review: **9/10**, based on five criteria: discoverable/editable Spring channels
in both contexts, working menu toggles and readable default panels, exact layout
restoration without modifying project content, measured color-preview improvement,
and safe native clothing/layer interactions with atomic Undo. The visual review
includes dark/light menus and an animated premade Panda. This is an affected-workflow
regression review; project-dependent rendering latency and full-release coverage
remain outside that score.
