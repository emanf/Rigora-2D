# Production workflow handoff

Completion update, 2026-11-01: the new authoritative status is
[completion-plan.md](completion-plan.md). Timeline frame marks, native Unity scene
playback/validation, local streaming phonemes, audio-reactive gestures, authored
camera turns, movement views, ground/magnet particles, Puppet audio/replays and
local browser-source output now have working implementations and targeted evidence.
The current affected integration run passes 70 tests; follow-up teardown checks
pass 16 tests. These overlap. Unreal native scene playback remains blocked by the
missing engine/SDK. Adobe project conversion and documented advanced limits remain
unsupported. The historical diagnosis/evidence below must not override that status.

Owner resumed this work on 2026-10-30; regression closure was reviewed on 2026-11-01.
The three fixes recorded below are now
implemented: arbitrary export sampling with bounded retimed events, preserved
timeline column widths, and the default-camera deletion assertion. The previous
integration report actually completed with 15 passing checks. New storage/recovery
coverage passes 10 checks, and current export coverage passes nine checks, including
both Godot runtimes. These groups overlap; do not add them as unique test totals.

The planar Godot wrapper also preserves manually posed bones while paused and
keeps emitting callbacks after thousands of loops. Both are checked in the actual
headless engine. Ruff lint/format passes (660 files), and mypy passes 251 modules.
The final export report build/resume-camera-guards.xml passes 15 tests, including
camera follow/parent-folder guards for all planar adapters. The final production
authoring UI/export report build/resume-parity-final.xml passes 20 tests; these
reports overlap. Unsupported indirect camera motion is rejected before rendering,
and the supported Godot native 2D route remains available.
The full run finished: **1,381 passed, 11 failed, 1 skipped**, 4,953 seconds in
build/resume-complete.xml. All eleven failures were then resolved and rechecked
together on the current source: **11 passed**, 51 seconds in
build/final-resolved.xml. Do not describe the earlier full report as passing or add
overlapping report counts. No validation process remains active.

Late fixes include legacy interactive timeline-header migration and a real view
ownership defect: foot-contact constraints disappeared from Object Editor membership
after a turnaround switch. Constraints/deformers now follow their owner's saved
view, including legacy memberships edited while an empty view is selected.
build/resume-view-fixed.xml passes 14 checks across actual Milo/Bolt editing,
turnarounds, portable saving, legacy ownership and foot contacts. Remaining stale
tests now reflect the 32 MiB content limit, background Open/drag workflows,
approved panel defaults/compact controls and implemented motion paths. Preview
translation is checked by actual pixels at explicit 100% zoom while retaining
raster reuse; source changes still redraw.
The detailed next-fix sections below preserve the original diagnosis; use this
current status rather than repeating completed edits.

## Earlier remaining-work list (superseded by completion-plan.md)

1. Implement and natively validate the remaining Unity/Unreal scene-camera/lens/
   particle playback routes. Updated Unity texture/event callbacks also need
   current target-editor execution. An Unreal installation/SDK and a genuine
   Unity Editor were unavailable at the previous toolchain check. Keep unsupported
   paths explicitly rejected until they work; retain the functioning baked routes
   and Godot native 2D route. Do not compile the Rigora application bundle.
2. Update export capability docs and scores when those routes are actually
   validated. Export remains unchecked in production-workflow-plan.md; its current
   score is 8/10. The resumed regression fixes score 9/10 under criteria recorded
   there. Cross-platform/native-device QA remains separate from Windows/offscreen.
3. Keep the broader accepted comparison backlog visible in
   character-animator-comparison.md: real-time speech recognition, automatic speech
   gestures/turn detection, movement-driven switching, collision/magnet simulation,
   Puppet Stage audio/replay integration, broadcasting and Adobe project
   interoperability are not complete. This does not authorize starting an
   unrequested numbered milestone; preserve the owner's sequential prompt policy.

For future narrow edits, use affected checks rather than repeating the entire
82-minute suite without a new reason. Reproduction command for the complete report:
`.venv/Scripts/python.exe -m pytest tests --basetemp=build/resume-complete --junitxml=build/resume-complete.xml -q --tb=short --durations=12`
with QT_QPA_PLATFORM=offscreen. Use a fresh report path if repeating it so existing
evidence is preserved. The final export and view tests include cases added after
the complete run was collected; their passing focused reports are separate evidence.

## Working constraints

- Work in this chat with one agent. Do not use Graphify or spawn reviewers.
- Use source development through Run_Rigora.bat. Do not build executable bundles.
- Run GUI validation offscreen, and native engine checks headless without taking
  focus from the owner's game.
- Preserve existing owner choices, MVVM, Qt-free domain/engine services, useful
  docstrings, and CRLF in batch files. No batch files were changed in this work.
- Reviews need numeric scores and criteria. Stop selection loops after eight
  attempts by choosing the highest-scoring working option and stating limits.
- No Git repository was initialized; do not initialize or publish automatically.

## Existing implementation and documentation

See [production-workflow-plan.md](production-workflow-plan.md) for the feature
checklist, review scores and validation evidence, and
[production-workflows.md](production-workflows.md) for the user guide. The plan's
statement that a complete test run is in progress is superseded by this pause.

Implemented work covers background project I/O and recovery, large scene/Object
metadata chunks, preview performance diagnostics, foot contacts, animation layers,
artwork replacement, typed game events, multitrack audio, editable motion paths,
game regions and particles, camera shots/follow/transitions, state-machine preview,
export preflight, and updated engine packages. This is not a claim that the whole
approved request is finished. Unity/Unreal native validation and camera/particle
runtime parity remain pending; preflight blocks unsupported planar exports.

Recent hardening includes faster character assembly (all 18 motions measured at
3.62 seconds without profiling), correct unworn retained gloves, placed-bone
camera follow, preserved region payloads and path timing/outline, initial playback
events, runtime camera metadata, animated texture variants, and an authored Godot
scene containing Skeleton2D/Bone2D/Polygon2D nodes before scripts execute.

## Completed fixes and original diagnoses (archive)

### 1. Restore arbitrary export sample order

Reproduced failure:
`tests/test_output.py::test_streamed_hd_gif_exceeds_old_budget_with_correct_palettes_timing_and_alpha`.
The test deliberately exports frames `[0, 1] * 17` at 1920 x 1080. New preflight
incorrectly rejects these with 'Animation samples must be strictly increasing'.

In application_services/export_preflight.py remove the blanket ordering error;
arbitrary forward/reverse/repeated samples are an existing export convention.
Keep forward consecutive sampling requirements specifically for included audio.
In application_services/export_metadata.py extend exported_events to follow each
sample segment instead of dropping events for non-increasing sequences:

- Emit events at the initial source frame once at zero seconds.
- Forward segment a to b includes a < event.frame <= b.
- Reverse segment includes b <= event.frame < a, in descending source order.
- Repeated samples hold without additional events.
- Event time is (segment index + (event.frame - a) / (b - a)) / output fps.
- Preserve source frame, ID and payload_json; cap exported occurrences at 4096
  and surface a ProjectError/preflight finding if exceeded.

Add a regression with events at source frames 0 and 6 and samples
`(0, 6, 12, 6, 0)`, expecting seconds 0, 1/24, 3/24 and 4/24 at 24 fps.
Update docs/game-engine-export.md ordering statements. Recheck streamed GIF,
event metadata and native package coverage.

### 2. Preserve restored timeline Lock/Eye widths

Reproduced failure:
`tests/test_preview_toolbox_gui.py::test_toolbox_and_timeline_channel_widths_survive_relaunch`.
Saved widths 39/37 reopen as 26/26. In presentation/widgets/timeline.py,
anchor_track_columns always calls resizeSection(column, 26). In
presentation/views/main_window.py (locate actual file with rg), it is called
both during layout reset and after header state restoration.

Minimal proposed fix: add keyword reset=False; retain current widths normally,
and apply 26 only at initial setup and explicit Reset layout (reset=True).
Preserve name-column Stretch and state-column Fixed modes and right anchoring.
Check relaunch, refresh, default reset and right-edge alignment regressions.

### 3. Correct owned-deletion test for the default camera

Reproduced failure:
`tests/test_owned_object_deletion.py::test_creator_object_deletion_cleans_feet_controls_and_all_owned_geometry`.
The test assumes an empty pose after deleting its character, but the independent
default Main Camera correctly remains. Assert remaining pose IDs equal scene
camera IDs. Preserve no-orphan, asset-retention and Undo checks. This finding does
not currently require changing deletion behavior.

### 4. Original validation follow-up (superseded by current status above)

Inspect existing build/production-complete.xml and stopped session evidence for
any further failures. The interrupted full run collected 1387 tests, reached at
least 72%, and loaded some source before subsequent fixes. It cannot establish
the current result. More tests were added after collection.

Already corrected since that full run began:

- Retained gloves: first_variant is explicitly None when unworn; three cases pass.
- Mustache roundtrip: Project models are exactly equal; eight mesh position
  coordinates differ by at most 5.684341886080802e-14. The test now compares other
  fields exactly and coordinates with absolute 1e-9 tolerance. A speculative
  engine/deformation.py change was reverted.
- Live spring viewport: compare source_pose to source and displayed bone nodes
  to pose.for_display(), accounting for intentional camera isolation.
- Large PNG/view project saves: object-chunks-v1 now chunks large linked Object
  maps rather than exceeding root metadata's 8 MiB cap.

The stopped integration session 23745 covered the mustache roundtrip,
tests/test_large_project_storage.py, tests/test_contact_editor_gui.py and
tests/test_production_authoring_gui.py. Inspect build/production-integration-recheck.xml
if present; do not assume it passed. Recheck storage/recovery compatibility,
chunk checksum/corruption, Unicode byte boundaries and shared 256 MiB chunk budget.

The most recent one-line Godot planar runtime change honors motion.speed_scale;
rerun relevant native tests. Retain authored manual bone poses when playing is
false and the normal game canvas when use_scene_camera is false.

After fixes, run Ruff lint/format and mypy, then a fresh complete offscreen suite
or explicitly report any incomplete coverage. Most recent static run passed
(659 formatted files and 251 mypy source files), before the remaining fixes above.
Do not broaden testing repeatedly after sufficient checks pass without a reason.

## Validation evidence to consult

Reports overlap; do not add their counts as unique tests.

| Report under build/ | Result / scope |
| --- | --- |
| production-authored-godot.xml | 8 passed; actual native authored nodes, weighted geometry, camera overlays, texture/events, normal game canvas |
| production-parity-final.xml | 13 passed; preflight UI/stale checks, regions, audio/events, native |
| production-creator-regressions.xml | 59 passed; creator/generator/template drag |
| production-baseline-fixed.xml | 12 passed, 1 skipped; authoring/bone transport, Windows symlink permission skip |
| production-metadata-reviewed.xml | 6 passed; initial events, payload atomicity, region UI |
| production-path-roundtrip.xml | 3 passed; timing, arranged source keys, outline |
| production-camera-data.xml | 2 passed; runtime camera metadata and region UI |
| production-follow-final.xml | 3 passed; shape and placed/rotated character bone follow |
| production-storage-views.xml | 5 passed, 1 failed; Unicode/corruption and PNG save passed, mustache float assertion subsequently corrected |

build/export-preflight-review.png was visually reviewed for dark neutral styling,
readable fields/report and controls. Godot 4.7.2 portable validation binaries are
in ignored build/export-validation/godot/; use the console executable with
--headless and hidden-window flags. RIGORA_GODOT may override its location.
No current Unity Editor or Unreal SDK was found; a unity.exe on PATH was not a
Unity Editor. Do not report updated Unity/Unreal native packages as validated.

## Finishing the broader request

Update the plan with fresh results and the status of every remaining item. Export
is still an open checklist item because Unity/Unreal camera/particle playback and
native checks remain outstanding. Existing export review is 8/10, explicitly
limited by that engine coverage; most completed increments are reviewed at 9/10
and paths at 8.5/10 with criteria in the plan. Re-score actual final changes and
state concrete limitations. Keep all existing user/plugin/API/format documentation
consistent. Do not introduce a new numbered milestone without the owner's request.

Final reporting should describe delivered behavior and real validation, separate
unsupported/native-unverified routes, and avoid claiming a passing full suite or
complete broad scope without evidence. No executable compilation is authorized.
