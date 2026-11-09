# Production workflows

These workflows use the same document history and evaluator as ordinary editing.
Original actions, vectors and source artwork remain editable. The bounds below
describe the current implementation; they are not a claim of complete Adobe or
game-engine behavior parity.

## Recovery and larger projects

Rigora checkpoints changed, unsaved documents every two minutes. Use **File →
Recover unsaved work**, or the Welcome recovery button, to open a checkpoint as
an unsaved copy. It includes linked source bytes and never replaces the original
file. If the latest checkpoint is damaged, an earlier valid checkpoint can be
recovered. Clean shutdown removes this run's resolved checkpoints.

Saved project tabs, active scenes, clips and cursors reopen behind Welcome.
Unsaved changes use explicit recovery rather than silently replacing a saved
project. Disk reads/writes run on a worker; edits made during a save remain dirty
after that captured revision finishes. Save All and closing wait for publication
while Qt continues processing events.

Larger format-2 packages split scene collections and linked-Object/view definitions
into checksummed chunks. Root metadata and each chunk remain bounded to 8 MiB;
all scene/Object chunks together to
256 MiB; the complete package to 512 MiB. Individual source files remain limited
to 32 MiB. Older applications reject the required chunk feature rather than
discarding records. See [project format](project-format.md).

## Performance and diagnostics

Open **View → Performance & project diagnostics** to inspect measured evaluation
and paint costs, mesh/triangle counts, cache use and costly parts. Run project
checks to inspect sources, rigs, evaluation warnings and output budgets on a
worker. Findings navigate to their scene/item only while the inspected revision
is still current. These checks sample one frame per scene.

Full/Half/Quarter preview quality controls the actual retained raster resolution.
Export always renders original vectors at output resolution. Exact evaluated
frames share a bounded 64 MiB/128-entry cache in the active GUI session. Cache
entries are not quantized and scratch documents have independent caches. This
improves repeated samples; it does not guarantee real-time playback for every rig.
No GPU renderer or automatic preview-quality changes are enabled.

## Foot contacts

1. Open the character or scene and choose **Animation → Foot contacts**.
2. Select connected upper/lower leg segments. Optionally select the foot segment
   to preserve an authored contact angle.
3. Choose Object or World coordinates, set the planted anchor, contact/release
   frames, blend duration and knee direction. Apply the interval.
4. Inspect its **Foot contact** timeline lane and scene anchor. The ordinary
   scalar weight keys remain editable. Removing the contact removes its owned
   anchor/rule/parameter tracks and retains the bones.
5. Use **Bake FK action** for a separate sampled action. The worker reads a fork
   and publishes one Undo command only if the source context is still unchanged.

The analytical solver compensates the upper joint when the target is beyond
reach or inside the knee's minimum angle. It requires unit-magnitude segment
scales and zero pivots. It does not calculate whole-body balance or a shared
pelvis correction for several simultaneous planted feet. Baking is bounded to
100,000 bone/frame pairs and refuses incomplete evaluated poses.

## Layered actions

Edit an Animation segment in the main timeline to set **Layer**, **Weight**,
**Override/Additive**, **Fade in/out**, **Mute/Solo** and its body-part mask.
An empty mask affects the entire Object; selecting a body branch includes its
descendants. Higher layer orders evaluate later, with manual keys above action
layers. Solo applies independently to each character.

Override blends toward the source pose. Additive applies offsets relative to its
authored rest pose, using ratios for scale. Overlap and fade settings crossfade
live without replacing the original action with baked keys. Envelopes are linear;
an arbitrary editable layer-weight curve is not supplied.

## Artwork replacement and audio

In **Assets → Imports**, right-click artwork and choose **Replace artwork…**.
The native picker and background importer validate the replacement before one
Undoable publication. Asset identities, geometry, UVs, bones and keys remain.
Source revisions are content-addressed so Undo restores actual old bytes.
Different image dimensions fit the existing UV geometry. Filesystem watching is
not enabled; replacement/relinking is explicit.

Choose **Animation → Audio tracks** to import PCM WAV and create independent
voice/music/effect placements. Each track has a stable name, source, start frame,
source trims, gain, fade-in/out and Mute/Solo. Trims and fades use seconds; scene
placement uses frames. Up to 32 tracks belong to a clip. Removing a placement
retains its source asset.

Playback uses independent buffered players. Video/editable-rig export mixes in
bounded blocks to 48 kHz stereo PCM with linear resampling, channel downmixing
and clamping. Sparse retimed samples cannot preserve audio timing; preflight
requires consecutive samples or disabling audio. Native Unreal audio integration
remains manual.

## Typed events and game regions

In the clip marker editor, choose custom, footstep, sound, hit, spawn, despawn or
signal and supply a JSON object payload. Arranged events follow source speed,
offsets, repeats, Mute/Solo and fades. Playback delivers crossings through
`AnimationSession.last_events` and the `animation.event` plugin hook. Scrubbing
and preview/export evaluation never execute payloads.

Exported event seconds follow the actual output samples, including sparse-frame
retiming. Engine wrappers expose Godot's `event_fired(Dictionary)`, Unity's
`EventFired` and Unreal's Blueprint `OnAnimationEvent`. Unity/Unreal include a
JSON payload string for their runtime interfaces. Game code owns event behavior;
JSON is never executed as code. A clip resolves at most 4096 event occurrences.

Choose **Animation → Game regions & particles → Regions** to create a Hitbox or
Hurtbox. Set a rectangle/ellipse, dimensions, Object parent, group and JSON payload.
Regions are selectable editor outlines and stay out of rendered artwork.
Ordinary Transform/Visibility/Opacity keys control their pose and activation.
Object Editor restricts them to its current editable scope. Runtime, sprite and
editable-rig manifests retain sampled source-pixel polygons/activation. They do
not automatically create engine colliders or impose damage/collision policy.

## Deterministic particles

The **Particles** tab creates a scene/Object emitter with seeded emission,
start/end, rate/burst, lifetime, speed, cone, direction, gravity, size, color and
Circle/Square primitives. World particles retain their emission-time position
while the emitter moves; local particles follow its current transform.

Seeking reconstructs living particles deterministically rather than depending
on playback history. Each emitter supports 2048 live particles; the scene 8192.
Editable scene exports support 250,000 particle samples per package.
The birth transform samples primary motion, without secondary spring simulation.
Original vector primitives appear in the viewport, rendered output and native
Godot 2D playback. Image-texture particles and a full collision/magnet simulator
are not provided. Other editable engine adapters reject unsupported particles
before publication; baked exports preserve their appearance.

## Camera shots and paths

Open **Animation → Camera shots** for ordered shots and background thumbnails.
Selecting a shot seeks the ordinary timeline. Set the camera/start, transition
duration and Linear/Smoothstep easing. The transition keys appear in a **Shot
transition** lane and remain ordinary editable progress channels. Returning to
an earlier camera does not create a constraint cycle. Removing a shot retains
camera motion and lens effects.

Choose optional target-follow and world offset on the same panel. Viewport guides
offer thirds, safe areas or both, inside the active camera border; guides are
editor overlays and never render. Existing camera motion presets, effects and
backgrounds use the same final renderer. Thumbnails sample a fork and stale
results are discarded.

**Animation → Bezier artwork & motion paths** provides draggable cubic anchors
and handles. Vector Artwork produces an original SVG and retains its control
metadata for later editing. Motion Path attaches an Object/camera to progress
keys in World/Parent coordinates, with optional tangent orientation. Up to 64
joined cubic segments are supported. Progress is uniform in the cubic parameter,
not arc-length speed. Bone chains use IK rather than this Object path solver.
The timeline's scalar transition graph remains a separate editor.

## State-machine preview

Choose **Animation → Animation state machine**, select the Object and add states
that reference its existing named actions. Set speed/loop per state, initial
state, numeric/boolean parameters and ordered transition conditions. Comparisons
support equality/inequality and numeric ordering. Blend duration crossfades into
the destination action. Save publishes one Undo command.

Start/reset preview, change live parameter values and inspect the resulting pose.
The preview uses a fork: source actions, main cursor and Undo history stay intact.
Stop, closing the panel or changing the source restores its owned preview. This
is forward live preview with reset, not a parameter-history recorder or an
exported engine controller. Bounds are 32 states, 32 parameters and 128 conditions.

## Export checks and engine capabilities

In **Render & export**, choose **Check export**. A cancellable worker checks all
requested samples, source assets, evaluation/mesh warnings, budgets and adapter
capabilities. The report identifies format, coverage, measured counts and
errors/warnings/information. An edit invalidates a pending report. Queueing also
checks settings/capabilities before creating output; incomplete rig evaluation
or unsupported native features cannot silently publish a partial rig.

**Godot 4 · native 2D rig + scene playback** includes authored Skeleton2D/Bone2D
and separate Polygon2D nodes in its scene file, visible in Godot's editor before
Play. Its runtime supplies current-bone skinning and sampled FFD, texture/palette changes,
clothing, camera cuts/paths/transitions, lens/backgrounds and vector particles.
Disable **Use scene camera** when placing the character under a game's Camera2D;
the armature then shares the game's canvas.
Set `playing=false`, edit bones and call `refresh_pose()` to update artwork.

Unity's editable prefab also drives sampled scene-camera cuts/affine motion,
background/lens overlays and batched vector particles. Disable
`RigoraScenePlayback.useSceneCamera` when placing it under the game's camera.
Its updated geometry, appearance, callbacks and scene playback pass native Unity
6000.6.4f1 checks and a rendered comparison against canonical pixels.

The planar 3D Godot/Unreal rig adapters retain bones, weights, FFD samples,
animated textures, wardrobes, events, regions and camera metadata. They do not
drive scene camera/lens/particle playback; preflight directs such scenes to native
Godot 2D or baked formats. Original vectors and source project remain included.
Godot 2D and planar runtimes have current headless execution checks. The updated
Unreal adapter needs validation with its target toolchain, which is not installed
here. See [engine exports](game-engine-export.md).

Explicit sample lists may move forward, reverse or hold a frame. Event times follow
each crossed segment, and holding a frame does not repeat its events. Packages
with event metadata support up to 4096 exported occurrences; image/video formats
without event metadata are unaffected by that limit. Audio still requires forward
consecutive samples at the selected output FPS.

## Movement views and particle forces

**Animation → Movement-driven views** maps an Object's authored views to Idle,
Left, Right, Up and Down. Choose a movement driver and a pixel/second threshold.
The shared evaluator samples primary world motion, including constraints; the
dominant axis chooses the view. Seeking, saving and export use the same result.
Explicit View keys take precedence. Object Editor keeps its manually selected
view. A deleted/out-of-scope driver leaves the automatic mapping dormant until
restored or replaced. Mappings require nonempty authored slots.

**Game regions & particles → Particle physics** adds a static world ground plane,
bounce/friction and a world magnet with linear radius falloff. Negative magnet
strength repels. Physics requires World space and reconstructs each particle from
its seeded birth with fixed steps, so reverse or arbitrary seeks do not depend on
playback history. Ground contact includes the circle/square's vertical extent.
This is static plane collision, not arbitrary artwork or particle-particle contact.
Frames are bounded to 200,000 simulation steps; reduce count/lifetime if necessary.

Movement and camera-turn regression coverage passes 20 checks in
`build/movement-turn-check.xml`. The final UI/particle/movement report passes 15
checks in `build/movement-particle-ui.xml`. These overlap and are not unique totals.
Review: **8.5/10** for shared evaluation, deterministic seeking, editable overrides,
ownership, persistence and UI operation; camera/device QA and arbitrary collision
geometry remain outside this increment.

## Puppet Stage audio and replays

Puppet Stage can play the active clip's audio during scratch preview. **Record
microphone** opens the chosen input only when Record is pressed. Stop releases
input first and keeps voice with the animation in one Undo step; voice-only takes
also work. Discard/close drops unpublished data. Failed/stale publication retains
the stopped take for retry, and a late worker cannot publish after Discard.

Choose an Object target and **Capture action as replay** to retain its current
owned tracks as an ordinary editable action and add a replay card. Existing
Object actions also appear as **Replay** entries in the motion selector. Cards
reference project-local actions; portable recipe cards remain independent of
project action IDs. Edit a replay in the normal Object action timeline.

Replay cards support speed and repeat, including synchronized source audio.
Audio Mixer exposes rate (which changes pitch), source advance, loop origin,
loop period and end limit so
recorded placements remain editable. Replay motion windows and audio stop at the
kept take's end. Mix nested looping audio to WAV before capturing another replay;
nested loop composition and source tracks with an early end limit are explicitly
rejected until mixed to WAV. Combined audio rates are bounded
to 0.05–20×; existing track-count and duration limits still apply.

Fifteen affected tests pass in `build/puppet-replay-final.xml`, including actual
PCM timing/mixing, recorded replay geometry and offscreen voice-only UI capture.
Review: **8.5/10** for editable data, synchronization, Undo/ownership, explicit
device lifecycle and recovery. Physical devices remain unverified.

Final hardening preserves a trimmed action's source phase/fades and voice delays
inside each replay loop. Failed triggers roll back their entire scratch edit.
Replay audio lookup also works with the GUI's separated Object/Scene action
contexts. Seventeen audio/replay/spring checks pass in
`build/completion-audio-phase.xml`; the public API/automation/MCP follow-up passes
16 checks in `build/completion-audio-api.xml`. Groups overlap.
