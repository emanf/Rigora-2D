# Professional feature priorities after the scene performance pass

These are proposed increments, not implemented features. Existing bones, IK, springs,
deformation, timeline editing, onion poses, motion reuse and linked source registration
already provide the foundation. Keep the shared Qt-free evaluator and application services.

## 1. GPU mesh viewport and a performance inspector

The remaining large cost is painting new, densely deformed artwork. Upload indexed
triangles, UVs and changing vertex positions, batch compatible materials, and retain
textures under a visible memory budget. Rasterize original SVGs at the required output
resolution when their source or zoom changes. Keep deterministic CPU export and an
available CPU viewport fallback.

Qt supplies an integrated OpenGL widget and documents resource sharing and context
ownership: [QOpenGLWidget](https://doc.qt.io/qt-6/qopenglwidget.html). This is an implementation
candidate; the expected Rigora speedup must be demonstrated with the existing workload
benchmarks before selecting a backend. Changing the widget alone does not establish a gain.

Add an optional inspector showing evaluation time, painting time, visible triangles,
cache hit rate and pixel memory per project. Update its counters at a low cadence so
the inspector does not become another per-frame cost. Artists should be able to identify
an expensive mesh, spring chain or material without running a Python profiler.

Acceptance: opaque/translucent seams, holes, clipping, sprites, draw order, original SVG
sharpness, HiDPI, selection and exports agree with existing reference tests; compare
integrated and discrete GPUs on Windows, Linux and macOS with graceful context failure.

## 2. Larger project storage and background open/save

The current format caps metadata at 8 MiB and packages at 128 MiB. Large generated engine
stress scenes can exceed the metadata cap even when their viewport is responsive.
Separate dense geometry/key arrays into versioned, validated package chunks and read
only required sources. Prepare a save from an immutable document snapshot on a worker;
publish it atomically and mark saved only the revision actually written. Continue to
open older project versions and preserve undo, embedded originals and recovery backups.

Acceptance: representative large projects save/reopen exactly, cancellation never damages
the destination, editing during save stays safe, and inactive tabs do not eagerly decode.
Measure opening time, save time, peak RAM and switching time as separate workloads.

## 3. Foot-plant and contact tracks

Provide editable support intervals and ground anchors for arbitrary rigs. Combine existing
IK with root motion compensation so a planted foot remains fixed while hips and the
other leg move; provide an explicit release interval for toe-off. Show contact markers
on the timeline and in the preview. Generated reference-character idle locks already
exist; this proposal makes the workflow available to an artist's own rig.

[Harmony's IK workflow](https://docs.toonboom.com/help/harmony-21/premium/cut-out-animation/about-inverse-kinematic.html)
describes fixing feet or another body part while moving the rest of a character. Rigora's
design should use its own constraints and UI, with deterministic seeks and editable keys.

Acceptance: a stationary support point drifts less than one output pixel, forward/backward
seeks agree, switching contact states blends continuously, and baking is one undoable edit.

## 4. Artwork revision and reload workflow

Extend existing linked assets with a safe refresh action and optional file watching.
Coalesce changes, decode on a worker, compare dimensions and UV implications, and preserve
the last good version after a malformed update. Replace accepted sources in one undo step
while retaining object/bone identities. Show which projects use the changed source.

[Spine's image workflow](https://us.esotericsoftware.com/spine-images) is useful reference
for an artist working with external artwork folders. Rigora must retain its own source
integrity, embedding and project isolation rules.

Acceptance: changing a texture does not lose its rig, another tab's identically named or
identically identified asset cannot overwrite it, and undo restores both pixels and metadata.

## 5. Bounded playback cache and explicit proxy previews

Cache completed clip frames in a bounded per-document store and invalidate them by actual
geometry/material dependencies. Allow an explicit preview proxy for very large images,
with a visible full-quality/proxy indicator; exports always use original sources. This
complements the current single-pose part cache and geometry memoization during navigation.

Acceptance: show memory usage and cache progress, prioritize the active project, cancel
obsolete work, never change project artwork, and verify full-quality export independently
of the selected preview setting. Do not promise realtime playback until measured.
