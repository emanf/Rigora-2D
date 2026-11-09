# ADR 0003: Deterministic pose evaluation and transient playback

Status: Accepted for Prompt 4. Date: 2026-10-17.

## Decision

Use the existing immutable version 2 authoring records. Compile parent indices,
numeric key arrays and validated Bezier controls once per scene/clip. Evaluate
each frame from rest values; no previous pose or frame cache participates.
Iterative parent-first traversal handles deep hierarchies without recursion.
Double-precision Python floats match existing transform storage. Shared affine
math in `domain/geometry.py` keeps authoring and evaluated transforms consistent.

`SceneEvaluator` produces an immutable `ScenePose` containing local components,
local/world matrices, visibility, bone lengths, draw order and warnings. The
mapping is read-only and each pose is independent. Constraints and deformation
have explicit deferred positions in the evaluation order; no empty solver/plugin
framework is added before those milestones.

`AnimationSession` owns an evaluator, a clock-independent `PlaybackController`
and its most recent pose. `DocumentService` lazily creates one runtime per
document and rebuilds it after scene replacement. Saving does not recompile or
pause an unchanged scene. Playback never mutates authoring records or undo history.
Unsupported tracks are compilation errors, not document-loading errors.

The CLI and Python use those same services. The Qt `PlaybackViewModel` supplies
elapsed monotonic time, catches actionable errors and pauses when switching tabs.
The view paints object axes and bone endpoints from evaluated world matrices.
Timeline controls observe the session; they do not compute animation themselves.

## Consequences

Arbitrary and backward seeks produce reproducible results. Inclusive ranges give
the final frame a full display interval. Runtime loop overrides and playback
positions are deliberately transient. See [the contract](../animation-engine.md)
for exact interpolation and blending rules.

The benchmark separates model construction, compilation and evaluation. Its
first 100,000-key default-easing run measured 16.035 ms median evaluation. Removing
unnecessary Bezier time inversion for linear time controls reduced the measured
median to 6.310 ms. No complicated caching or new dependency was needed. Absolute
timings are host-specific and exclude Qt painting. Full immutable pose allocation
remains intentional for ownership and inspection; revisit it only with measured
production workloads.
