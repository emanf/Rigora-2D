"""Editable game exports retain true skinning, sampled deformation and wardrobe ownership."""

import json
import math
import struct
import zipfile
from dataclasses import replace

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.output import OutputService, OutputSettings, RenderCancelled
from rigora.domain.character_recipe import character_preset
from rigora.domain.geometry import affine, multiply, transform_point


def decode_glb(data):
    """Decode native glTF chunks so tests verify actual mesh buffers rather than export metadata."""
    magic, version, length = struct.unpack_from("<4sII", data)
    assert magic == b"glTF" and version == 2 and length == len(data)
    size, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    gltf = json.loads(data[20 : 20 + size])
    binary_size, binary_kind = struct.unpack_from("<I4s", data, 20 + size)
    assert binary_kind == b"BIN\0"
    return gltf, data[28 + size : 28 + size + binary_size]


def accessor(gltf, binary, index):
    """Read the exporter's tightly packed, explicitly typed glTF elements."""
    item = gltf["accessors"][index]
    view = gltf["bufferViews"][item["bufferView"]]
    width = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[item["type"]]
    code = {5126: "f", 5123: "H", 5125: "I"}[item["componentType"]]
    return list(
        struct.iter_unpack(
            "<" + code * width, binary[view["byteOffset"] : view["byteOffset"] + view["byteLength"]]
        )
    )


def world_matrices(runtime, frame):
    """Evaluate exported bone TRS hierarchies independently of Rigora's scene evaluator."""
    worlds = {}

    def resolve(index):
        if index in worlds:
            return worlds[index]
        node = runtime["nodes"][index]
        sample = node["samples"][frame]
        x, y, _ = sample["translation"]
        _, _, z, w = sample["rotation"]
        sx, sy, _ = sample["scale"]
        local = affine(x, y, math.degrees(2 * math.atan2(z, w)), sx, sy, 0, 0)
        worlds[index] = multiply(resolve(node["parent"]), local) if node["parent"] >= 0 else local
        return worlds[index]

    for i in range(len(runtime["nodes"])):
        resolve(i)
    return worlds


def check_geometry(document, gltf, binary, runtime, frames):
    """Compare reconstructed skin/morph vertices with canonical evaluation."""
    for f, frame in enumerate(frames):
        pose = document.animation.evaluate(frame)
        worlds = world_matrices(runtime, f)
        for part in runtime["parts"]:
            node = next(n for n in gltf["nodes"] if n["name"] == part["node"])
            skin = gltf["skins"][node["skin"]]
            primitive = gltf["meshes"][node["mesh"]]["primitives"][0]
            attrs = primitive["attributes"]
            positions = accessor(gltf, binary, attrs["POSITION"])
            weights = accessor(gltf, binary, attrs["WEIGHTS_0"])
            joints = accessor(gltf, binary, attrs["JOINTS_0"])
            binds = accessor(gltf, binary, skin["inverseBindMatrices"])
            matrices = [
                multiply(worlds[j], (b[0], b[1], b[4], b[5], b[12], b[13]))
                for j, b in zip(skin["joints"], binds, strict=True)
            ]
            offsets = (
                accessor(gltf, binary, primitive["targets"][f]["POSITION"])
                if "targets" in primitive
                else [(0, 0, 0)] * len(positions)
            )
            source = pose.meshes[part["id"]]
            for i, (point, delta) in enumerate(zip(positions, offsets, strict=True)):
                x = y = 0
                for joint, weight in zip(joints[i], weights[i], strict=True):
                    px, py = transform_point(
                        matrices[joint], point[0] + delta[0], point[1] + delta[1]
                    )
                    x += px * weight
                    y += py * weight
                expected = transform_point(
                    pose.nodes[source.object_id].world_matrix, *source.positions[i]
                )
                assert (x, y) == pytest.approx((expected[0] / 100, -expected[1] / 100), abs=2e-5)


@pytest.mark.parametrize("engine", ("godot-rig", "unity-rig", "unreal-rig"))
def test_editable_character_skin_geometry_wardrobe_and_source_are_preserved(engine, tmp_path):
    """Export native skin/bone curves, wardrobe parts and matching character poses."""
    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(
        build_character(replace(character_preset("nova"), motions=("Walk",)))
    )
    before = doc.project
    frames = (0, 12, 24)
    path = tmp_path / "rig.zip"
    result = OutputService(lambda _: path).export(
        doc, str(path), OutputSettings(format=engine, frames=frames, width=512, height=512)
    )
    assert result["status"] == "completed" and doc.project is before
    with zipfile.ZipFile(path) as archive:
        gltf, binary = decode_glb(archive.read("character.glb"))
        runtime = json.loads(archive.read("rig.json"))
        assert runtime["wardrobes"] and any(w["owner"] == root for w in runtime["wardrobes"])
        assert any(n["kind"] == "bone" for n in runtime["nodes"])
        assert any(c["target"]["path"] == "rotation" for c in gltf["animations"][0]["channels"])
        check_geometry(doc, gltf, binary, runtime, frames)
        assert any(name.endswith(".svg") for name in archive.namelist())
        assert "source-project.json" in archive.namelist()
        assert runtime["duration"] == pytest.approx(3 / 24)


def test_two_bone_weighted_deformation_and_cancellation_are_not_flattened(tmp_path):
    """Retain two-bone blending and sampled mesh correction in a single-image rig."""
    doc = DocumentService()
    doc.new()
    service = ImageRigService(doc)
    mesh = service.import_image_bytes(
        "original.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="480">'
        b'<rect width="320" height="480" fill="#888"/></svg>',
        2,
        2,
    )
    first = service.draw_bone(mesh, (850, 400), (950, 400))
    second = service.draw_bone(mesh, (950, 400), (1050, 400), first)
    editor = AnimationEditingService(doc)
    editor.key(second, "transform.rotation", 0, 10)
    editor.key(second, "transform.rotation", 12, 70)
    frames = (0, 6, 12)
    path = tmp_path / "weighted.zip"
    OutputService(lambda _: path).export(
        doc, str(path), OutputSettings(format="godot-rig", frames=frames)
    )
    with zipfile.ZipFile(path) as archive:
        gltf, binary = decode_glb(archive.read("character.glb"))
        runtime = json.loads(archive.read("rig.json"))
        assert any(
            sum(w > 0 for w in v["values"]) > 1 for p in runtime["parts"] for v in p["weights"]
        )
        check_geometry(doc, gltf, binary, runtime, frames)
    import threading

    cancelled = threading.Event()
    cancelled.set()
    before = path.read_bytes()
    with pytest.raises(RenderCancelled):
        OutputService(lambda _: path).export(
            doc, str(path), OutputSettings(format="godot-rig"), cancel=cancelled
        )
    assert path.read_bytes() == before
