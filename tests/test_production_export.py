"""Export parity, preflight isolation and real headless Godot 2D skinning checks."""

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.documents import DocumentService
from rigora.application_services.export_preflight import ExportPreflight
from rigora.application_services.game_authoring import GameAuthoringService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.output import OutputService, OutputSettings
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError


def export_document():
    """Create a genuinely weighted two-bone rig with animated source-vector recoloring."""
    doc = DocumentService()
    doc.new()
    rig = ImageRigService(doc)
    mesh = rig.import_image_bytes(
        "body.svg",
        b'<svg xmlns="http://www.w3.org/2000/svg" width="320" height="480">'
        b'<rect width="320" height="480" fill="#888888"/></svg>',
        2,
        2,
    )
    first = rig.draw_bone(mesh, (850, 400), (950, 400))
    second = rig.draw_bone(mesh, (950, 400), (1050, 400), first)
    edit = AnimationEditingService(doc)
    edit.key(second, "transform.rotation", 0, 10)
    edit.key(second, "transform.rotation", 12, 70)
    look = AppearanceService(doc)
    stage = look.ensure(mesh)
    edit.key(stage, "parameters.tint.amount", 0, 0, interpolation="step")
    edit.key(stage, "parameters.tint.amount", 12, 0.8, interpolation="step")
    edit.key(stage, "parameters.tint.g", 0, 0)
    edit.key(stage, "parameters.tint.b", 0, 0)
    edit.marker("Footstep", 6, event_type="footstep", payload={"surface": "stone"})
    return doc, mesh


@pytest.mark.parametrize("kind", ("godot-rig", "godot-2d", "unity-rig", "unreal-rig"))
def test_editable_packages_retain_animated_colors_and_retime_events(kind, tmp_path):
    """Each native adapter receives actual alternate textures and correctly retimed callbacks."""
    doc, _ = export_document()
    revision = doc.project
    path = tmp_path / "rig.zip"
    OutputService(lambda _: path).export(
        doc,
        str(path),
        OutputSettings(
            format=kind,
            frames=(0, 6, 12),
            width=128,
            height=128,
        ),
    )
    assert doc.project is revision
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("rig.json"))
        part = data["parts"][0]
        assert len(set(part["texture_states"])) == 2
        assert archive.read(part["texture_states"][0]) != archive.read(part["texture_states"][-1])
        assert data["events"][0]["seconds"] == pytest.approx(1 / 24)
        assert json.loads(data["events"][0]["payload_json"]) == {"surface": "stone"}
        assert data["scene_samples"][0]["camera"]
        if kind == "unreal-rig":
            compile(archive.read("import_editable_rig.py"), "importer.py", "exec")


def test_preflight_reports_unsupported_features_and_export_preserves_existing_output(tmp_path):
    """Native capability gaps block publication, and the supported 2D route passes every sample."""
    doc, _ = export_document()
    GameAuthoringService(doc).emitter(settings=dict(rate=1, lifetime=2, speed=0))
    before = doc.project
    settings = OutputSettings(format="unreal-rig", frames=(0, 6, 12))
    result = ExportPreflight(doc.fork()).inspect(settings)
    assert not result["ready"] and result["metrics"]["evaluated"] == 3
    assert "native_particles" in {f["code"] for f in result["findings"]}
    path = tmp_path / "preserved.zip"
    path.write_bytes(b"keep")
    with pytest.raises(ProjectError, match="does not render particles"):
        OutputService(lambda _: path).export(doc, str(path), settings)
    assert path.read_bytes() == b"keep" and doc.project is before
    for kind in ("godot-2d", "unity-rig"):
        assert ExportPreflight(doc.fork()).inspect(OutputSettings(format=kind, frames=(0, 6, 12)))[
            "ready"
        ]


def test_export_events_follow_reverse_and_held_samples_with_bounded_expansion():
    """Existing arbitrary frame lists keep ordered callbacks without duplicate held events."""
    from rigora.application_services.export_metadata import exported_events

    doc, _ = export_document()
    AnimationEditingService(doc).marker("Start", 0, event_type="signal", payload={"value": 1})
    frames = (0, 0, 6, 12, 6, 0)
    result = exported_events(doc, frames, 24)
    assert [e["frame"] for e in result] == [0, 6, 6, 0]
    assert [e["seconds"] for e in result] == pytest.approx([0, 2 / 24, 4 / 24, 5 / 24])
    assert json.loads(result[0]["payload_json"]) == {"value": 1}
    assert ExportPreflight(doc).inspect(OutputSettings(format="gif", frames=frames))["ready"]
    assert len(exported_events(doc, (6,), 24)) == 1
    assert not exported_events(doc, (), 24)
    for index in range(9):
        AnimationEditingService(doc).marker(f"Signal {index}", 3, event_type="signal")
    repeated = (0, 6) * 300
    with pytest.raises(ProjectError, match="4096 event occurrences"):
        exported_events(doc, repeated, 24)
    report = ExportPreflight(doc).inspect(OutputSettings(format="runtime-json", frames=repeated))
    assert not report["ready"]
    assert any("4096 event occurrences" in finding["message"] for finding in report["findings"])
    assert not ExportPreflight(doc).inspect(
        OutputSettings(format="runtime-json", frames=repeated), deep=False
    )["ready"]
    assert ExportPreflight(doc).inspect(OutputSettings(format="gif", frames=repeated), deep=False)[
        "ready"
    ]


@pytest.mark.parametrize("kind", ("godot-rig", "unreal-rig"))
@pytest.mark.parametrize("driver", ("follow", "parent"))
def test_preflight_blocks_indirect_camera_motion_without_direct_camera_keys(kind, driver):
    """Follow rules and animated camera folders must not bypass native capability checks."""
    from rigora.application_services.camera_shots import CameraShotService
    from rigora.application_services.scene_editing import SceneEditingService

    doc, mesh = export_document()
    target = next(m.object_id for m in doc.scene.meshes if m.id == mesh)
    camera = doc.scene.cameras[0].id
    if driver == "follow":
        AnimationEditingService(doc).key(target, "transform.x", 12, 100)
        CameraShotService(doc).follow(camera, target)
    else:
        SceneEditingService(doc).flags((camera,), locked=False)
        folder = SceneEditingService(doc).group((camera,), "Camera dolly")
        AnimationEditingService(doc).key(folder, "transform.x", 12, 100)
    assert not any(t.owner_id == camera for t in doc.animation.evaluator.timeline.tracks)
    report = ExportPreflight(doc).inspect(
        OutputSettings(format=kind, frames=(0, 6, 12)), deep=False
    )
    assert not report["ready"]
    assert "native_camera" in {finding["code"] for finding in report["findings"]}
    for supported in ("godot-2d", "unity-rig"):
        assert ExportPreflight(doc).inspect(
            OutputSettings(format=supported, frames=(0, 6, 12)), deep=False
        )["ready"]


def test_runtime_json_retains_evaluated_camera_cuts_lens_and_background(tmp_path):
    """Runtime interchange carries framing/settings as well as camera transform nodes."""
    from rigora.application_services.cameras import CameraService

    doc, _ = export_document()
    cameras = CameraService(doc)
    opening = doc.scene.cameras[0].id
    close = cameras.add("Close shot")
    cameras.update(close, background_mode="color", background_color="#222222")
    cameras.activate(close, frame=6)
    cameras.action(close, "rain", "camera_effect", 0, 12)
    path = tmp_path / "camera.json"
    OutputService(lambda _: path).export(
        doc,
        str(path),
        OutputSettings(
            format="runtime-json",
            frames=(0, 6, 12),
            width=64,
            height=64,
        ),
    )
    data = json.loads(path.read_text())
    assert [s["active_camera"] for s in data["samples"]] == [opening, close, close]
    camera = next(c for c in data["samples"][1]["cameras"] if c["id"] == close)
    assert camera["background_color"] == "#222222"
    assert camera["lens_effects"]["rain"] > 0


def test_headless_godot_2d_actual_skinning_seek_particles_and_event_delivery(tmp_path):
    """Execute the exported engine scene and compare native polygon vertices to canonical poses."""
    binary = Path(
        os.environ.get(
            "RIGORA_GODOT", "build/export-validation/godot/Godot_v4.7.2-stable_win64_console.exe"
        )
    ).resolve()
    if not binary.is_file():
        pytest.skip("Set RIGORA_GODOT to a local console executable for native validation.")
    doc, mesh = export_document()
    game = GameAuthoringService(doc)
    game.emitter(x=900, y=400, settings=dict(rate=2, lifetime=2, speed=0, size=4))
    game.region(name="Hand hit", x=920, y=400, width=30, height=20)
    from rigora.application_services.cameras import CameraService

    cameras = CameraService(doc)
    second_camera = cameras.add("Close shot")
    cameras.update(second_camera, background_mode="color", background_color="#222222")
    cameras.activate(second_camera, frame=6)
    cameras.action(second_camera, "rain", "camera_effect", 0, 12)
    archive_path = tmp_path / "native.zip"
    OutputService(lambda _: archive_path).export(
        doc,
        str(archive_path),
        OutputSettings(
            format="godot-2d",
            frames=(0, 6, 12),
            width=128,
            height=128,
        ),
    )
    root = tmp_path / "native"
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(root)
    script = """extends SceneTree
func _initialize():
    call_deferred("verify")
func verify():
    var rig = load("res://rig.tscn").instantiate()
    var authored: bool = rig.has_node("SceneCamera/Armature")
    authored = authored and rig.find_children("*", "Bone2D", true, false).size() == 3
    rig.playing = false
    root.add_child(rig)
    var events: Array = []
    rig.event_fired.connect(func(e): events.append(e))
    rig.seek(1.0 / 24)
    var overlays: bool = rig.backdrop.visible and rig.lens.visible
    var camera_transform = rig.scene_layer.transform
    rig.seek(2.0 / 24)
    var points: Array = []
    for polygon in rig.parts.values():
        for point in polygon.polygon:
            points.append([point.x, point.y])
    var seek_events: int = events.size()
    rig.seek(0)
    rig._emit_interval(0, 2.0 / 24)
    var texture = rig.parts.values()[0].texture.resource_path
    rig.use_scene_camera = false
    rig.refresh_pose()
    var game_canvas: bool = rig.skeleton.get_canvas() == rig.get_canvas()
    var payload = {"points": points, "events": events, "seek_events": seek_events,
        "bones": rig.bones.filter(func(b): return b is Bone2D).size(),
        "particles": rig.particle_nodes.size(), "regions": rig.get_regions().size(),
        "texture": texture, "overlays": overlays, "game_canvas": game_canvas,
        "authored": authored,
        "projection": [camera_transform.origin.x, camera_transform.origin.y]}
    print("RIGORA_TEST:" + JSON.stringify(payload))
    quit()
"""
    (root / "verify.gd").write_text(script, encoding="utf-8")
    for arguments in (("--editor", "--import", "--quit"), ("--script", "res://verify.gd")):
        run = subprocess.run(
            [str(binary), "--headless", "--path", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert run.returncode == 0 and "SCRIPT ERROR" not in run.stderr, run.stdout + run.stderr
    output = json.loads(
        next(
            line.removeprefix("RIGORA_TEST:")
            for line in run.stdout.splitlines()
            if line.startswith("RIGORA_TEST:")
        )
    )
    pose = doc.animation.evaluate(12)
    source = pose.meshes[mesh]
    expected = [
        transform_point(pose.nodes[source.object_id].world_matrix, *p) for p in source.positions
    ]
    for actual, wanted in zip(output["points"], expected, strict=True):
        assert actual == pytest.approx(wanted, abs=0.001)
    assert output["bones"] == 3 and output["particles"] > 0 and output["regions"] == 1
    assert output["seek_events"] == 0
    assert len(output["events"]) == 1 and output["events"][0]["type"] == "footstep"
    assert output["overlays"]
    assert output["game_canvas"]
    assert output["authored"]


def test_headless_godot_planar_runtime_texture_and_callback_without_seek_events(tmp_path):
    """Import the native glTF package and execute its runtime, including resource switching."""
    binary = Path(
        os.environ.get(
            "RIGORA_GODOT",
            "build/export-validation/godot/Godot_v4.7.2-stable_win64_console.exe",
        )
    ).resolve()
    if not binary.is_file():
        pytest.skip("Set RIGORA_GODOT to a console executable for native validation.")
    doc, _ = export_document()
    path = tmp_path / "planar.zip"
    OutputService(lambda _: path).export(
        doc,
        str(path),
        OutputSettings(
            format="godot-rig",
            frames=(0, 6, 12),
            width=128,
            height=128,
        ),
    )
    root = tmp_path / "planar"
    with zipfile.ZipFile(path) as archive:
        archive.extractall(root)
    (root / "verify.gd").write_text(
        """extends SceneTree
func _initialize():
    call_deferred("verify")
func verify():
    var rig = load("res://rig.tscn").instantiate()
    rig.playing = false
    root.add_child(rig)
    var events: Array = []
    rig.event_fired.connect(func(e): events.append(e))
    rig.seek(2.0 / 24)
    var texture = rig.parts.values()[0].material_override.albedo_texture.resource_path
    var seek_events = events.size()
    var skeleton = rig.find_children("*", "Skeleton3D", true, false)[0]
    skeleton.set_bone_pose_position(0, Vector3(1, 2, 3))
    rig._process(0.1)
    var manual_pose: bool = skeleton.get_bone_pose_position(0).is_equal_approx(Vector3(1, 2, 3))
    rig.seek(0)
    rig.playing = true
    rig.motion.speed_scale = 2.0
    rig._process(0.6 / 24)
    var speed_events: int = events.size()
    events.clear()
    rig.event_time = rig.definition.duration * 5000
    rig._process(0.6 / 24)
    print("RIGORA_TEST:" + JSON.stringify({"texture": texture, "events": events,
        "seek_events": seek_events, "parts": rig.parts.size(), "manual_pose": manual_pose,
        "speed_events": speed_events}))
    quit()
""",
        encoding="utf-8",
    )
    for arguments in (("--editor", "--import", "--quit"), ("--script", "res://verify.gd")):
        run = subprocess.run(
            [str(binary), "--headless", "--path", str(root), *arguments],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert run.returncode == 0 and "ERROR" not in run.stderr, run.stdout + run.stderr
    output = json.loads(
        next(
            line.removeprefix("RIGORA_TEST:")
            for line in run.stdout.splitlines()
            if line.startswith("RIGORA_TEST:")
        )
    )
    assert "-1.png" in output["texture"] and output["parts"] == 1
    assert output["seek_events"] == 0 and len(output["events"]) == 1
    assert output["manual_pose"] and output["speed_events"] == 1
