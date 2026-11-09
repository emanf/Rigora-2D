# Scene attachment implementation validation

Source review dated 2026-11-06. This implements the accepted proposal in
[the binding review](binding-system-review-2026-11-06.md). It keeps rig binding
and placed Scene following as separate operations.

## Review criteria and score

Engineering/usability review: **8.9/10**, the rounded equal-weight average below.
This is a source and offscreen-interaction assessment, not a novice user study.

| Criterion | Score | Evidence and limits |
| --- | ---: | --- |
| Correctness | 9.0/10 | Placed final bone matrices, affine following, direct source editing, deterministic pickup/transfer/release seeks |
| Rig/data protection | 9.5/10 | Whole-character skins retained, release leaves rig/physics intact, deletion repairs references and preserves pose, atomic Undo |
| Discovery and ease of use | 8.5/10 | Guided source/target/placement/timing card, search, scene picker, Inspector shortcut, explicit Apply; custom grip placement still uses local numeric fields |
| Timeline workflow | 9.0/10 | Flat link-icon lane, initial independent key, held states, locks, mute, key capture, context guards |
| Performance | 9.0/10 | Compiled state-boundary graphs, no graph construction per frame, serial evaluation and real offscreen paint measurements below |
| Integration | 8.5/10 | Named grips share with Object definitions; Scene links remain local; Scene-copy remapping, API/plugin services, sampled native export; no automatic two-hand solver or native live attachment constraint |

## Regressions repaired

- Props bound to placed characters now follow the displayed hand through
  Scene translation, rotation and mirroring rather than its unplaced bind pose.
- Binding a whole Object retains its internal skinning instead of detaching it.
- New Scene attachments preserve authored local controls and exact evaluated
  affine matrices. Direct Scene dragging converts through the effective parent.
- Sprung hands drive prop placement after secondary motion. Attached characters
  receive the same acceleration as equivalent direct Object movement.
- Removing a target repairs setup and held keys, including an independent key
  at the current frame to preserve the current placement of an animated prop.
  Object Editor bone deletion captures outside props through a Scene-space fork.
- Locked Object ownership protects bone target picking. Setup edits cannot
  bypass locked Attachment tracks.
- Scene links are excluded from reusable Object fragments and rig-binding
  removal. Editable export samples actual following rather than authored rest
  placement. Preflight reports unrepresentable native affine shear.
- Pending editors close on Scene/clip/editor context changes and retain the
  shared timeline artwork/icon-refresh contract.

## Focused evidence

`tests/test_scene_attachments.py` covers 21 cases, including real offscreen Qt
clicks. The final context/refresh check passed all 21 cases; the preceding
attachment/binding run passed 36 cases. An expanded integration run passed 81
cases covering rig bindings, object reuse, springs, timeline actions, native
exports and automation. A strict existing Add Track category assertion was
updated to include the implemented Attachment entry.

Reports remain under ignored `build/`: `scene-attachment-context-contract.xml`,
`scene-attachment-final-core.xml` and `scene-attachment-integration2.xml`.
The final fresh-process release check passed **28 cases** covering the new
attachments and related character/timeline action editors. It also verifies
context changes, real thumbnail callbacks and a 720 × 520 window with reachable
footer controls and no horizontal form scrollbar.

## Complete source inventory and static checks

The final collected inventory contains **2,295 unique cases: 2,294 passed,
one skipped, zero unresolved failures and zero missing cases**. The skipped
case requires Windows symlink privileges/Developer Mode.

The initial broad run was interrupted between chats. Completed case evidence
was retained and the remaining files ran in isolated offscreen workers. One
long-lived UI worker encountered mixed versions of the attachment editor and
its ViewModel while the context guard was being completed. The final clean
process passed that case and all other attachment cases. The inventory report
records the earlier failure and the exact final report resolving it; duplicate
reruns are not counted as additional coverage.

`build/scene-attachment-final-inventory.json` records each unique case's result,
evidence file and source fingerprints. Broad reports are in
`build/attachments-resume-gate/`; the final recheck is
`build/scene-attachment-release-gate.xml`.

Ruff lint passed, all **516 source/test files** passed the format check, and
mypy passed all **282 source modules**. Static logs are
`build/scene-attachment-static-lint.log`, `scene-attachment-static-format.log`
and `scene-attachment-static-types.log`.

## Serial performance

Measured before concurrent full-suite workers started. Source Python/PySide6,
offscreen Windows, one Little character and a vector prop, with a pickup at frame
20 and release at frame 90. Evaluation measurements use three warmed passes of
120 frames each; paint measurements use 70 warmed frames and a reused output
image. These are local CPU/offscreen results, not GPU or universal FPS guarantees.

| Workload | Median | 95th percentile |
| --- | ---: | ---: |
| Character and prop, no attachment | 0.53 ms | 0.55 ms |
| Keyed pickup/release evaluation | 0.71 ms | 0.74 ms |
| Character with 32 additional empty followers | 4.17 ms | 4.33 ms |
| Viewport paint | 4.20 ms | 4.47 ms |
| Evaluate, prepare and paint | 5.33 ms | 5.63 ms |

The 32-follower test measures transform-following cost, not 32 detailed rendered
characters. The real viewport pick path also passed without project mutation.
Raw values and workload code are in `build/scene-attachment-performance.json`
and `build/measure_scene_attachments.py`.

## Visual inspection

Inspected final 880 × 760 screenshots in dark and light themes. Shared custom
window chrome, neutral palette, aligned fields, readable selection, distinct
source/target steps and reachable footer controls were retained. Fine alignment
is optional, and the form scrolls vertically on smaller windows. Screenshots
are `build/scene-attachments-dark.png` and `build/scene-attachments-light.png`.
No raster thumbnails or bone/hand artwork were modified.

## Scope

No executable was compiled and no native game engine was launched. Export
validation uses generated native packages and reconstructed sampled transforms.
Automatic two-hand IK and blended dual grips remain outside this implementation;
the supported workflow has one active following target per Object.
