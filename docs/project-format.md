# Rigora project format, version 2

A `.rigora` document is a ZIP containing UTF-8, human-readable `manifest.json`,
`project.json`, and exactly the embedded source files declared by its assets.
Nothing is extracted or executed. Optional plugin data is inert JSON.

The manifest identifies `format: "rigora"`, `format_version: 2`,
`project_file: "project.json"`, a matching `project_id`, `created_with`, and an empty
`required_features` array. Unknown required capabilities are rejected. Optional
manifest fields survive subsequent saves.

Structural schemas are provided in `schema/manifest-v2.schema.json` and
`schema/project-v2.schema.json`. Regenerate them with
`python tools/export_schema.py`. `Project.from_dict()` is the authoritative
validator for graph relationships, unique IDs, range relationships, geometry,
and finite numeric values that JSON Schema alone does not fully express.

## Canonical records

All persistent entities have stable UUIDs. Display names can change without
changing references. Names contain 1–200 nonblank UTF-8 characters. IDs are unique
across the entire project, including nested bones, vertices, tracks, and keys.
Deserialization requires stored IDs rather than generating replacements.

| Container or record | Stored responsibility |
| --- | --- |
| Project / ProjectSettings | Scenes, shared assets and references, plugin data, coordinate/time/color conventions |
| Scene / SceneSettings | Entity collections, canvas, frame rate, frame range, explicit draw order |
| Layer / Group | Visibility, locking, order, transform parenting and organization |
| SceneObject / Transform | Source asset, parent/layer, visibility, local affine transform |
| Asset / AssetReference | Source kind, location, storage policy, MIME type, optional SHA-256, stable indirection |
| Character / Skeleton / Bone | Character membership, bone collection, rest transforms and bone hierarchy |
| Mesh / Vertex | Stable vertices, UVs, normalized bone weights and indexed triangle faces |
| Slot / Attachment | Object/bone owner, attachment membership, active attachment and local transform |
| AnimationClip / Timeline / Track / Keyframe | Frame ranges, property keys, interpolation, blend policy and influence |
| Deformer / Constraint | Ordered owner/type/parameters, enabled state, optional target |
| PluginExtension | Plugin identifier, positive payload version and inert JSON payload |

Scene collections are `layers`, `groups`, `objects`, `characters`, `skeletons`,
`meshes`, `slots`, `attachments`, `clips`, `timelines`, `deformers`, `constraints`,
and `extensions`. Refer to the schema and `domain/entities.py` for individual
field defaults. Prompt 4 evaluates scalar transform/bone animation; Prompt 5 adds
rig authoring and transform/IK solvers. Prompt 6 adds source-preserving artwork
import, mesh geometry, skinning, deformation and common-timeline deformation keys.

Every scene reference resolves inside that scene, except asset references, which
resolve to project assets. Group parents are groups; object parents are objects
or groups. Bone parents belong to the same skeleton. All parent chains are
acyclic. Character references have explicit skeleton/object/mesh types. A slot's
attachment list must agree with each attachment's slot ID. Slots belong to bones
or objects. Deformers/constraints target an object, mesh or bone; constraint
targets and property-track owners resolve inside their scene. Draw-order IDs
identify objects or slots and cannot repeat.

## Coordinates, transforms, time and geometry

Units are pixels; origin is top left; X points right and Y points down. Color
metadata currently declares sRGB. Local transforms use finite double-precision
numbers and degrees, with positive rotation clockwise on screen. Column-vector
composition is:

`local = T(x,y) * T(pivot_x,pivot_y) * R(rotation) * S(scale_x,scale_y) * T(-pivot_x,-pivot_y)`

`Transform.matrix()` returns `(a,b,c,d,tx,ty)` where
`x' = a*x + c*y + tx`, `y' = b*x + d*y + ty`. A child world transform is its
parent world matrix multiplied by its local matrix. A missing parent means scene
space. Bone rest transforms use the same convention; rest length runs along
local positive X. Negative or zero scales are permitted authoring data; inverse
transforms are not needed for forward pose evaluation. Singular scales remain
valid for forward evaluation. Rig commands reject singular/unstable inverse
spaces and transformations requiring shear rather than silently losing geometry.

Optional bone fields include `visible` (true), `locked` (false), `color`
(`#bcbcbc`, validated `#RRGGBB`) and `group` (`Default`, a nonempty name). Old
version 2 records acquire defaults without an identity/reference migration.
Locks constrain authoring; constraints may still drive locked bones at runtime.
Constraint kind/owner/target/parameters/enabled/order now define executable
transform/IK contracts; unknown kinds warn and retain their data. See
[rigging](rigging.md) for solver parameters and ordering.

Canvas dimensions are integers from 1–16384. Scene frame rate is an integer from
1–240. Inclusive scene frame bounds are integers from 0–10,000,000 with
`end_frame >= start_frame`. Keys use nonnegative finite frame numbers, including
fractional frames. Seconds relative to scene start are
`(frame - start_frame) / fps`. Clips have inclusive, nonnegative ordered ranges;
keys and clips can extend beyond a scene's working range. Keys in a track have
strictly increasing, unique times. Interpolation is `step`, `linear`, or `bezier`;
optional tangent pairs store frame/value offsets. Blending is `override` or
`additive` with influence from zero to one. See the
[animation contract](animation-engine.md) for supported scalar properties, exact
handle conventions, blend semantics and inclusive playback duration. Loading
preserves unsupported animation data; compilation reports unsupported tracks.

Layer `order` and slot `draw_order` are integer ordering metadata. The explicit
scene `draw_order` list is back-to-front: unlisted objects/slots retain collection
order before listed entries. Layers partition this ordering in ascending order.
The transform preview follows this ordering for objects, then overlays bones.
Artwork meshes follow their object ordering; slots/attachments remain later work.

Mesh triangle entries are triples of distinct existing vertex IDs. Zero-area
triangles, duplicate faces and edges with more than two faces are rejected.
Optional `object_id` attaches a mesh to a SceneObject. Optional Vertex `pinned`
and `protected` default to false. These are additive format 2 fields, with no
identity migration. Bone weights reference existing bones, range from 0–1,
and sum to one within a 1e-6 tolerance when supplied. An empty weight map denotes
an unskinned vertex. Authoring services validate base geometry edits. Evaluation
samples vertex x/y and numeric `parameters.*` tracks, then executes the ordered
deformation stack after constraints. Bind matrices, field controls, pins and masks
are inert JSON on load. See [deformation](deformation.md) for runtime contracts.

## Assets and portability

A hybrid policy supports `embedded` sources under ZIP `assets/` and `external`
sources relative to the project directory. Raster, vector, audio and sequence
kinds are data declarations. **Assets → Register project asset** embeds opaque
source bytes with integrity checks. **Import artwork** inspects PNG/JPEG/static
SVG metadata and fully decodes in the GUI before creating textured geometry.
Original source bytes remain unchanged; this is not layered art expansion or
vector path authoring. The core metadata inspector remains Qt-free.

Paths use canonical forward slashes, at most 4096 characters, without absolute
paths, drives, traversal, control characters, Windows device names, or alternate
data streams. External resolution follows symlinks and rejects any resolved path
outside the project directory. A saved SHA-256 detects changed external files.
Missing/changed external sources produce warnings on open while preserving the
valid document. Reading them reports an actionable error.

Saving into a different directory with external links requires embedding those
links first. **Assets → Embed linked assets** reads all sources and commits one
undoable conversion. An unresolved source aborts conversion without changing the
project. Embedded sources remain available after the original file is removed.
Recovery retains the backup's source directory and embedded bytes.

Limits: 8 MiB root metadata, 32 MiB per embedded/source file, 512 MiB total
uncompressed contents and package file size, 4096 ZIP members, 100 scenes, and
100,000 entries per typed record collection. ZIP directories, unlisted members,
duplicate names, encrypted members, duplicate JSON keys, and oversized entries
are rejected. Reads are bounded. No executable deserialization is used.

Format-2 packages with larger scene metadata declare the required
`scene-chunks-v1` feature. Larger linked-Object/view definitions additionally use
`object-chunks-v1` and checksummed UTF-8 byte segments under `data/object-library/`.
Segments rejoin before JSON decoding, preserving characters across boundaries.
Scene collection chunks are named under `data/`, individually SHA-256 checked
and bounded to 8 MiB each. Scene and Object chunks share a 256 MiB total budget. Small
packages keep the previous inline layout; older readers refuse an unsupported
required feature. Chunk references are validated against the exact ZIP member
set before reconstructing ordinary typed records.

## Saving, recovery and migration

Saves validate the entire model and source payload, write a temporary sibling,
flush and fsync it, then publish atomically. A new destination uses no-clobber
hard-link publication. Replacing an existing file requires explicit overwrite
approval or the active file's matching digest. Previous bytes are retained at
`<name>.rigora.bak`. A backup opens as an unsaved recovery requiring Save As.
Failed saves retain the active document and do not advance its saved baseline.

Digest checks detect ordinary external changes; they are not distributed locking
against arbitrary concurrent writers. New-file publication requires filesystem
hard-link support; unsupported filesystems return a useful save error.

Version 1 migrates additively through the explicit migration registry to version
2. Migration preserves IDs and compatible optional fields, marks the document
dirty, and reports an upgrade message. Opening never modifies the original file.
Saving the upgrade writes version 2 and keeps the original version 1 backup.
Future versions or missing migration steps are rejected. Unknown optional JSON
fields survive round trips at all record levels and are deeply frozen in memory.
Nonfinite numbers and unsupported required capabilities are rejected.

## Commands, caches and workspace ownership

`DocumentService.execute()` accepts reversible validated commands. `ProjectPatch`
and `ScenePatch` retain only changed fields and share unaffected immutable
records. `CompoundCommand` reverses actions in reverse order. A service
`transaction(label)` commits as one undo entry or restores the original model
and asset-byte cache on failure. Nested transactions and lifecycle changes inside
transactions are rejected. Related entities can be inserted in one atomic scene
delta so their references validate together.

Each open tab owns a separate `DocumentService`, history, saved baseline, file
checksum, source bytes, and session UUID. Canvas view transforms are per session. The presentation also provides a
closable Welcome tab without an authoring document; it retains open sessions.
Opening an already-open path selects its tab. Save As cannot target another open
document's path. Tab and application closure resolve every dirty document.

Only canonical authoring data and source bytes enter the package. Decoded images,
evaluated poses, thumbnails, render caches, command history, and workspace layout
are derived/session data and are not serialized. Immutable saved-model baselines
avoid serialization on every dirty-state refresh. Workspace geometry, recent
paths, and theme are stored separately, normally at
`%LOCALAPPDATA%/Rigora/workspace.json`, with `RIGORA_PREFERENCES_PATH` for an explicit
override. Preference failures do not discard project work or prevent shutdown.

Sequence and layered-source descriptors are validated optional asset metadata;
their referenced image IDs must exist. Instance sequence metadata is validated
on meshes as well. Original containers and derived editable image sources survive
round trips; runtime caches do not. See [asset-pipeline.md](asset-pipeline.md) for
the sprite/layered contracts and separate versioned output JSON formats.
