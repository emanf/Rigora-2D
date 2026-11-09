# ADR 0004: Undoable rest rigs and deterministic constraints

Status: Accepted for Prompt 5. Date: 2026-10-17.

Add optional bone display/group fields to existing format 2 records. Named groups
and visibility/lock properties avoid a separate rig document/database. `RigService`
uses immutable scene patches and shared affine inverse/TRS decomposition. Topology
edits preserve rest-world geometry and reject unrepresentable shear/singular
spaces. Referenced deletion fails atomically without losing animation/bindings.

Extend the existing evaluator's constraint stage using an instance-owned callable
registry. A compiled plan orders target/ancestor dependencies before numeric
priority. Rules update working poses and propagate descendants; failures restore
their input and report warnings. No previous-frame cache, plugin import or
authoring mutation participates. Two-bone IK is analytic with explicit bend,
reach, stretch and FK settings. Reflection scales support symmetric chains.

`RigViewModel` owns per-tab transient selection/tool/mode and delegates edits.
`RigWorkspace` coordinates hierarchy, viewport and inspector so the main shell
does not own solver/edit logic. Viewport gestures commit once on release. Rest
mode omits animation tracks but shares configured solvers; normal playback uses
the existing animation service. Ordinary parameter controls avoid a second model
or JSON editing workflow. Skinning, deformation, plugin loading and key editing
remain later increments; FFD requirements are retained separately for Prompt 6.
