"""Editable planar glTF skins and engine packages from canonical evaluated scene data."""

import io
import json
import math
import struct
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any, cast

from rigora.application_services.audio import AudioService
from rigora.application_services.documents import DocumentService
from rigora.application_services.export_metadata import exported_events
from rigora.domain.geometry import Matrix, decompose, inverse, multiply, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.state import ScenePose
from rigora.engine.vector_appearance import styled_artwork
from rigora.infrastructure.artwork import inspect_artwork
from rigora.infrastructure.media_import import pillow_image, png_bytes
from rigora.resources import asset_path

RIG_FORMATS = ("godot-rig", "godot-2d", "unity-rig", "unreal-rig")
IDENTITY: Matrix = (1, 0, 0, 1, 0, 0)
MAX_BYTES = 128 * 1024 * 1024
MAX_PARTICLE_SAMPLES = 250_000


def converted(matrix: Matrix) -> Matrix:
    """Convert screen pixels to a right-handed XY plane with 100 pixels per unit."""
    a, b, c, d, x, y = matrix
    return a, -b, -c, d, x / 100, -y / 100


def matrix4(matrix: Matrix) -> list[float]:
    """Expand a planar affine matrix into glTF column-major storage."""
    a, b, c, d, x, y = matrix
    return [a, b, 0, 0, c, d, 0, 0, 0, 0, 1, 0, x, y, 0, 1]


def trs(matrix: Matrix) -> dict[str, list[float]]:
    """Recover exact local TRS, rejecting shear rather than discarding it."""
    x, y, rotation, sx, sy = decompose(converted(matrix))[:5]
    half = math.radians(rotation) / 2
    return {
        "translation": [x, y, 0],
        "rotation": [0, 0, math.sin(half), math.cos(half)],
        "scale": [sx, sy, 1],
    }


class GltfBuffer:
    """Own aligned binary storage and typed accessor metadata for a single glTF document."""

    def __init__(self, gltf: dict[str, Any]) -> None:
        """Share the document's accessor/view arrays while owning only its binary bytes."""
        self.gltf, self.data = gltf, bytearray()

    def view(self, data: bytes) -> int:
        """Append one four-byte-aligned region and return its bufferView index."""
        self.data.extend(b"\0" * (-len(self.data) % 4))
        offset = len(self.data)
        self.data.extend(data)
        if len(self.data) > MAX_BYTES:
            raise ProjectError("Editable rig geometry/textures exceed the 128 MiB budget.")
        views = self.gltf["bufferViews"]
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data)})
        return len(views) - 1

    def accessor(
        self,
        values: Sequence[Sequence[float]],
        kind: str,
        component: int = 5126,
        *,
        bounds: bool = False,
    ) -> int:
        """Write finite float or unsigned integer rows with explicit glTF element widths."""
        flat = [value for row in values for value in row]
        if not flat or any(not math.isfinite(value) for value in flat):
            raise ProjectError("Editable rig accessors require finite nonempty geometry.")
        code = {5126: "f", 5123: "H", 5125: "I"}[component]
        view = self.view(struct.pack("<" + code * len(flat), *flat))
        entry: dict[str, Any] = {
            "bufferView": view,
            "componentType": component,
            "count": len(values),
            "type": kind,
        }
        if bounds:
            entry.update(
                min=[min(row[i] for row in values) for i in range(len(values[0]))],
                max=[max(row[i] for row in values) for i in range(len(values[0]))],
            )
        self.gltf["accessors"].append(entry)
        return len(self.gltf["accessors"]) - 1

    def glb(self) -> bytes:
        """Serialize a standards-based binary glTF with embedded images and aligned chunks."""
        self.gltf["buffers"] = [{"byteLength": len(self.data)}]
        encoded = json.dumps(self.gltf, allow_nan=False, separators=(",", ":")).encode()
        encoded += b" " * (-len(encoded) % 4)
        binary = bytes(self.data) + b"\0" * (-len(self.data) % 4)
        return (
            struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
            + struct.pack("<I4s", len(encoded), b"JSON")
            + encoded
            + struct.pack("<I4s", len(binary), b"BIN\0")
            + binary
        )


def rig_package(
    document: DocumentService,
    engine: str,
    frames: tuple[float, ...],
    *,
    fps: float,
    loop: bool,
    texture_limit: int,
    check: Callable[[], None],
    report: Callable[[int], None],
    include_audio: bool = True,
) -> tuple[bytes, list[str]]:
    """Export editable bones/weights plus sampled deformation, wardrobe and visibility data.

    Geometry is a planar skinned mesh, not a rendered sprite. Original source artwork
    remains in the package; portable PNG textures are derived directly from it.
    Constraints are sampled into bone TRS. Mesh corrections are native morph targets.
    """
    if document.project is None or engine not in RIG_FORMATS:
        raise ProjectError("Choose an open project and an editable engine rig format.")
    poses = []
    particle_samples = 0
    for i, frame in enumerate(frames):
        check()
        pose = document.animation.evaluate(frame)
        particle_samples += sum(len(parts) for parts in pose.particles.values())
        if particle_samples > MAX_PARTICLE_SAMPLES:
            raise ProjectError("Editable scene export exceeds 250,000 particle samples.")
        if i == 0 and sum(len(m.positions) for m in pose.meshes.values()) * len(frames) > 1_000_000:
            raise ProjectError(
                "Editable rig export exceeds one million sampled vertices. "
                "Reduce the frame count or simplify the meshes."
            )
        warnings = [*pose.warnings, *(w for m in pose.meshes.values() for w in m.warnings)]
        if warnings:
            raise ProjectError("Cannot export incomplete rig evaluation: " + "; ".join(warnings))
        poses.append(pose)
        report(i + 1)
    if not poses[0].meshes:
        raise ProjectError("Editable game export needs mesh artwork in the active animation scope.")
    gltf, runtime, files = build_rig(document, poses, fps, loop, texture_limit, check)
    from rigora.application_services.scene_export import scene_samples

    runtime["scene_samples"] = scene_samples(
        document, poses, texture_limit, files, check, overlays=engine in ("godot-2d", "unity-rig")
    )
    runtime["use_scene_camera"] = document.animation_scope is None
    audio = AudioService(document).position(frames[0]) if include_audio else None
    if audio:
        service = AudioService(document)
        if service.clip and "audio_tracks" in service.clip.extra:
            from rigora.engine.audio_mix import write_mix

            mixed = io.BytesIO()
            write_mix(
                mixed,
                tuple((t, document.read_asset(t["asset_id"])) for t in service.tracks()),
                start=frames[0],
                duration=len(frames) / fps,
                fps=document.scene.settings.fps,
                cancelled=check,
            )
            files["voice.wav"] = mixed.getvalue()
            audio = replace(audio, seconds=0, duration=len(frames) / fps, gain=1, muted=False)
        else:
            files["voice.wav"] = document.read_asset(audio.asset_id)
        runtime["audio"] = {
            "path": "voice.wav",
            "offset": audio.seconds,
            "duration": audio.duration,
            "gain": audio.gain,
            "muted": audio.muted,
        }
    files["character.glb"] = gltf
    files["rig.json"] = json.dumps(runtime, separators=(",", ":"), allow_nan=False).encode()
    files["source-project.json"] = json.dumps(
        document.project.to_dict(), separators=(",", ":")
    ).encode()
    files["README.txt"] = (
        b"Editable planar rig: 100 pixels per unit, XY plane, separate skinned image parts.\n"
        b"character.glb contains bones, weights, meshes and sampled animation/morph targets.\n"
        b"rig.json retains wardrobe membership, visibility, opacity and editable runtime data.\n"
        b"Textures are derived from original vectors at the selected resolution limit; originals "
        b"and authored project metadata are retained. "
        b"Constraints are sampled, not engine solvers.\n"
        b"Keep every package file together. See the included engine instructions.\n"
    )
    add_engine_files(files, engine)
    if engine == "godot-2d":
        from rigora.application_services.godot_scene import native_scene

        files["rig.tscn"] = native_scene(runtime, files)
    if sum(map(len, files.values())) > MAX_BYTES:
        raise ProjectError("Editable rig package exceeds the 128 MiB decoded file budget.")
    check()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in files.items():
            check()
            archive.writestr(path, data)
    return output.getvalue(), [
        "Editable planar meshes use PNG textures; original vectors are included. "
        "Constraints/FFD are sampled into bone and morph animation."
    ]


def build_rig(
    document: DocumentService,
    poses: list[ScenePose],
    fps: float,
    loop: bool,
    texture_limit: int,
    check: Callable[[], None],
) -> tuple[bytes, dict[str, Any], dict[str, bytes]]:
    """Assemble native glTF accessors and a matching engine-friendly authoring manifest."""
    assert document.project is not None
    scene, first = document.scene, poses[0]
    files: dict[str, bytes] = {}
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "Rigora 2D"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "skins": [],
        "materials": [],
        "textures": [],
        "images": [],
        "accessors": [],
        "bufferViews": [],
        "extensionsUsed": ["KHR_materials_unlit"],
        "animations": [],
        "samplers": [{"magFilter": 9729, "minFilter": 9729, "wrapS": 33071, "wrapT": 33071}],
    }
    buffer = GltfBuffer(gltf)
    ids = {key: i for i, key in enumerate(first.nodes)}
    bone_roots = {
        b.id: rig.extra.get("object_id")
        for rig in scene.skeletons
        for b in rig.bones
        if b.parent_id is None
    }
    parents = {key: node.parent_id or bone_roots.get(key) for key, node in first.nodes.items()}
    samples: list[list[dict[str, list[float]]]] = []
    followers = {c.owner_id for c in scene.constraints if c.kind == "scene_attachment"}
    for pose in poses:
        values = []
        for key, node in pose.nodes.items():
            sample_local = node.local_matrix
            if key in followers:
                sample_parent = pose.nodes.get(node.parent_id or "")
                sample_local = (
                    multiply(inverse(sample_parent.world_matrix), node.world_matrix)
                    if sample_parent
                    else node.world_matrix
                )
            values.append(trs(sample_local))
        samples.append(values)
    for key, node in first.nodes.items():
        record = {
            "name": f"rigora_{node.kind}_{key.replace('-', '')}",
            **samples[0][ids[key]],
            "extras": {"rigora_id": key, "name": node.name, "kind": node.kind},
        }
        gltf["nodes"].append(record)
    for key, parent in parents.items():
        if parent in ids:
            gltf["nodes"][ids[parent]].setdefault("children", []).append(ids[key])
        else:
            gltf["scenes"][0]["nodes"].append(ids[key])
    runtime: dict[str, Any] = {
        "format": "rigora.editable-rig",
        "version": 1,
        "fps": fps,
        "canvas": scene.settings.to_dict(),
        "loop": loop,
        "duration": len(poses) / fps,
        "nodes": [],
        "parts": [],
        "wardrobes": [],
        "times": [i / fps for i in range(len(poses) + 1)],
        "events": exported_events(document, [p.requested_frame for p in poses], fps),
    }
    from rigora.engine.game_regions import game_regions

    runtime["regions"] = (
        [
            {"seconds": i / fps, "regions": game_regions(document.scene, pose)}
            for i, pose in enumerate(poses)
        ]
        if any(o.extra.get("game_region") for o in document.scene.objects)
        else []
    )
    runtime["region_coordinates"] = "source scene pixels, x right and y down"
    for key, node in first.nodes.items():
        runtime["nodes"].append(
            {
                "id": key,
                "name": gltf["nodes"][ids[key]]["name"],
                "label": node.name,
                "parent": ids.get(parents[key] or "", -1),
                "kind": node.kind,
                "samples": [s[ids[key]] for s in samples],
            }
        )
    times = runtime["times"]
    time_accessor = buffer.accessor([[t] for t in times], "SCALAR", bounds=True)
    animation: dict[str, Any] = {
        "name": document.animation.evaluator.clip.name
        if document.animation.evaluator.clip
        else "Animation",
        "channels": [],
        "samplers": [],
    }

    def channel(node: int, path: str, values: list[list[float]], kind: str) -> None:
        """Append a linear native animation channel, retaining the final frame hold."""
        if all(row == values[0] for row in values):
            return
        output = buffer.accessor([*values, values[-1]], kind)
        sampler = len(animation["samplers"])
        animation["samplers"].append(
            {"input": time_accessor, "output": output, "interpolation": "LINEAR"}
        )
        animation["channels"].append({"sampler": sampler, "target": {"node": node, "path": path}})

    for key in first.nodes:
        for path, kind in (("translation", "VEC3"), ("rotation", "VEC4"), ("scale", "VEC3")):
            channel(ids[key], path, [s[ids[key]][path] for s in samples], kind)
    objects = {o.id: o for o in scene.objects}
    source_meshes = {m.id: m for m in scene.meshes}
    mesh_nodes = {}
    weight_accessor: int | None = None
    render_order = {key: index for index, key in enumerate(first.render_order)}
    ordered_meshes = sorted(
        first.meshes.items(), key=lambda item: render_order.get(item[1].object_id or "", 0)
    )
    for order, (key, mesh) in enumerate(ordered_meshes):
        check()
        source = source_meshes[key]
        if not mesh.asset_id or not mesh.object_id or not mesh.positions:
            raise ProjectError("Editable export needs textured meshes attached to artwork objects.")
        if any(len(vertex.weights) > 4 for vertex in source.vertices):
            raise ProjectError(
                "Editable game skins support at most four bone influences per vertex."
            )
        versions: dict[str, str] = {}
        texture_states = []
        for pose in poses:
            check()
            sampled = pose.meshes[key]
            signature = json.dumps(
                [sampled.asset_id, dict(sampled.appearance)], sort_keys=True, default=dict
            )
            if signature not in versions:
                if not sampled.asset_id:
                    raise ProjectError("Animated artwork requires a valid source asset.")
                data = document.read_asset(sampled.asset_id)
                extension = {
                    "image/svg+xml": "svg",
                    "image/png": "png",
                    "image/jpeg": "jpg",
                    "image/webp": "webp",
                    "image/bmp": "bmp",
                    "image/tiff": "tiff",
                    "image/gif": "gif",
                }.get(inspect_artwork(data).media_type, "image")
                files[f"sources/{sampled.asset_id}.{extension}"] = data
                path = f"textures/{key}-{len(versions)}.png"
                files[path] = texture(data, sampled.appearance, texture_limit)
                versions[signature] = path
                if sum(map(len, files.values())) > MAX_BYTES:
                    raise ProjectError("Animated artwork exceeds the 128 MiB rig file budget.")
            texture_states.append(versions[signature])
        texture_path = texture_states[0]
        image = files[texture_path]
        image_index = len(gltf["images"])
        gltf["images"].append({"bufferView": buffer.view(image), "mimeType": "image/png"})
        gltf["textures"].append({"source": image_index, "sampler": 0})
        gltf["materials"].append(
            {
                "name": objects[mesh.object_id].name,
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": image_index},
                    "metallicFactor": 0,
                    "roughnessFactor": 1,
                },
                "alphaMode": "BLEND",
                "doubleSided": True,
                "extensions": {"KHR_materials_unlit": {}},
            }
        )
        joints = list(dict.fromkeys(bone for v in source.vertices for bone in v.weights))
        if any(not v.weights for v in source.vertices):
            joints.append(mesh.object_id)
        joints = list(dict.fromkeys(joints))
        bind_world = {joint: joint_world(first, joint, scene) for joint in joints}
        bind_inverse = {joint: inverse(world) for joint, world in bind_world.items()}
        skin_index = len(gltf["skins"])
        gltf["skins"].append(
            {
                "joints": [ids[j] for j in joints],
                "inverseBindMatrices": buffer.accessor(
                    [matrix4(converted(bind_inverse[j])) for j in joints], "MAT4"
                ),
            }
        )
        base = [
            transform_point(first.nodes[mesh.object_id].world_matrix, *point)
            for point in mesh.positions
        ]
        positions = [[x / 100, -y / 100, order * 0.0001] for x, y in base]
        vertex_joints, vertex_weights = [], []
        for vertex in source.vertices:
            weights = list(vertex.weights.items()) or [(mesh.object_id, 1.0)]
            vertex_joints.append([joints.index(j) for j, _ in weights] + [0] * (4 - len(weights)))
            vertex_weights.append([float(w) for _, w in weights] + [0.0] * (4 - len(weights)))
        attributes = {
            "POSITION": buffer.accessor(positions, "VEC3", bounds=True),
            "NORMAL": buffer.accessor([[0, 0, 1]] * len(base), "VEC3"),
            "TEXCOORD_0": buffer.accessor(mesh.uv, "VEC2"),
            "JOINTS_0": buffer.accessor(vertex_joints, "VEC4", 5123),
            "WEIGHTS_0": buffer.accessor(vertex_weights, "VEC4"),
        }
        triangles = [[i] for face in mesh.triangles for i in (face[0], face[2], face[1])]
        primitive: dict[str, Any] = {
            "attributes": attributes,
            "material": image_index,
            "indices": buffer.accessor(triangles, "SCALAR", 5125),
        }
        corrections = []
        for pose in poses:
            check()
            matrices = {j: multiply(joint_world(pose, j, scene), bind_inverse[j]) for j in joints}
            world = pose.nodes[mesh.object_id].world_matrix
            offsets = []
            for i, vertex in enumerate(source.vertices):
                influences = vertex.weights or {mesh.object_id: 1.0}
                blended = cast(
                    Matrix,
                    tuple(
                        sum(matrices[j][axis] * w for j, w in influences.items())
                        for axis in range(6)
                    ),
                )
                expected = transform_point(world, *pose.meshes[key].positions[i])
                if math.dist(transform_point(blended, *base[i]), expected) < 1e-6:
                    offsets.append([0.0, 0.0, 0.0])
                else:
                    local = transform_point(inverse(blended), *expected)
                    offsets.append(
                        [(local[0] - base[i][0]) / 100, -(local[1] - base[i][1]) / 100, 0.0]
                    )
            corrections.append(offsets)
        morphs = any(
            any(any(abs(c) > 1e-8 for c in row) for row in sample) for sample in corrections
        )
        if morphs:
            primitive["targets"] = [
                {"POSITION": buffer.accessor(offsets, "VEC3", bounds=True)}
                for offsets in corrections
            ]
        mesh_index, node_index = len(gltf["meshes"]), len(gltf["nodes"])
        name = f"rigora_part_{key.replace('-', '')}"
        record = {"name": name, "primitives": [primitive]}
        if morphs:
            record.update(
                weights=[1.0] + [0.0] * (len(poses) - 1),
                extras={"targetNames": [f"sample_{i}" for i in range(len(poses))]},
            )
        gltf["meshes"].append(record)
        gltf["nodes"].append(
            {
                "name": name,
                "mesh": mesh_index,
                "skin": skin_index,
                "extras": {"rigora_id": key, "source_object": mesh.object_id},
            }
        )
        gltf["scenes"][0]["nodes"].append(node_index)
        mesh_nodes[key] = name
        if morphs:
            if weight_accessor is None:
                weight_accessor = buffer.accessor(
                    [
                        [float(i == min(f, len(poses) - 1))]
                        for f in range(len(poses) + 1)
                        for i in range(len(poses))
                    ],
                    "SCALAR",
                )
            sampler = len(animation["samplers"])
            animation["samplers"].append(
                {"input": time_accessor, "output": weight_accessor, "interpolation": "LINEAR"}
            )
            animation["channels"].append(
                {"sampler": sampler, "target": {"node": node_index, "path": "weights"}}
            )
        runtime["parts"].append(
            {
                "id": key,
                "node": name,
                "object_id": mesh.object_id,
                "label": objects[mesh.object_id].name,
                "texture": texture_path,
                "texture_states": texture_states,
                "positions": [dict(zip(("x", "y", "z"), p, strict=True)) for p in positions],
                "uv": [{"x": u, "y": v} for u, v in mesh.uv],
                "triangles": [v[0] for v in triangles],
                "joints": [ids[j] for j in joints],
                "bindposes": [{"values": matrix4(converted(bind_inverse[j]))} for j in joints],
                "weights": [
                    {"indices": j, "values": w}
                    for j, w in zip(vertex_joints, vertex_weights, strict=True)
                ],
                "corrections": [
                    {"vertices": [dict(zip(("x", "y", "z"), p, strict=True)) for p in offsets]}
                    for offsets in corrections
                ]
                if morphs
                else [],
                "states": [
                    {
                        "visible": p.nodes[mesh.object_id].visible,
                        "opacity": p.nodes[mesh.object_id].opacity,
                    }
                    for p in poses
                ],
            }
        )
    if animation["channels"]:
        gltf["animations"].append(animation)
    runtime["clip"] = animation["name"]
    for owner in (*scene.groups, *scene.characters, *scene.objects):
        for group in owner.extra.get("outfits", ()):
            variants = [
                {
                    "id": v["id"],
                    "name": v["name"],
                    "parts": [mesh_nodes[k] for k in v["meshes"] if k in mesh_nodes],
                    "occludes": [mesh_nodes[k] for k in v.get("occludes", ()) if k in mesh_nodes],
                }
                for v in group["variants"]
            ]
            if any(v["parts"] for v in variants):
                runtime["wardrobes"].append(
                    {
                        "owner": owner.id,
                        "id": group["id"],
                        "name": group["name"],
                        "variants": variants,
                        "selected": group.get("selected", group.get("default")),
                    }
                )
    gltf["extras"] = {
        "rigora": {"coordinates": "XY planar, +Y up, 100 pixels/unit", "runtime": "rig.json"}
    }
    return buffer.glb(), runtime, files


def joint_world(pose: ScenePose, key: str, scene: Any) -> Matrix:
    """Move skeleton joints with their owning stage object while retaining native hierarchy."""
    node = pose.nodes[key]
    if node.kind == "bone":
        rig = next((rig for rig in scene.skeletons if any(b.id == key for b in rig.bones)), None)
        root = rig.extra.get("object_id") if rig else None
        if isinstance(root, str) and root in pose.nodes:
            return multiply(pose.nodes[root].world_matrix, node.world_matrix)
    return node.world_matrix


def texture(data: bytes, appearance: Any, limit: int) -> bytes:
    """Render original styled vectors directly to a bounded portable texture."""
    source = styled_artwork(data, appearance)
    info = inspect_artwork(source)
    if info.kind == "vector":
        import resvg_py

        scale = min(4, limit / max(info.width, info.height))
        source = resvg_py.svg_to_bytes(
            svg_string=source.decode(),
            skip_system_fonts=True,
            width=max(1, round(info.width * scale)),
            height=max(1, round(info.height * scale)),
        )
    image = pillow_image(source)
    if max(image.size) > limit:
        from PIL import Image

        image.thumbnail((limit, limit), Image.Resampling.LANCZOS)
    return png_bytes(image)


def add_engine_files(files: dict[str, bytes], engine: str) -> None:
    """Attach the engine's maintained native loader and wardrobe controls."""
    if engine == "godot-2d":
        for name in ("RigoraRig2D.gd", "rig.tscn", "project.godot", "ENGINE.txt"):
            files[name] = asset_path(f"exporters/godot/rig2d/{name}").read_bytes()
        return
    folder = engine.removesuffix("-rig")
    names = {
        "godot": (
            "RigoraRig.gd",
            "rig.tscn",
            "Preview.gd",
            "preview.tscn",
            "project.godot",
            "ENGINE.txt",
        ),
        "unity": (
            "Runtime/RigoraRig.cs",
            "Runtime/RigoraScenePlayback.cs",
            "Runtime/RigoraFlat.shader",
            "Runtime/RigoraParticles.shader",
            "Editor/RigoraRigImporter.cs",
            "ENGINE.txt",
        ),
        "unreal": ("import_editable_rig.py", "ENGINE.txt"),
    }[folder]
    for name in names:
        files[name] = asset_path(f"exporters/{folder}/rig/{name}").read_bytes()
    if folder == "unreal":
        plugin = asset_path("exporters/unreal/rig/RigoraRuntime/RigoraRuntime.uplugin").parent
        for path in plugin.rglob("*"):
            if path.is_file():
                files["RigoraRuntime/" + path.relative_to(plugin).as_posix()] = path.read_bytes()
