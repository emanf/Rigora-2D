# Animation evaluation contract

Prompt 4 implements scalar animation; Prompt 5 adds rig constraints and rest-bone
editing; Prompt 6 adds mesh deformation and common-timeline deformation keys.
The project format remains version 2. Persistent records and evaluated poses
have separate ownership; evaluation never writes keys, transforms or undo state.

## Shared service

```python
from pathlib import Path
from rigora.application_services.documents import DocumentService

document = DocumentService()
document.open(Path("my-project.rigora"))
session = document.animation  # First scene, first clip; scene range if no clips.
pose = session.evaluate(23.5)  # Pure random access; does not move transport.
session.seek(23.5)  # Publish a clamped transport position/pose.
session.play()
session.advance(0.25)  # Explicit seconds, independent of Qt/timer ticks.
session.pause()
session.stop()  # Return to the first frame.
```

`document.select_animation_clip(clip_uuid)` compiles a different clip atomically.
`AnimationSession(scene, clip_uuid)` can evaluate any scene directly in Python.
The desktop currently operates on the first scene. These are internal Python
services; the stable public API is a later milestone.

The CLI uses the same path:

```powershell
.\.venv\Scripts\python.exe -m rigora --evaluate my-project.rigora --frame 23.5
```

`--clip UUID` selects a clip and `--loop` wraps the requested frame. Without
`--frame`, evaluation starts at the selected clip's first frame. JSON contains
the requested/evaluated frame, node identities, local components, matrices,
visibility, bone lengths, render order and deferred-stage warnings. Errors go to
stderr and return exit code 1. No Qt import, display, artwork decode or network
connection is involved.

## Evaluation order

1. Normalize the requested absolute frame against the clip/scene range.
2. Start from authored local/rest values. Sample tracks in stored timeline order
   and blend each into its targeted scalar component.
3. Compose local matrices, then world matrices in parent-first order. Parent
   input order is irrelevant; missing/incompatible parents and cycles fail.
4. Evaluate enabled constraints in dependency order, with numeric order and
   stored index breaking ties. Recompose affected descendants after each solver.
   Invalid/cyclic rules warn and retain valid geometry. See [rigging](rigging.md).
5. Evaluate ordered mesh deformation after constraints. Sample local vertex
   coordinates and numeric deformer parameters on the same timeline; apply
   skinning, masks, FFD/lattice and other stages into immutable MeshPose output.
   Invalid stages warn and retain their input. See [deformation](deformation.md).
6. Prepare visibility and object draw order, followed by the bone overlay.
   Layer order is ascending; unlisted objects precede explicit draw-order entries
   within a layer. Slots/attachments are not part of the current preview.

`local = T(x,y) T(pivot) R(rotation) S(scale) T(-pivot)`; world is parent world
multiplied by local. Units are pixels, positive Y down and positive rotation
clockwise. A bone extends from local `(0,0)` to `(length,0)`. Negative and zero
scales are valid for forward transforms. Nonfinite results, including composed
matrices or bone endpoints, fail explicitly. Visibility propagates through
parents and hidden layers. Each call returns a fresh immutable pose.

## Sampling and blending

Supported owners are groups, objects and bones. Supported paths are
`transform.x`, `transform.y`, `transform.rotation`, `transform.scale_x`,
`transform.scale_y`, `transform.pivot_x`, `transform.pivot_y`, and bone `length`.
Keys must contain finite numeric scalars; booleans and other JSON types are
rejected during compilation. Empty tracks contribute nothing; a single key
holds its value. Values outside the keyed interval hold its endpoints.

The left key selects a segment's interpolation. Step holds its value until the
next key. Linear interpolates directly. Bezier uses the endpoints and controls
`left + tangent_out` and `right + tangent_in`, where each tangent is a relative
`(frame_offset, value_offset)`. Missing controls use one third of the frame
interval and zero value offset, giving smoothstep easing. Controls must lie in
the segment in ordered time; values may overshoot. General time curves use a
bounded 40-iteration inversion; linear time controls evaluate directly. Exact
key times return exact stored values.

Tracks apply in timeline order, with influence `w` in `[0,1]`:

| Blend | Result |
| --- | --- |
| Override | `current * (1-w) + sample * w` |
| Additive translation, rotation, pivot, length | `current + sample * w` |
| Additive scale | `current * ((1-w) + sample * w)` |

Additive scales are factors relative to identity 1; other additive values are
deltas. Rotation follows authored degrees, including full revolutions; there is
no implicit shortest-angle interpolation. A negative evaluated bone length fails.
Unsupported properties are not silently ignored. They leave the document intact
and report a preview error; a different valid clip remains selectable.

## Time and transport

Frames are absolute timeline positions, including fractional frames. Range
duration is `(out - in + 1) / fps`; a single-frame clip lasts `1 / fps` seconds.
Seconds relative to the range start convert as `frame = in + seconds * fps`.
Direct seek clamps to the displayed inclusive endpoints. Non-looping playback
holds the final frame until its full interval finishes, then stops there.
Play from the end restarts at the range start; Stop always returns there.

Looping wraps modulo `out - in + 1`, including negative or large requests.
Fractional positions within the last interval can exceed `out` but remain below
`out + 1`; keys outside the displayed range can affect that interval. If the last
key is at `out`, its value holds. A pose with looping disabled clamps to `out`.

The GUI uses elapsed monotonic seconds, not a count of display timer events.
Seeking pauses playback. Changing tabs/Welcome pauses the previous session and
retains each tab's frame. Runtime loop overrides are not saved; reopening starts
at the first clip's first frame with its authored loop preference.

## Performance

Run `python tools/benchmark_animation.py` for 1,000 bones, 1,000 tracks and
100,000 keys. `--bones`, `--tracks`, `--keys`, `--samples` and `--curve` configure
the workload. The fixture uses bounded-depth bone chains and deterministic
random/backward frame requests. JSON reports fixture construction, compilation,
median and p95 evaluation separately. It measures in-memory poses, excluding
storage, event dispatch and painting; it is not a full application FPS claim.
