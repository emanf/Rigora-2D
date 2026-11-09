"""The public video importer shares canonical services, dry-run and file authorization."""

import pytest
from test_video_rig import specimen

from rigora.api import AutomationError, RigoraAPI
from rigora.infrastructure import video_rig
from rigora.infrastructure.video_models import MODELS


def test_video_import_api_dry_run_editable_action_and_one_undo(tmp_path, monkeypatch):
    """Automation can create exactly the GUI's rig without implicitly downloading models."""
    (tmp_path / "clip.mp4").write_bytes(b"decoder boundary")
    models = tmp_path / "models"
    models.mkdir()
    for key in MODELS:
        (models / (key + ".onnx")).write_bytes(b"model boundary")
    monkeypatch.setattr(video_rig, "analyze_video", lambda *a, **k: specimen())
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    baseline = api.document.project
    arguments = {"path": "clip.mp4", "models": "models", "cutout": False}
    planned = api.execute("video_rig_import", arguments, dry_run=True)
    assert planned.dry_run and api.document.project is baseline
    result = api.execute("video_rig_import", arguments)
    assert result.data["bones"] == 11 and result.can_undo
    assert any(c.id == result.data["clip_id"] for c in api.document.scene.clips)
    api.execute("undo")
    assert api.document.project == baseline


def test_video_import_cannot_read_an_unauthorized_model_directory(tmp_path):
    """Model weights receive the same read-root protection as imported video and artwork."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    with pytest.raises(AutomationError, match="outside"):
        api.execute("video_rig_import", {"path": "clip.mp4", "models": "../outside"})


def test_media_import_api_accepts_ordered_images_and_static_pose(tmp_path, monkeypatch):
    """The shared API exposes media sources without inventing animation for one still."""
    from dataclasses import replace

    for name in ("pose2.png", "pose1.png"):
        (tmp_path / name).write_bytes(b"image boundary")
    models = tmp_path / "models"
    models.mkdir()
    for key in MODELS:
        (models / (key + ".onnx")).write_bytes(b"model boundary")
    calls = []

    def analyze(paths, *args, **kwargs):
        calls.append((paths, kwargs))
        analysis = specimen()
        return replace(analysis, poses=analysis.poses[: len(paths)])

    monkeypatch.setattr(video_rig, "analyze_images", analyze)
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    baseline = api.document.project
    arguments = {"paths": ["pose2.png"], "models": "models", "cutout": False}
    planned = api.execute("media_rig_import", arguments, dry_run=True)
    assert not planned.data["clip_id"] and api.document.project is baseline
    result = api.execute("media_rig_import", arguments)
    assert not result.data["clip_id"] and result.data["bones"] == 11
    api.execute("undo")
    arguments["paths"] = ["pose2.png", "pose1.png"]
    arguments["sample_fps"] = 12
    result = api.execute("media_rig_import", arguments)
    assert result.data["clip_id"]
    assert [path.name for path in calls[-1][0]] == ["pose2.png", "pose1.png"]
    assert calls[-1][1]["sample_fps"] == 12
    api.execute("undo")
    protected = api.document.project
    with pytest.raises(AutomationError, match="outside"):
        api.execute("media_rig_import", {**arguments, "paths": ["../outside.png"]})
    assert api.document.project is protected
    assert api.document.project == baseline
