# ADR 0005: Source-preserving mesh authoring and ordered deformation

Status: Accepted for Prompt 6. Date: 2026-10-17.

Extend format 2 records additively with `Mesh.object_id` and Vertex `pinned` /
`protected` flags. Old files acquire defaults and UUIDs remain unchanged. Meshes
already held UVs/weights/faces; stages and numeric tracks already held the needed
extensible data. No separate deformation document, schema migration, database,
new numerical dependency or second timeline is warranted.

Keep geometry, skinning, interpolation and stage evaluation Qt-free. Each stage
accepts local points plus immutable parameters/nodes and produces the same vertex
count. Stage failures preserve input geometry and report diagnostics. Explicit
bone/object bind matrices avoid ambiguous rest-world inference. Pinned vertices
resolve after the stack; masks and intensity blend each stage against its input.
Extend ScenePose with immutable MeshPose output shared by CLI and GUI.

Use displacement-form Bernstein FFD and bilinear lattices. Both have exact
neutral identity, explicit fixed bounds and customizable controls; their distinct
basis functions are numerically tested. Original presets exercise bend, bulge,
twist, squash/stretch, transform and local pins. Solvers/presets can be explicitly
injected, while project data itself never executes extensions.

Application services own validated reversible mutations. A composable command
group adds nested savepoints while the existing explicit transaction API retains
its nesting guard. Source import plus scene creation and reusable-clip import
therefore remain atomic and one undo step. MeshViewModel owns transient previews;
MeshWorkspace coordinates workers/widgets; MeshInteraction owns viewport gestures.
The main shell only selects modes/actions and displays common engine output.

Use Qt's existing image/SVG adapters in two background workers, then publish
results on the GUI thread only for the original accepted project revision.
Preserve original source bytes; cache adaptive QImage previews under a bounded
budget. CPU triangle texture mapping is sufficient for this milestone and avoids
introducing an unmeasured GPU abstraction. Disable antialiased triangle clip
edges so opaque and translucent textures have consistent internal coverage.

Portable geometric clips use bounded data-only JSON with logical vertex indices,
topology checks, UUID remapping, spatial adaptation and FPS retiming. Atomic
publication protects existing files. Full animation editors, content library,
plugin manifests and renderer/export backends remain their sequential milestones.
See [workflow and contracts](../deformation.md) for exact limits.
