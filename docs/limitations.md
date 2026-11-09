# Known limitations

Rigora 0.1.0 is a development candidate. Current production workflows are
summarized in [production workflows](production-workflows.md); dated validation
records describe the source at their stated dates, not every later addition.

## Authoring and evaluation

- Media to Rig reconstructs editable 2D human/quadruped poses and body motion
  from images, sequences and video with local
  optional models. Stylized footage can require a subject region and joint
  corrections. Its reference artwork is one skinned raster cutout, not recovered
  clothing/vector layers, unseen pixels, face/audio capture or arbitrary animal
  anatomy. See [Media to Rig](video-to-rig.md) for supported layouts and evidence.

- Multiple scenes are editable, with separate scene-local placement/animation
  state. Linked reusable Objects share artwork/rig definitions; scene transform,
  visibility and opacity stay local. Deleting an Object removes its owned data.
- Two-bone IK/contact solving requires connected positive-length segments,
  unit-magnitude scales and zero pivots. Foot contacts compensate the upper joint;
  they do not solve whole-body balance or a shared multi-foot pelvis adjustment.
- Scene attachments use one active target and held pickup/transfer/release keys.
  Automatic two-hand IK, blended dual grips and viewport grip-point dragging are
  not provided. Native TRS exports reject attachment-induced affine shear; use
  uniform target scale, disable inherited scale or choose baked output. See
  [Scene attachments](scene-attachments.md).
- Initial skin weights use nearest segments. Full/Mask topology, weight editing,
  FFD/lattices/sculpting and custom dots do not provide automatic anatomical
  skinning or arbitrary topology repair. Alpha masks and generated meshes have
  documented bounds. Rest topology edits do not retarget existing animation keys.
- Live action layers support body masks, additive/override blending and linear
  influence envelopes. State machines are forward parameter previews on existing
  actions, with reset; they are not native exported game controllers or recorded
  parameter histories. Older clip blend commands still create baked clips.
- Cubic artwork/motion paths support 64 joined segments. Progress is uniform in
  the parameter rather than arc-length speed. Object/camera path constraints do
  not replace bone-chain IK. Full SVG filter/text editing is not implemented.
- Seeded Circle/Square particles reproduce seeks and sample primary birth
  transforms. They do not sample secondary spring simulation at birth or provide
  image-texture particles or arbitrary artwork/particle-particle collision.
  Optional World-space ground collision and attract/repel magnets use bounded
  deterministic simulation. Regions are gameplay
  polygons/activation data; applications own collider and damage behavior.
- Spring seeks use bounded fixed substeps/checkpoints. Dense meshes, long cold
  seeks and stacked stages can exceed a frame budget. Preview quality and caching
  help measured costs; no GPU renderer or universal real-time guarantee is claimed.

## Media and output

- PSD/ORA import is a documented subset; unsupported features require explicit
  approximation or reject. PDF-compatible Illustrator artboards flatten with
  acknowledgement, retaining originals. Private AI layer/vector decoding is absent.
- SVG final rendering uses original vectors. Qt and the headless renderer support
  different SVG subsets; headless text needs outlines. New raster imports apply
  EXIF orientation and convert embedded ICC profiles to sRGB while retaining
  exact originals. Monitor/HDR/OCIO workflows and complete layered-format color
  preservation remain absent; see [raster color policy](color-management.md).
- PCM WAV input supports 32 independently trimmed/faded/gained tracks per clip.
  The bounded export mixer uses linear resampling/downmixing with clamping.
  Optional offline streaming phonemes use a bundled US-English acoustic model.
  Camera yaw can select existing authored views; continuous view synthesis,
  semantic speech gestures, 3D mocap and finger tracking are not supplied.
  Physical device compatibility still needs hardware QA.
- GIF has palette/binary-alpha and centisecond limits; APNG/WebP preserve smooth
  alpha. Video needs an installed compatible FFmpeg. Sparse retimed frames cannot
  preserve normal audio timing; preflight requires consecutive samples or no audio.
- Godot native 2D supports editable bones/parts and sampled scene playback.
  Unity also supports sampled camera/lens/backgrounds and batched particles.
  Planar 3D Godot/Unreal rigs support sampled bones/FFD, source/palette
  switches, clothing and events. Their scene camera/lens/particle playback is
  unsupported and rejected explicitly; use native Godot 2D, Unity or baked output.
  Region polygons remain game-owned metadata. Constraints/springs are sampled
  rather than recreated as engine physics solvers. No Spine interchange.
- Current Godot packages execute in headless native validation. Unity's updated
  native import/runtime and camera/particle rendering pass Editor and GPU pixel
  checks. Unreal plugin compilation/runtime and audio setup remain unverified.
  Unity's bundled shader targets the built-in renderer; URP/HDRP need adaptation.
- Output stages privately and cancellation discards unpublished files. Publication
  is atomic per file rather than transactional across an image sequence; disk
  failure can leave earlier published files. Queue resumption is not persistent.

## Persistence, workspace and extensions

- Background project I/O and checks avoid blocking disk work, but snapshot setup,
  validation adoption, frame evaluation and widget refresh still use CPU/memory.
  Source import has a 96 MiB embedded budget. Large packages use bounded scene
  chunks and a 512 MiB total package limit; sources remain at most 32 MiB each.
  Model records/assets are not loaded lazily from disk.
- Recovery checkpoints default to two minutes, so work since the last checkpoint
  can be lost after a crash. Restore opens an explicit unsaved copy. Filesystem
  watching is not enabled; source replacement/relinking is explicit and Undoable.
- Full/Half/Quarter retained preview quality and exact-frame caching are explicit.
  Pixel budgets are separate from model data, original vectors and Undo history.
  Undo defaults to 500 compound edits and can retain 1–10,000; this is an edit
  count, not a byte-accurate memory cap. Explicit generated-cache maintenance
  retains the current generation, two newest generations and a seven-day grace
  period. It does not detect every generation in use by another application process.
  Full keyboard/screen-reader canvas parity, multiple-monitor/DPI changes and
  non-Windows native behavior need further validation. Native Snap flyouts are absent.
- Python plugins are trusted executable code. Exception containment does not
  sandbox native crashes or infinite loops in an in-process callback. API/CLI/MCP
  share services; MCP has a separate session from the unsaved GUI and is not a
  multi-user collaborative server.

## Content and distribution

- Original procedural content is not a proprietary commercial motion catalog.
  Authored views use independent projected parts; they do not synthesize continuous
  3D turning or automatic cross-view retargeting. Audio-reactive head/brow gestures
  and local browser-source broadcast output exist; semantic gestures, NDI, Syphon,
  Adobe Dynamic Link and Adobe project interchange remain absent.
- Source/native packages and manual GitHub release builds are available. Signed
  installers, an automatic updater and cross-platform runtime QA remain separate.
  Windows is the primary development host.
- The top-level source license and owner-supplied bone redistribution provenance
  remain unresolved. See [provenance](provenance.md) before public distribution.

See [game engine exports](game-engine-export.md), [project format](project-format.md)
and [production implementation evidence](production-workflow-plan.md) for exact
current contracts, validation and remaining integration work.
