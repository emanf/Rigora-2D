# ADR 0011: Source-preserving media and staged output

Status: Accepted for Prompt 11. Date: 2026-10-18.

`AssetPipeline` delegates to existing document/mesh commands. Imports keep original
bytes plus derived images and optional sequence/layer descriptors in format-2
metadata. Authoritative source IDs validate in the project graph and remap when
packs create fresh entities. `SceneEvaluator` chooses sprite sources at absolute
frame times after canonical deformation; presentation and exporters consume the
same MeshPose. The domain/engine remain Qt-free and require no new dependencies.

Optional Pillow/resvg provide headless rasterization and codecs. Optional
psd-tools extracts supported pixel layers with diagnostics. OpenRaster ZIP/XML
and PCM WAV parsing use bounded standard-library readers. Static import refuses
animation/multipage containers rather than flattening them. New project sources
are budgeted before mutation, and compound imports remain undoable.

`OutputService` extends the existing evaluated SVG pipeline with staged PNG,
GIF, WebP, APNG, atlas, runtime and optional FFmpeg output. Fixed video profiles
include H.264 MP4, VP8/VP9 WebM alpha, ProRes 4444 MOV alpha and lossless BGRA FFV1
in Matroska. Alpha is kept in staged PNG frames for all transparent video profiles.
Every adapter injects the
same authorization/overwrite policy. The encoder path is host configuration,
never a tool argument; subprocess flags and lifetime are bounded. Custom
exporters are trusted, explicitly injected callbacks with one staging destination.
The desktop host discovers installed FFmpeg from PATH when no valid saved path
exists. GIF writes Pillow header/frame blocks incrementally into private staging,
retaining one rendered frame rather than accumulating the animation in memory.

`RenderQueue` owns a single worker and immutable document forks. Progress/state
are lock-protected; cancellation removes staging before an atomic publication
gate. Publication is individually atomic per file; it is not a cross-file
filesystem transaction. Work neither mutates authoring data nor uses GUI objects.

Qt ViewModels own import workers and queue polling. Import results are adopted
on the GUI thread only if the captured source project remains unchanged/open.
The dialogs use shared custom chrome and Material Icons. Closing a dialog keeps
jobs; application shutdown cancels unfinished work. CLI, API and MCP call these
same services; one-shot CLI waits while stateful hosts can poll/cancel jobs.

Runtime JSON and atlas JSON have explicit version-1 contracts in the
[asset/output guide](../asset-pipeline.md). No engine-specific compatibility or
full Photoshop, audio animation, installer or production-readiness claim is made.
