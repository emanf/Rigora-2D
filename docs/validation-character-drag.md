# Character dragging and whole-Object flipping

Reviewed on 2026-10-29. Development targets the source application launched by
`Run_Rigora.bat`; executable compilation requires a separate owner request.
All GUI verification used Qt's offscreen platform and explicit widget events,
without native mouse movement or foreground windows.

## Review: 9/10

| Criterion | Score | Evidence |
| --- | --- | --- |
| Responsiveness | 3/3 | Scene gestures reuse compiled evaluation; whole-Object skin geometry and device-resolution artwork survive translation; dense template preparation runs off-thread once |
| Transform correctness | 3/3 | Every body/clothing vertex and bone endpoint mirrors once; feet remain attached; creator presets, robot, idle/walk/run, actual toolbar and pointer gestures checked |
| Edit integrity | 2/2 | Shared transform planning for preview/commit, one Undo per release, stale-result rejection, complete source assets, immutable plugin parameters and cache invalidation checks |
| Platform coverage | 1/2 | Windows source validated offscreen; native interactive frame pacing and other platforms remain unmeasured |

## Changes

Scene transform planning now computes desired local values without publishing a
Project on every mouse move. Ordinary drag previews feed those values into the
existing evaluator; release uses the same authoring service once. Sprites that
require rebinding, and spring histories, retain authored scratch evaluation.

Whole-Object flipping no longer explicitly mirrors bind-space rig roots that
already follow their Object placement. Whole-Object edits also leave skin bind
matrices intact; individual sprite edits retain their rebind behavior. This
keeps feet, floor controls, bone overlays, clothing and alternate hands together.

The deformation plan retains frozen static parameters and keys local skin caches
by artwork-to-Object space plus bone dependencies. Moving a whole Object can
reuse local geometry; editing a bone or moving a part relative to its rig
invalidates that geometry. The viewport retains tiles for translation, while
rotation, scale, geometry, source, appearance and zoom changes invalidate them.
Original SVGs remain the source at the current output resolution.

Template hover prepares one immutable graph off-thread and moves a retained
preview. Dropping reuses that graph when available, positions and links it in
the worker, and publishes a validated revision atomically. Static templates do
not run an unnecessary preview timer. Prepared placement retains original image
bytes, fresh identities, independent scene transforms and one-step Undo/Redo.
The content JSON member bound now matches the archive's 32 MiB member limit so
creating the robot with its entire action catalog succeeds.

## Measurements and evidence

The source workflow harness exercised a full 59-part Milo character after every
original SVG had loaded. Sixteen actual press/move/release frames, including
viewport painting, averaged **10.8 ms**, with a **13.0 ms** maximum in that run.
These are offscreen measurements, not a native-display FPS guarantee. The earlier
scratch-rebuild drag averaged approximately 34 ms/frame. Scene release still does
one validated authoring operation; it is not moved into an unvalidated fast path.

Evidence: `build/character-template-drag-performance.json`,
`build/character-drag-compiled-headless/run-1.json` (latest run uses source mode),
and `character-flipped-moved.png` beside that report. The source harness passed
33 cumulative workflow checks, including existing Object/binding/clipboard,
scene templates, pivots, bone placement, depth ordering and cameras.

**132 distinct passing source tests** cover numerical and offscreen GUI behavior.
Results are consolidated in
`build/character-verified.xml`. Ruff lint/format checks and mypy over 216 source
modules pass. During review, older spring assertions were adjusted to compare
restored physics while allowing camera outlines to remain hidden in Object
Editor; simulated transforms and edit history are still checked.

The final visual capture waits for valid SVG renderers. An earlier diagnostic
capture occurred before asynchronous loading completed and was replaced; it is
not evidence of complete artwork rendering. The temporary validation plugin is
not installed or trusted in the owner's preferences.
