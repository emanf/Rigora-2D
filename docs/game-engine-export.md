# Game engine exports

The format menu offers baked sprites and editable planar rigs for each engine,
plus a native Godot 2D scene package. Choose the mode to match the game. Exporting
does not modify the original animation or history. **Check export** inspects all
requested samples/sources on a cancellable worker and reports explicit adapter
limits. Queueing also checks settings and capabilities before publication.

Choose **File → Render & export… → Godot 4 / Unity / Unreal Engine 5**. Select the
clip/action, frame range, FPS and transparent resolution, then queue a `.zip`.
Packages contain PNG frames, `atlas.png`, ordered `animation.json`, native
resources or an editor importer, and README instructions.

Animations are baked. Bones, deformation controls, replaceable clothing and audio
are not engine runtime data. Export each action separately and retain the editable
`.rigora` source. Atlas sides must fit within 8192 pixels; existing render budgets
still apply. Every engine uses a bottom-center pivot.

## Godot 4

Extract and open `project.godot` to preview. For an existing project, copy the
folder into it and instantiate `animation.tscn`. It contains AnimatedSprite2D,
editable SpriteFrames, AtlasTexture rectangles and the exported loop/FPS settings.
Keep `atlas.png` beside the scene. Native loading was checked in Godot 4.7.2.
See [Godot SpriteFrames](https://docs.godotengine.org/en/stable/classes/class_spriteframes.html).

## Unity

Extract under `Assets`; let the included Editor script compile. Use **Tools →
Rigora → Import sprite animation** and choose that folder. It creates native
AnimationClip, AnimatorController and SpriteRenderer/Animator prefab assets in a
fresh Generated folder, retaining previous imports. Sprites use uncompressed
textures and 100 pixels/unit. Compilation, keys, exact duration, pivot and prefab
creation were checked in Unity 6000.6.4f1. The adapter uses standard Unity
2022.3/6 editor APIs.
See [Unity animation curves](https://docs.unity.com/en-us/engine/6000.7/script-reference/unityengine/animationclip).

## Unreal Engine 5

Enable **Paper 2D**, **Python Editor Script Plugin** and **Editor Scripting
Utilities**. Extract the ZIP and run `import_rigora.py` using **Tools → Execute
Python Script**. It imports textures, creates PaperSprites and an ordered
PaperFlipbook under `/Game/Rigora/<name>`. Existing destination folders are
rejected. Place the flipbook in the scene; set the component's Looping property
to the exported preference. Flipbook assets do not store a loop flag. Scale is
100 pixels per Unreal unit.

The adapter follows Epic's documented editor APIs. No Unreal installation was
available for native execution; syntax/package contents were checked. Verify
sprite geometry/material in your target version before production use.
See [PaperSprite](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PaperSprite?application_version=5.6)
and [PaperFlipbook](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PaperFlipbook?application_version=5.6).

Python/CLI/MCP use the same `frame_render`/`render_submit` operations with explicit
`format="godot"`, `"unity"` or `"unreal"` and a `.zip` destination.

## Editable rigs, clothing and colors

Choose **Godot · editable rig + clothing**, **Unity · editable rig + clothing**
or **Unreal · editable glTF rig**. The shared operation format IDs are
`godot-rig`, `unity-rig`, `unreal-rig`. Export each action separately. Sampled
frames play sequentially at the chosen output FPS, including one final hold.
These are flat textured meshes in a 3D XY plane, with 100 pixels per unit and
Y pointing up. Use an orthographic camera for a 2D game. They do not create
engine-native Skeleton2D/Bone2D resources.

Every ZIP contains `character.glb` with actual bones, hierarchy, skin weights,
separate mesh parts, materials, native bone animation and morph corrections.
`rig.json` retains wardrobe IDs, variants, body-part coverage, per-frame
visibility/opacity, part labels and animation samples. Original SVG/image bytes,
portable PNG textures and `source-project.json` retain the authored source.
Changing a garment's runtime tint affects that part independently.

Constraints and nonlinear FFD are sampled into native bone/morph animation;
their original editable definitions survive in the source project rather than
becoming engine constraint solvers. Up to four influences per vertex are
supported. Animated artwork-source/palette changes retain separate PNG revisions
and per-frame texture paths applied by the wrappers. The larger Width/Height value limits
each texture's longest edge (up to 4096); it does not crop the geometry. Vector
textures render directly from the original SVG, up to four times source size.
The package is bounded to 600 frames, one million sampled vertices and 128 MiB
of decoded files. Reduce the sample range for dense meshes.

**Godot:** open `project.godot` and run the fitted preview. Copy the folder into
an existing project and instantiate `rig.tscn` for a reusable rig without a camera.
The child glTF scene provides native Skeleton3D, skinned MeshInstance3D and
AnimationPlayer resources. The `RigoraRig.gd` wrapper exposes
`set_clothing(group_id, variant_id)`, `set_part_color(part_name, Color(...))`
and `seek(seconds)`. Its `playing` property controls the wrapper clock and
`event_fired(Dictionary)` delivers typed events; seeking never emits them. An
empty clothing variant removes that category and restores covered skin.
Set `playing=false` before manually posing bones.

**Unity:** extract under `Assets`, wait for compilation, then choose **Tools →
Rigora → Import editable rig**. It creates native Transform bones, weighted Mesh
assets, SkinnedMeshRenderer parts, AnimationClip curves/blend shapes, materials
and a prefab in a fresh GeneratedRig folder. No third-party glTF package is
required. The prefab's `RigoraRig` exposes `SetClothing`, `SetPartColor` and `Seek`.
`EventFired` delivers typed events with a JSON payload string. Imported alternate
textures are serialized with the prefab. Changing clothing or seeking does not
dispatch events. `Advance(deltaSeconds)` supports a caller-owned forward clock;
stop Animation before using it. The prefab's `RigoraScenePlayback` renders sampled
camera cuts, affine camera motion, background/lens images and batched particles
in source layer order. Disable `useSceneCamera` to use the game's own camera;
the exported camera/overlays turn off while particles remain visible. Main-scene
exports enable this option; Object Editor exports disable it initially.
Native Unity 6000.6.4f1 checks pass for weighted vertices, wardrobe, colors,
animated textures, typed callbacks, affine camera cuts, overlays, particle scale,
camera opt-out and instance resource cleanup. A hidden batch GPU render also
matches canonical pixels at 256 × 144 (mean RGB error below 0.18/255 and exact
alpha for the opaque background/transparent-overlays fixture).
The supplied unlit shader is for the built-in renderer; replace materials for
URP/HDRP. Stop Animation before manually posing bones.

**Unreal:** enable Interchange glTF import and Python Editor Script Plugin, then
run `import_editable_rig.py`. Import bones, weights, animations and morph targets
through the native options and retain separate clothing meshes. For Blueprint
controls, copy the included `RigoraRuntime` plugin into a C++ project's `Plugins`
folder, build it with the Unreal toolchain, and restart before importing. Assign
the resulting definition asset to a RigoraWardrobeComponent. It exposes clothing,
part colors and seeking; bind meshes by name or explicitly using `BindPart`.
The included ENGINE.txt explains material parameters and single-node animation
setup. **Unreal compilation/runtime execution is unverified** in this environment.
The importer also loads alternate textures into the definition asset. Set the
component's texture parameter to the imported material's actual base-color sampler.
Blueprint `OnAnimationEvent` carries ID/name/type/JSON payload/target. Seeking
does not emit it. Typed payloads never execute automatically.

With **Include clip audio** enabled, editable packages retain `voice.wav` and its
offset/gain/mute settings. Godot and Unity wrappers synchronize the source during
native playback. Unreal carries source/timing metadata for manual audio setup.
See [editable-rig validation](validation-editable-rig.md) for native editor checks
and remaining limits.

## Native Godot 2D scene

Choose **Godot 4 · native 2D rig + scene playback**, format ID `godot-2d`.
Extract and open `project.godot`, or copy its folder into a project and instance
`rig.tscn`. Its authored Skeleton2D, Bone2D/Node2D hierarchy and independent
Polygon2D artwork exist in the local editor scene tree before scripts run.
The runtime skins vertices against current native bones and applies
sampled FFD corrections, artwork/skin changes, wardrobe coverage, opacity and
draw order. The alternative GLB and original project/artwork remain included.

The scene supports evaluated camera cuts/motion/follow/paths/transitions,
backgrounds, lens overlays and seeded vector particles. Camera projection keeps
the frame's aspect ratio. A private CanvasLayer carries the exported camera;
the runtime does not replace the whole game viewport's canvas transform. Disable
**Use scene camera** when placing a character under the game's Camera2D; the
armature then joins the parent's normal game canvas.
Lens/background images derive from the same original-vector final renderer.

Use `playing`, `seek(seconds)`, `set_clothing`, `set_part_color` and
`event_fired(Dictionary)`. For manual bone poses, set `playing=false` and call
`refresh_pose()` after editing bones. `get_regions()` returns source-pixel
polygons/activation; game code decides collider and damage behavior. Constraints
and spring physics remain sampled rather than native solvers.

Current tests execute both Godot package types headlessly in official Godot
4.7.2. They compare native 2D deformed vertices with canonical evaluation and
check texture switching, particles/regions, camera overlays, callback delivery
and non-executing seeks. Unity has separate native Editor and rendered-pixel checks;
Unreal compilation/runtime remains unverified without an installed engine/SDK.

`source-project.json` records the authored model metadata. Keep the original
`.rigora` document for a complete multi-scene project and all unused/audio sources;
the engine ZIP retains original artwork used by its exported scope, not a full
project backup.

## Capability differences

| Data | Baked sprite packages | Godot native 2D / Unity rigs | Planar Godot / Unreal rigs |
| --- | --- | --- | --- |
| Artwork/camera/lens/particles | Rendered pixels | Separate parts and scene playback | Artwork playback; camera metadata only |
| Editable bones/weights/FFD | Original source project | Native bones, sampled corrections | Native bones, sampled corrections |
| Clothing/skin changes | Baked appearance | Runtime wardrobe/texture switching | Runtime wardrobe/texture switching |
| Game events/regions | Manifest data | Callback and region data | Callback and region metadata |
| Unsupported scene camera/particles | Preserved by rendering | Supported | Explicit preflight error; use a supported route |

Each package exports one action/range. Event seconds map through the actual
output samples, including sparse retiming. Audio requires consecutive samples
at the selected FPS; disable audio for retimed poses. Reverse segments emit
crossed events in reverse source order; held samples do not repeat events.
An event at the initial sample is emitted once at zero seconds. Expanded event
occurrences are bounded to 4096 per export.
