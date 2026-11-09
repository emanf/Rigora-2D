# Artwork, meshes and deformation

Prompt 6 adds actual textured geometry, skinning, editable FFD/lattice fields,
weight painting and deformation keys to the existing engine and document model.
The shared geometry layer uses pinned Shapely; mask extraction uses the render
extra. GUI controls use the pinned PySide6 extra.

## Working in the editor

### Character roots and single-image rigs

Every character has a permanent **root dot** in the preview. Solid artwork and an
empty scene have no root until converted to a character. These are placement
controls rather than extra bones: dragging a dot changes where new chains start, preserving all
existing bone and artwork poses. Roots stay visible with the bone overlay hidden,
survive deleting all ordinary bones, save with the project, and support Undo.
Locked or hidden character roots do not offer placement magnets.

Use Select & transform to drag a root. Joint alignment uses the same 14-screen-pixel
tolerance as bones; hold **Alt** for free placement. Draw from a character root
to create another branch in that character's skeleton. Ctrl-click continues to
select ordinary bones. Root dots cannot be deleted.

For a character supplied as one PNG, JPEG or SVG, choose its artwork in **Bone
Editor** and leave **Auto bind artwork while drawing** checked. Drawing bones
now binds and auto-weights that image automatically. A pristine, coarse import
grid is refined once into a triangular deformation mesh. Edited topology, UVs,
protected regions, existing deformers and vertex keys prevent automatic refinement.
Each complete draw/refine/bind operation is one Undo step. Separate image rigs
keep separate skeletons; original image bytes remain embedded and unchanged.
For bones already drawn over an image, use **Bind image to bones** once.

### Soft area stretching

**Edit Mesh** opens with **Soft Drag** enabled; Custom FFD also exposes this toggle.
It brings the **Mesh / Deform** inspector forward, with **Subdivision** at the top
of the Mesh page. New artwork and drawn shapes use **Full** triangles by default;
saved meshes retain their existing topology. Full, Mask and Grid remain available
in the division selector. Mesh edges and points appear automatically while editing
and disappear when Edit Mesh is toggled off or Select is chosen. The separate
Wireframe checkbox belongs to bone editing, so mesh editing draws only one overlay.

Subdivision Density ranges from 1 to 10 in both editors. Existing saved meshes
retain their geometry until subdivision is applied again. Mask outlines reduce
pixel stair steps within 0.7 source pixels while retaining holes, thin connections
and disconnected pieces. Expand uses rounded joins to avoid long corner spikes.

Drag near the artwork's points instead of aiming at a dot. **Radius** controls the
visible influence circle in screen pixels; **Strength** controls the displacement.
**Falloff** blends between uniform movement (0%) and a smooth fade toward the edge (100%).
The default moves nearby dots most and distant dots less.
FFD/lattice/pin controls are affected when a compatible stage is selected;
otherwise this tool adjusts ordinary mesh vertices. Pinned and protected mesh
vertices stay fixed. Toggle Soft Drag off to return to direct point editing and
marquee selection.

Weights and original values are captured once per gesture. Pointer frequency
does not accumulate extra stretching. Posed meshes invert the displayed deformation
derivatives once at press, so bone rotation does not redirect the drag. Singular
folds stay fixed. A drag commits once on release, supports the existing Auto key
policy, and cancels on Escape, focus loss, tool change, or tab change.

### Spring preview

Spring Editor's **Play/Pause** runs the selected group's spring release test at
the held scene frame. **Repeat** replays the three-second test. The controls are
independent of timeline playback and looping, and create no keys or undo entries.
Pause holds the simulated pose; Play resumes it. Closing the editor, changing
groups/regions, seeking the timeline, or switching projects releases the preview.
Starting timeline playback also takes priority. **Create timeline motion test**
is a separate, explicit command for adding an editable test clip to the project.

### Existing mesh controls

1. Create a project and press **Ctrl+I** (Add assets). Choose PNG, JPEG or
   self-contained static SVG. Import embeds the original bytes in Project assets.
   Double-click the source to create a fitted artwork instance with Full irregular
   triangles. Each placement has independent transforms, geometry and deformation.
2. Press **M**, select the artwork in **Mesh / Deform**, then **Frame artwork**.
   The Mesh page selects/moves vertices, edges or triangles. Ctrl extends
   selection. Insert splits a hit face or shared edge; an outside click creates
   a loose vertex. Select three vertices and Connect triangle to make a face.
   Delete removes vertices and adjacent faces, leaving explicit holes.
3. Mesh overlay shows triangles and vertex handles. Selected coordinates, UVs
   and triangle area appear in the inspector. Pin vertices to their sampled
   base position; protect a region to prevent base movement, deletion and weight
   painting. A fully protected face also refuses insertion.
4. **Subdivision** is available directly on the Mesh page: Full, Mask or Grid,
   with Density, Alignment and Mask Expand sliders and numeric inputs. Apply
   confirms replacement of topology-dependent edits and keys, then prepares the
   result in the background with progress. Skin bindings, interpolated weights,
   appearance and original artwork survive. A tab/revision change discards stale
   results; the complete operation is one Undo step.
5. On Deform, add a preset. Use New control grid (2–8 controls per axis) for FFD
   or lattice creation. Select a stage and choose the control tool; drag handles
   and Ctrl-select multiple dots, drag a selection rectangle, or use Ctrl+A. Drag
   selected dots or inside their bounding box to move the group. Eight box handles
   resize the selected control positions around the opposite edge/corner. Unselected
   dots stay unchanged. Movement/resizing previews geometry live and commits one
   undo step, including multi-channel auto-keying. Escape or changing tools cancels
   the gesture. Stages can be disabled, reordered or removed.
   Assign an optional vertex mask to the selected vertices, or clear the mask to
   affect all vertices. **Motion** exposes the relevant numeric parameters.
6. For local pins, add a **Local pins** stage, select mesh vertices and Create
   pins from selection. Drag its square anchors with the control tool; radius
   and anchor strength are editable/animatable on Motion.
7. Create bones in the existing Rig editor. Back in Mesh / Deform → Weights,
   Bind & auto weight all bones captures the displayed bone/object matrices.
   Choose a bone, radius in scene pixels, strength and influence cap (1–16).
   Activate paint brush for add/subtract/smooth/normalize. The neutral heatmap
   runs from dark (zero) to white (one). Preview is immediate and each complete
   stroke is one undo item. Esc cancels an unfinished gesture.
8. For surface animation, sculpt the initial pose at frame 0 and click **Key mesh pose**,
   or enable **Auto key edited values**. Move the **timeline playhead** to a later frame
   before sculpting again. Earlier poses remain intact and in-between frames interpolate.
   Once that mesh has deformation keys, subsequent point/control edits record at the
   playhead even with Auto key off, including newly touched dots and axes. The timeline
   shows vertex channels together in a **Mesh deformation** row; key edits, timing and
   curve tools still operate on the underlying channels.
   On Motion, select a vertex coordinate, field-control coordinate, pin value or
   deformer parameter. Apply value changes the base parameter; Auto key writes
   the value at the displayed timeline frame instead. Explicit key frame, value
   and interpolation fields add/update/delete keys. A first key after frame 0 seeds
   the initial value automatically. Dense poses support more than 512 channels.
   Select an existing key to edit it. Step, linear and eased Bezier share the existing track sampler.
9. Exit Mesh/deformation edit mode and Rig rest mode to play normally. The same
   clip selector and Timeline scrubber evaluate all deformation and bone tracks.
   The dope sheet and graph editor use these same channels.

Drag gestures are transient until release, and input focus loss cancels them.
Tab switching retains each project's selections/mode and its independent undo
history. Navigation still uses wheel, middle-drag and Space-drag.

**Deform → New deformation example** opens an independent editable study.
Motion's example selector offers bending, a waving arm, torso FFD,
squash/stretch and a deforming prop. The same projects are in `examples/`.
Original source illustrations and CC0 notice are in `assets/examples/`.

## Evaluation contract

The order is track sampling/blending → local/world node transforms → constraints
and IK → mesh deformation stack → object world transform → texture rendering.
Vertex `x`/`y` channels sample the local base geometry. Stages are ordered by
`order`, preserving collection order on ties, and consume the previous stage's
output. The authoring mesh, UVs, source bytes and bind matrices remain unchanged.

Each stage has a stable ID, mesh/object owner, kind, enabled state, order and
JSON parameters. `intensity` is 0–10. Optional `weights` maps vertex UUIDs to
0–1 mask values; omitted vertices in an explicit mask receive zero influence.
Without a mask, every vertex receives full influence. A stage blends
`input + (solver_output - input) * intensity * mask`. Pinned vertices return to
their sampled local base positions after the complete stack. Protection affects
authoring, rather than animation/deformation evaluation.

| Kind | Solver and principal parameters |
| --- | --- |
| `ffd` | Tensor-product Bernstein displacement field; fixed `bounds`, `columns`, `rows`, row-major `controls` pairs |
| `lattice` | Piecewise bilinear displacement field with the same control contract |
| `transform` / `vertex_offset` | Local affine translation/rotation/scale/pivot; masks provide weighted offsets |
| `pin` | Vertex-UUID `pins` with local x/y/strength and optional smooth radial `radius` |
| `mesh_sculpt` | Vertex-UUID `offsets` pairs; a persistent surface shape beneath skinning/FFD |
| `skinning` | Linear blend skinning with explicit bone-world `bind_matrices` and `object_bind` |
| `bend` / `twist` | `amount` in degrees, oriented along local Y about fixed field center |
| `bulge` | Dimensionless horizontal expansion over a sine profile along local Y |
| `squash_stretch` | Local Y factor 0.05–20, reciprocal X factor to preserve area |

Field bounds are fixed when a stage is created. FFD/lattice controls store local
**displacements**, so all-zero controls are an identity even outside the field.
Normalized coordinates clamp to the field edge. FFD is smooth/global;
bilinear lattice controls are local and can have derivative discontinuities.
Skinning uses `inverse(current_object_world) * current_bone_world *
inverse(bind_bone_world) * bind_object_world`, blended by normalized vertex weights.
Unweighted vertices pass through. Rebinding explicitly captures a new bind pose.
Automatic weights use inverse squared distance to bone segments; they are an
editable starting point rather than a character-aware solution.

Unknown or invalid stages warn and retain their input geometry atomically. This
includes singular skin bindings, invalid grids and nonfinite results. Runtime
deformation may fold or overlap intentionally; base topology edits reject collapsed,
inverted, overlapping, duplicate and nonmanifold triangles. Deleting vertices
also removes their pin/mask references and associated mesh animation tracks.
An unkeyed viewport sculpt that folds base triangles is stored in a **Mesh shape**
displacement stage instead. Its rest topology and UVs remain valid, while the
committed surface matches the live preview. Further sculpting accumulates deltas;
Undo, project save/load and reusable motion retain the shape.

ScenePose includes immutable MeshPose snapshots with local positions, UVs,
indexed triangles, source/owner IDs and warnings. The headless `--evaluate`
command includes those meshes in its JSON without importing Qt.

## Services and extension points

`MeshService` imports and edits geometry. `SkinService` binds and the pure
`weight_brush` function normalizes bounded influences. `DeformationService`
edits stages, controls, masks and pins. `DeformationMotionService` edits the same
Track/Keyframe/Timeline/AnimationClip records used by ordinary playback.

`DeformationPreset(name, kind, parameters)` is a data-only preset interface.
Python callers can supply additional presets and inject typed solver callables
through `DocumentService(deformer_solvers=...)`. Each solver receives immutable
local points, authoring mesh, deeply frozen parameters and evaluated nodes, and
must return the same vertex count with finite coordinates. Registries are owned
per document. Loading project data never imports or executes a plugin; the
manifest-based public plugin SDK remains Prompt 9.

## Reusable clips

Export writes a `.rigmotion` bundle for one geometric stage and its mesh vertex
tracks on the selected clip. Reuse creates a new stage, timeline and clip, remaps
UUIDs and selects the new clip. Existing stages and clips are preserved. Disable
an original stage when testing an imported copy on the same mesh, or their
effects compose. Bone skin bindings and bone motion are project-specific and
are excluded from this geometric clip format.

Version 1 motion bundles are bounded to 4 MiB of unambiguous UTF-8 JSON. They
require matching vertex counts, triangle topology and vertex ordering. Spatial
control offsets, vertex coordinates, pins, pivots and translation adapt to target
mesh bounds. Frames/tangent times rescale by target FPS / source FPS, preserving
duration. Radius uses the smaller axis ratio. Arbitrary shape correspondence,
silhouette retargeting and bone retargeting are not implied. Export refuses
overwrite without explicit consent and publishes through a flushed temporary file.

## Image and algorithm limits

- Sources: at most 32 MiB, 8192 pixels per axis and 16,777,216 pixels. GUI import
  fully decodes before mutation, using two background workers. A changed project
  cancels a pending import; errors preserve the document. Core import checks
  container metadata and SVG safety without depending on a pixel decoder.
- SVG: UTF-8 static Qt SVG subset. Scripts, animation, entities/document types,
  embedded raster images, external resources and event handlers are rejected;
  the element limit is 100,000. SVG paths remain source art, not editable paths.
  Unsupported Qt SVG effects may render differently; layered PSD/SVG, EXIF
  orientation, GIF/APNG playback and color-management pipelines are future work.
- Rendering: SVG artwork uses the original `QSvgRenderer` vectors through each
  evaluated mesh triangle, keeping curves and fine strokes sharp at the current
  zoom. SVG display does not deform a bitmap thumbnail. Hard shared-edge clip
  coverage prevents seams and double blending for translucent artwork. The warp
  follows the mesh's piecewise-affine geometry, so mesh density controls geometric
  approximation of nonlinear fields. This renders source paths; it does not rewrite
  SVG path data or add an SVG export pipeline. Original SVG bytes remain embedded.
  Raster sources and thumbnails use QImages up to 2048 pixels per axis, adapting
  to a shared 128 MiB pixel budget; parsed vectors are retained for the active
  project. Rendering is CPU based. Unsupported Qt SVG effects remain unsupported.
- Bone Editor and Edit Mesh support Full irregular triangles, alpha-boundary Mask triangulation
  and the established Grid. Density, Alignment, Expand and all-artwork subdivision
  are available. Skin bindings and interpolated weights survive regeneration;
  topology-dependent edits/keys require confirmation. See
  [the investigation and algorithms](mesh-and-spring-design.md) for limits and evidence.
  Manual insertion/deletion/face connection works for planar triangle meshes;
  there is no hole-filling, general remeshing, edge-flip tool or automatic repair.
  Geometry checks use absolute floating-point tolerances suitable for pixel units.
- Field-control editing uses each field's local coordinates. Surface point drags,
  resize handles and Soft Drag invert displayed derivatives once at press to
  follow the pointer through skinning and other fields. Singular folds stay fixed.
  Fields compose in their declared order;
  changing order deliberately changes results. Lattice resolution is chosen on
  creation; add a replacement stage to change it without silently remapping keys.
- Evaluation is stateless and CPU based. Dense grids, many influences, stacked
  fields and large brushes cost more. Run `tools/benchmark_deformation.py` for
  repeatable engine measurements; production-scale GPU performance is not claimed.

Qt API references used for the presentation adapter:
[QSvgRenderer](https://doc.qt.io/qt-6/qsvgrenderer.html),
[QImage](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QImage.html),
[QPainter](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QPainter.html) and
[QTransform](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QTransform.html).
