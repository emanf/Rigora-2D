# Production workflow implementation

Owner-approved scope, 30 October 2026. These are implementation increments;
unchecked entries are pending, not available features. All interfaces use shared
application services and the Qt-free evaluator. GUI validation stays offscreen;
executable bundles are not rebuilt during development.

Completion update, 1 November 2026: [current completion work](completion-plan.md)
records the added timeline frame marks, Unity scene runtime/native validation,
streaming local speech, view switching, particle forces, Puppet replay/audio and
local browser output. Export remains unchecked here because Unreal native scene
playback/toolchain validation is still unavailable. The new targeted reports do
not replace the earlier complete-suite report.

- [x] Recovery snapshots, explicit crash restore and saved-project session restoration.
- [x] Background project open/save and chunked larger-project storage.
- [x] Performance inspector, bounded evaluated-frame caching and explicit preview quality.
- [x] General editable foot contacts with IK/root compensation and baking.
- [x] Masked animation layers, additive poses and live crossfades.
- [x] Typed game events and engine export metadata.
- [x] Safe artwork replacement with Undo and binding preservation.
- [x] Multitrack audio with trimming, fades, gain and mute/solo.
- [ ] Export preflight, wardrobe/view/event/camera parity and native engine validation.
- [x] Camera shot list, composition guides, paths, follow and shot transitions.
- [x] Parameter-driven animation state-machine preview.
- [x] Hitbox/hurtbox authoring, timeline channels and game metadata.
- [x] Editable Bezier artwork and motion paths.
- [x] Project-wide diagnostics with scene/item navigation and stale-result guards.
- [x] World-space particles with deterministic seeking and rendered output.

Export preflight and current Godot native execution are implemented. The remaining
unchecked export scope is native Unity/Unreal validation of the updated adapters
and scene-camera/particle playback in their editable rig modes. Their baked modes
retain rendered effects; explicit preflight errors prevent silent native omissions.
The complete scene route is available in the new Godot native 2D package.

For each increment: implement an end-to-end authoring/evaluation workflow,
resolve focused test findings, document actual bounds, and record a numeric review
score with criteria. GPU rendering is conditional on profiling; changing the
viewport widget alone is not a verified performance improvement. Native engine
execution requires the relevant installed engine/toolchain; unavailable validation
must be reported explicitly rather than represented as passing.

## Persistence increment

Implemented in DocumentService/SaveRequest, RecoveryStore, ProjectIOViewModel and
ProjectStorage. Recovery snapshots default to two minutes and embed linked assets
in independent private packages. File → Recover unsaved work opens copies as
unsaved tabs. Clean exit removes this run's resolved checkpoints; crash snapshots
remain available. Saved tabs/cursors reopen behind Welcome. The private checkpoint
does not replace the original project file. Save All/close decisions wait for the
actual write while processing Qt events; edits newer than a written revision remain
dirty. External-change and overwrite/backup safeguards remain active.

Large format-2 packages declare `scene-chunks-v1`. Their root metadata stays within
8 MiB, individual checksummed scene chunks within 8 MiB, total scene chunks within
256 MiB and package contents within 512 MiB. Small packages keep the previous
layout. Old releases refuse the required feature instead of discarding data.
Loading/validation is still bounded and retains all embedded source bytes; this
increment does not claim lazy per-asset loading or binary geometry arrays.

Validation reports: `build/production-storage.xml` (46 passed),
`build/production-recovery.xml` (29 passed; initial Save All completion failure),
and `build/recovery-final.xml` (6 passed, including the corrected Save All case).
Tests exercise corruption rejection, exact larger-scene round trips, responsive
Qt during blocked disk writes, edits during saves, linked-source recovery,
predecessors, source preservation, actual recovery UI and saved-tab restoration.
Review **9/10**: data integrity **4/4**, responsive persistence **2/2**, recovery
workflow **2/2**, platform coverage **1/2**. Windows/offscreen is validated;
Linux/macOS native execution remains untested. Remaining increments above are pending.

## Performance and diagnostics increment

View → Performance & project diagnostics exposes evaluation/paint timings,
node/mesh/triangle counts, conservative frame-cache accounting, retained raster
memory and last measured expensive-part paints. Counters refresh twice a second;
per-part timing stops while the inspector is hidden. Full/Half/Quarter preview
quality changes actual retained viewport tile resolution and displays a quality
indicator. Export continues to rasterize original vectors at output resolution.

The active GUI session can reuse exact evaluated samples, bounded to 64 MiB of
conservative accounting and 128 entries. Fractional frames are never quantized;
continuously varying playback times can therefore still miss the cache. Switching
clips clears retained samples; inactive GUI sessions release their frame caches,
and scratch render/preview forks have independent disabled caches. This is not
a claim of universal real-time playback or a GPU renderer.

Explicit project checks inspect sources, rig issues, evaluation warnings, output
triangle budgets and chunked-storage requirements on a worker. They sample one
frame per scene, not every frame of every clip. Findings navigate only within
the inspected immutable revision; edits invalidate old navigation.

`build/production-performance-fixed.xml`: **18 passed**, including exact-frame
reuse, clip invalidation, eviction/fork isolation, actual proxy tile pixel sizes,
unchanged source/export, background diagnostic UI and animation/spring regressions.
The first run caught an unavailable icon (replaced with a bundled glyph) and an
old spring test that addressed camera-sensitive list positions (corrected to
bone identities). Review **9/10**: correctness **4/4**, source/cache isolation
**3/3**, UI clarity **1.5/2**, platform coverage **0.5/1**. GPU acceleration remains
conditional on profiling and native hardware validation.

## Foot contact increment

Animation → Foot contacts authors connected upper/lower segments, optional foot
orientation, Object/World anchors, contact/release frames and fade envelopes.
Ordinary editable scalar keys appear in a Foot contact lane. Scene markers show
active anchors at full opacity. The Qt-free solver accounts for Object placement
once, and compensates the upper joint for targets beyond reach or inside the
knee's minimum angle. This is upper-joint compensation, not a whole-body pelvis
or multi-contact balance solver. Unit-magnitude segment scales and zero pivots
are required by the shared analytical IK solver; unsupported setups are rejected.

Bake FK action samples an isolated revision on a worker and publishes a separate
action as one Undo command. Original clips, rest poses and constraints remain.
Closing cancels the result; concurrent project/context changes reject adoption.
Sampling is bounded to 100,000 bone/frame pairs. The editor limits contacts to
the editable view and preserves rule identity/order and unrelated metadata.

Validation: `build/foot-contacts-final.xml`, ten focused tests covering grounding,
random seeking, release, save/load, separate baked-pose parity, removal/Undo,
Object placement, knee reach, actual timeline UI and responsive/stale worker
results. Review **9/10**: solver/source integrity **4/4**, authoring/history
**3/3**, responsiveness **1/1**, coverage **1/2**. Multiple simultaneous planted
feet do not calculate a shared pelvis correction; native-platform rendering is
not validated here. Initial checks exposed a coordinate-space error for placed
Objects and incomplete constraint channel metadata; both were corrected.

## Animation layer increment

Animation actions now expose layer order, weight, Override/Additive blending,
fade-in/out, Mute/Solo and a body-part mask including selected descendants.
Empty masks cover the whole Object. Higher orders evaluate later; ordinary manual
channels remain above actions. Solo is scoped to its character. Additive actions
derive offsets (scale ratios) from authored rest. Overlapping actions crossfade
live through ordinary scalar evaluation; no baked replacement is needed. Placed
action settings survive source edits and package round trips. Linear envelopes
are supported; no arbitrary weight-curve editor is claimed.

`build/motion-layers.xml`: **17 passed**, including live midpoint/peak values,
body isolation, additive offsets, Solo/Mute, source synchronization, persistence
and existing scene-action pointer/UI tests. Review **9/10**: evaluation **4/4**,
source/history **3/3**, UI integration **1.5/2**, coverage **0.5/1**.

## Source, event and audio increments

Assets → Imports → right-click → Replace artwork uses the existing background
media worker. Revisions retain asset IDs and content-address their source bytes,
so Undo restores actual old artwork. Meshes, UVs, bindings and keys stay intact.
New dimensions fit the existing geometry. Missing original files can be replaced
through the native picker; automatic filesystem watching/reloading is not enabled.
The same operation is available as `asset_replace` through Python/CLI/MCP.

The clip marker editor supports typed custom/footstep/sound/hit/spawn/despawn/signal
events with bounded JSON object payloads. They follow arranged source speed and
repeats, respect Mute/Solo, deliver through AnimationSession.last_events and the
GUI `animation.event` plugin hook, and export to runtime/sprite/editable-rig JSON.
Seeking/evaluating does not execute events. Native engine callback adapters remain
part of the export parity increment; exported payloads are data, never executable code.

Animation → Audio tracks supports 32 independent PCM WAV placements with source
trims, scene placement, gain, fades and Mute/Solo. Playback owns separate buffered
decoders. Video and editable-rig export mix to stereo PCM in bounded blocks, with
linear resampling/downmixing. Legacy single voice timing remains supported.
Audio edit/list/remove and typed events have canonical automation operations.

`build/events-artwork.xml`: **18 passed**. `build/production-audio.xml`: **23 passed**
and one delayed-voice mux regression; corrected and revalidated with **4 passing**
tests in `build/audio-fixed.xml`, including actual mixer/replacement UI and PCM
samples. Review **9/10** for each increment: integrity/evaluation **4/4**,
shared-service/history **3/3**, UI/export **1.5/2**, coverage **0.5/1**. Native audio
device listening and all engine callback integrations are not claimed by these tests.

## Bezier increment

Animation → Bezier artwork & motion paths provides a separate draggable cubic
anchor/handle canvas. Original SVG controls remain editable and replaceable while
retaining existing mesh/asset IDs. Object/camera paths use ordinary constraint
progress keys, with World/Parent coordinates and optional tangent orientation.
One path supports 64 joined cubic segments. Parameter progression is uniform,
not arc-length speed; bone chains use IK instead of this Object/camera path tool.

`build/bezier-paths.xml`: **5 passed**, including exact camera pivot midpoint,
SVG revision/Undo/storage, actual curve authoring UI and layer regressions.
The existing timeline transition graph is a separate editor. A filename collision
was caught during implementation; its workflow was restored from retained local
bytecode behavior and validated with **18 passing** existing GUI tests in
`build/graph-restoration.xml` (3 Qt deprecation warnings). No bytecode or recovery
utility is required at runtime. Review **8.5/10**: geometry/history **4/4**,
integration/regressions **3/3**, authoring polish **1/2**, platform coverage **0.5/1**.

## Game regions and particles increment

Animation → Game regions & particles authors owned rectangle/ellipse hit/hurt
regions and seeded Circle/Square emitters. Ordinary transforms/visibility/opacity
control them. Regions remain selectable editor outlines and exported metadata,
not rendered artwork or automatic engine collision policy. Object Editor limits
regions to the editable scope. Particle seeks reconstruct living primitives;
world birth positions sample primary motion, without secondary spring simulation.
Bounds: 2048 live particles/emitter, 8192/scene and 250,000 sampled particles per
editable package. Rendered output uses original vector primitives.

`build/game-effects-gui.xml`: **6 passed** after correcting the export fixture's
path-authorizer argument. Particle random seeking/world-versus-local behavior,
SVG/storage, region activation/runtime JSON and actual authoring UI are checked.
The later production parity run additionally checks Object-view region isolation.
Review **9/10**: deterministic evaluation **4/4**, authoring/history **3/3**,
render/export integration **1.5/2**, native-platform coverage **0.5/1**. Image-texture
particles, collisions and magnets remain outside this implementation.

## Camera production increment

Animation → Camera shots provides ordered shot cards, background thumbnails,
optional target following, editable Linear/Smoothstep transitions and viewport
thirds/safe guides. Thumbnails use a fork and reject stale results. Progress keys
appear in the Shot transition lane. Temporal transitions use independent active
plans, so A→B→A does not create a static constraint cycle. Removing a shot retains
camera motion/effects. Bezier paths use the shared path service above.

`build/production-cameras.xml`: **21 passed**: midpoint/end framing, returning cuts,
follow pivot/offsets, Undo/storage, actual cards/guides/worker thumbnails/timeline
rows and existing camera previews. Review **9/10**: evaluation **4/4**,
source/history **3/3**, workflow **1.5/2**, platform coverage **0.5/1**.

## State-machine increment

Animation → Animation state machine saves validated Object states, numeric/bool
parameters and ordered conditions as one Undo step. Each state references an
existing owned action with speed/loop settings. Destination blending reuses live
layers. A private forward preview accepts live inputs; reset/stop/close restore
only its owned preview. Source actions, main cursor and history remain untouched.
Bounds: 32 states, 32 parameters, 128 conditions. Parameter-history recording,
random seeking through input history and native engine controllers are not claimed.

`build/state-machines.xml`: **9 passed**; `build/state-machine-gui.xml`: **6 passed**
including existing camera-preview regressions. These cover conditions, blend
midpoints, return transitions, persistence, real input/close UI and source/history
isolation. Review **9/10**: evaluation **4/4**, ownership/history **3/3**,
UI lifecycle **1.5/2**, platform coverage **0.5/1**.

## Export parity increment

Render & export → Check export samples all requested poses and sources on a
cancellable worker, reporting explicit capabilities, errors/warnings and budgets.
Concurrent edits reject stale results. Queueing checks settings/capabilities before
publication. Native source/palette changes package distinct original-derived
textures and per-frame paths rather than rejecting the animation. Event seconds
map through actual output samples, including sparse retiming. Audio requires
consecutive samples or must be disabled. Native callbacks never fire on seeks.
The shared plugin service factory exposes the production authoring services.

The new godot-2d package creates native Skeleton2D/Bone2D and Polygon2D parts,
current-bone skinning and sampled FFD, clothing/texture switching, evaluated scene
camera/framing/lens/background layers and vector particles. Its private CanvasLayer
does not replace the game's viewport transform. Camera fit preserves aspect ratio.
The planar 3D wrappers retain their existing editable geometry and gain texture
switching/events. Their unsupported camera/lens/particle playback rejects explicitly
and directs users to native Godot 2D or baked formats. Updated Unity/Unreal native
execution remains unverified; this is why the complete export scope stays unchecked.

`build/production-export.xml`: **10 passed**; `build/planar-native.xml`: **1 passed**;
`build/production-parity-final.xml`: **13 passed**. These overlap and are not a unique
test total. Official Godot 4.7.2 console execution checks actual 2D skin vertices,
texture changes, event delivery/non-executing seeks, regions/particles and camera
lens/background layers. The planar scene imports/executes its updated wrapper.
Actual export UI was captured and visually inspected for neutral styling, readable
fields/report and visible actions. Source checks pass Ruff and mypy (250 modules).
Review **8/10**: canonical parity **3/3**, supported Godot runtime **2/2**,
UI/preflight/source isolation **2/2**, other native deployment coverage **1/3**.
This score does not mark unsupported engine behavior as complete.

## Regression hardening

Full-suite review exposed repeated linked-Object publication during private creator
assembly. A profiled all-motion specimen spent 49.5 of 64 seconds in that path.
Private assembly now defers definitions to real project adoption; an unprofiled
18-motion build completed in 3.62 seconds. These are different measurement modes,
not a claimed speedup ratio. Character/creator/template drag regressions passed
**59 tests** in `build/production-creator-regressions.xml`, including Play/Create,
prepared template export and real destination Object-library publication.

Earlier assertions were updated for automatically linked Character metadata,
Object Editor isolation and the default Main Camera. Source poses and displayed
bones remain checked independently. `build/production-baseline-fixed.xml`:
**12 passed, 1 skipped** (Windows symlink creation unavailable). Initial-frame typed
cues now fire on the first positive Play step and loop crossings, while seeks,
stopping and scratch evaluation remain non-executing. Recovery cleanup releases
closed-document revisions and reports cleanup I/O failures safely. Imported audio,
event, region and particle metadata receive explicit shape/type checks.

The initial full run loaded the older creator implementation and was interrupted
after the new performance fix. The owner subsequently paused and resumed work;
current validation is recorded below. Review of this hardening:
**9/10**: root-cause correction **4/4**, source/history contracts **3/3**,
focused regression coverage **1.5/2**, environment coverage **0.5/1**.

Later regression checks additionally exposed a retained-but-unworn glove ID and
large linked-Object/view definitions left in root metadata. Unworn clothing now
uses the service's explicit None selection. object-chunks-v1 segments large
Object definition maps, verifies exact paths/checksums and UTF-8 reassembly, and
shares the 256 MiB data budget with scene chunks. This resolves PNG turnaround
projects exceeding the root cap. A focused Unicode/corruption check and the PNG
save/reload pass. Skinned camera-follow targets now apply the same placement
matrix as visible artwork; three camera service checks pass with a moved/rotated
creator specimen in build/production-follow-final.xml.

The native Godot 2D package now serializes its Skeleton2D/Bone2D/Polygon2D nodes
into rig.tscn, so they exist in Godot's local editor before scripts run. Disabling
the exported scene camera reparents the armature to the game's normal canvas.
The current native package run, build/production-authored-godot.xml, passes eight
checks including actual native scene presence, weighted geometry, camera overlays,
texture changes, events and game-canvas integration. Native processes use hidden
console/headless flags. Review remains 8/10 for the complete export increment
because Unity/Unreal camera/particle parity and updated native execution remain
pending; this does not reduce the verified Godot feature set.

Additional authoring review fixed region-payload loss and path timing/outline
roundtrips. Invalid region JSON rejects atomically; reopening a path retains its
manual timing and does not rewrite an arranged source action. Six metadata/UI
checks pass in build/production-metadata-reviewed.xml; three path checks pass in
build/production-path-roundtrip.xml. Runtime JSON now retains evaluated camera
settings/cuts/lens strengths with the world-space nodes; that focused check passes
in build/production-camera-data.xml. These report groups overlap other runs.

## Resumed regression hardening

The export preflight now preserves the existing arbitrary-frame convention.
Forward/reverse segments retime crossed events into output seconds; repeated
samples hold without repeating callbacks. Exported occurrences are bounded to
4096, checked before rendering for formats that carry event metadata. GIF and
other pixel-only formats are unaffected by the event budget. Audio retains its
forward consecutive-sampling requirement.

Planar capability checks now include constraint-driven cameras and animated
camera parent folders. They cannot silently accept follow/dolly animation merely
because the camera itself has no direct track. Six cases exercise both indirect
drivers across all three planar adapters, while retaining the native Godot 2D route.

Timeline column anchoring preserves restored fixed Lock/Eye widths; legacy
interactive columns migrate to compact controls, and initial setup/Reset layout
explicitly restore 26-pixel defaults. The owned-character
deletion check now verifies that only independent scene cameras remain, while
retaining its geometry/rig cleanup, source retention and Undo assertions.

Native planar Godot playback preserves manually posed bones while paused,
honors AnimationPlayer speed, and delivers callbacks after thousands of loops.
The headless check exercises these behaviors in the actual engine, together with
alternate textures and non-executing seeks. Historical validation documents now
point to the current capability report instead of implying newer Unity/Unreal
runtime changes were already executed in their target editors.

`build/resume-export-final.xml`: **9 passed**; `build/resume-storage.xml`:
**10 passed**; `build/resume-godot.xml`: **1 passed**;
`build/resume-event-final.xml`: **1 passed**. Groups overlap. The initial resumed
regression group passed the HD streamed GIF, saved timeline widths, native export
and deletion checks; its new event-budget test first exceeded the existing
600-sample settings cap. The fixture was corrected to exercise >4096 event
occurrences within 600 samples and passes in the fresh reports above.
The previously interrupted integration process had completed with **15 passed**
in `build/production-integration-recheck.xml`.
The final camera/export report `build/resume-camera-guards.xml` passes **15 tests**;
`build/resume-parity-final.xml` passes **20 tests** across export and production
authoring UI (before the additional parent-folder cases). These counts overlap.

The complete run exposed three later findings. A template failure fixture still
assumed the old 8 MiB content-scene limit; it now exercises the actual 32 MiB bound.
Legacy interactive timeline headers needed migration to compact fixed controls
without clobbering modern fixed-column widths. Both restoration paths and the
template validation/rollback case pass: `build/resume-late-fixes.xml`, **3 passed**.
A toolbar test intercepted the old synchronous Open method instead of background
project I/O. Its routing check now targets the actual worker entry point; that
test and three real persistence-UI checks pass in `build/resume-toolbar-fixed.xml`.

The complete offscreen run finished with **1,381 passed, 11 failed and 1 skipped**
in 4,953 seconds (`build/resume-complete.xml`). It is not a passing post-fix full
run. Its failures are being resolved/rechecked in focused groups on the current
source rather than repeating an 82-minute suite for narrow fixes.

The later failures exposed view membership dropping owned foot-contact constraints.
View partitions now retain both constraints and deformers, and older saved view
memberships recover them through their owner's view rather than the current empty
slot. The actual Milo/Bolt view/timeline UI, portable turnarounds, Undo and editable
foot contacts pass **14 checks** in `build/resume-view-fixed.xml`, including a new
Qt-free legacy-membership regression.

Other old assertions expected every dock to start visible, 40-pixel toolbox buttons,
unimplemented motion paths, synchronous drag readiness, and a raster repaint for
pure translation. They now check the approved four default panels, a deliberately
shown inspector before floating, compact square controls, the implemented path
action and completed worker previews. Translation caching now has pixel assertions:
old pixels clear, translated artwork appears, and source changes redraw. This
fixture explicitly sets 100% zoom (`build/final-cache.xml`, **1 passed**).

Regression closure reviewed **2026-11-01**: every original full-run failure was
rechecked together on the final source. `build/final-resolved.xml` reports
**11 passed in 51 seconds**. No known failure from the complete run remains
unresolved. This focused post-fix result does not turn the earlier full report into
a passing full-suite report. The 15-test final export and 14-test view/contact
reports cover additional cases introduced during hardening and overlap other runs.

Ruff lint/format passes (660 files), and mypy passes 251 source modules.
Review of the resumed fixes: **9/10**, shared behavior
and bounded data **4/4**, layout/history preservation **2/2**, actual Godot and
focused regression evidence **2/2**, native-platform coverage **1/2**. Complete
export parity remains **8/10** under the criteria above because Unity/Unreal
scene playback and current native validation are still pending.
