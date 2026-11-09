"""Canonical offline automation, actual preview output and bounded file/mutation semantics."""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from rigora.api import AutomationError, RigoraAPI
from rigora.interfaces.cli.automation import run_batch
from rigora.resources import asset_path


def test_agent_workflow_and_svg_frames_roundtrip(tmp_path):
    """An agent-style workflow uses GUI services, produces real vector images and saves offline."""
    workflow = json.loads(Path("examples/agent-workflow.json").read_text(encoding="utf-8"))
    api = RigoraAPI(tmp_path)
    result = run_batch(api, workflow, dry_run=True)
    assert result["status"] == "planned" and api.document.project is None
    assert not (tmp_path / "output").exists()
    result = run_batch(api, workflow)
    assert result["status"] == "completed"
    assert result["steps"][-2]["data"]["valid"]
    paths = sorted((tmp_path / "output").glob("*.svg"))
    assert len(paths) == 4
    nodes = [ET.fromstring(path.read_bytes()) for path in paths]
    assert all(node.findall(".//{http://www.w3.org/2000/svg}image") for node in nodes)
    assert paths[0].read_bytes() != paths[1].read_bytes()
    clone = RigoraAPI(tmp_path)
    clone.execute("project_open", {"path": "output/agent-character.rigora"})
    assert clone.execute("project_validate").data["valid"]
    assert clone.execute("project_inspect", {"kind": "bones"}).data["items"]


def test_strict_paths_approval_dry_run_and_revision_guards(tmp_path):
    """Boundary validation precedes writes and rejects traversal, bad types and stale mutations."""
    api = RigoraAPI(tmp_path)
    start = api.execute("project_create")
    for path in ("../outside.rigora", str(tmp_path.parent / "outside.rigora")):
        with pytest.raises(AutomationError, match="outside"):
            api.execute("project_save", {"path": path})
    preview = api.execute("object_create", {"name": "Ghost"}, dry_run=True)
    assert preview.dry_run and not api.document.project.scenes[0].objects
    api.execute("object_create", {"name": "Actual"}, expected_revision=start.revision)
    with pytest.raises(AutomationError, match="revision"):
        api.execute("object_create", {}, expected_revision=start.revision)
    api.execute("project_save", {"path": "project.rigora"})
    original = (tmp_path / "project.rigora").read_bytes()
    for approval in (False, "true", 1):
        with pytest.raises(AutomationError):
            api.execute("project_save", {"path": "project.rigora", "approve_overwrite": approval})
    assert (tmp_path / "project.rigora").read_bytes() == original
    api.execute("project_save", {"path": "project.rigora", "approve_overwrite": True})
    remote = RigoraAPI(tmp_path, document=api.document, allow_overwrite=False)
    with pytest.raises(AutomationError, match="approval"):
        remote.execute("project_save", {"path": "project.rigora", "approve_overwrite": True})
    with pytest.raises(AutomationError):
        api.execute("project_create", {"width": True})
    for payload in ([], {"name": float("nan")}, {"name": object()}):
        with pytest.raises(AutomationError) as caught:
            api.execute("object_create", payload)
        assert caught.value.code == "invalid_arguments"


def test_authoring_transaction_rollback_and_shared_service_identity(tmp_path):
    """A transaction rolls back earlier commands and groups successful edits into one undo."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    source = api.document.project
    with pytest.raises(AutomationError), api.transaction():
        api.execute("object_create", {"name": "Temporary"})
        api.execute(
            "keyframe_set",
            {"owner_id": "missing", "property_path": "transform.x", "frame": 0, "value": 1},
        )
    assert api.document.project is source and not api.document.can_undo
    with api.transaction():
        api.execute("object_create", {"name": "One"})
        api.execute("object_create", {"name": "Two"})
    assert len(api.document.history.undo_stack) == 1
    api.execute("undo")
    assert api.document.project == source


def test_cli_json_help_batch_and_error_codes(tmp_path, catalog_cache_root):
    """The console adapter opens no Qt and emits predictable JSON results and exit codes."""
    import shutil

    from rigora.application_services.illustration_cache import cached_catalog

    cache = tmp_path / ".rigora-automation" / "cache" / "content"
    shutil.copytree(
        cached_catalog(catalog_cache_root), cache / cached_catalog(catalog_cache_root).name
    )
    script = (
        "from rigora.interfaces.cli.automation import automation_main; "
        "raise SystemExit(automation_main())"
    )
    workflow = Path("examples/agent-workflow.json").read_text(encoding="utf-8")
    (tmp_path / "workflow.json").write_text(workflow, encoding="utf-8")
    run = subprocess.run(
        [sys.executable, "-c", script, "--root", str(tmp_path), "batch", "workflow.json"],
        text=True,
        capture_output=True,
        timeout=40,
    )
    assert run.returncode == 0, run.stderr or run.stdout
    assert json.loads(run.stdout)["ok"]
    error = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            "--root",
            str(tmp_path),
            "project-open",
            "--args",
            '{"path":"../secret.rigora"}',
        ],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert error.returncode == 3
    assert json.loads(error.stdout)["error"]["code"] == "path_outside_root"
    core = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from rigora.api import RigoraAPI; "
            "assert not any(n.startswith('PySide6') for n in sys.modules)",
        ],
        capture_output=True,
        timeout=15,
    )
    assert core.returncode == 0
    dry_save = subprocess.run(
        [
            sys.executable,
            "-m",
            "rigora.interfaces.cli.automation",
            "--root",
            str(tmp_path),
            "--dry-run",
            "--save",
            "planned.rigora",
            "project-create",
        ],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert dry_save.returncode == 0, dry_save.stdout or dry_save.stderr
    assert json.loads(dry_save.stdout)["result"]["dry_run"]
    assert not (tmp_path / "planned.rigora").exists()
    duplicate = subprocess.run(
        [
            sys.executable,
            "-m",
            "rigora.interfaces.cli.automation",
            "--root",
            str(tmp_path),
            "project-create",
            "--args",
            '{"width":100,"width":200}',
        ],
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert duplicate.returncode == 3
    assert json.loads(duplicate.stdout)["error"]["code"] == "invalid_json"


def test_import_weights_key_edit_and_export_limits(tmp_path):
    """Low-level useful operations share validated entities and refuse oversized render jobs."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    source = asset_path("examples/prop.svg").resolve()
    imported = api.execute("asset_import", {"path": str(source)}).data
    mesh = api.execute(
        "mesh_create", {"asset_id": imported["asset_id"], "columns": 2, "rows": 2}
    ).data
    bone = api.execute("rig_create", {"start": [0, 0], "end": [100, 0]}).data
    api.execute("weights_assign", {"mesh_id": mesh["mesh_id"], "bone_ids": [bone["bone_id"]]})
    from rigora.application_services.meshes import MeshService

    service = MeshService(api.document)
    vertex = service.mesh(mesh["mesh_id"]).vertices[0]
    service.set_flags(mesh["mesh_id"], {vertex.id}, protected=True)
    baseline = api.document.project
    with pytest.raises(AutomationError, match="protected"):
        api.execute(
            "weights_assign",
            {
                "mesh_id": mesh["mesh_id"],
                "bone_ids": [bone["bone_id"]],
                "weights": {vertex.id: {bone["bone_id"]: 1}},
            },
        )
    assert api.document.project is baseline
    api.execute(
        "keyframe_set",
        {
            "owner_id": bone["bone_id"],
            "property_path": "transform.rotation",
            "frame": 12,
            "value": 30,
        },
    )
    api.execute("project_export", {"path": "project.json"})
    assert (tmp_path / "project.json").exists()
    with pytest.raises(AutomationError):
        api.execute("frame_render", {"path": "bad.svg", "frames": list(range(61))})
    assert not (tmp_path / "bad.svg").exists()
    with pytest.raises(AutomationError):
        api.execute("frame_render", {"path": "bad.svg", "width": 50000})


def test_pack_and_plugin_discovery_cannot_read_outside_authorized_roots(tmp_path, monkeypatch):
    """Discovery checks boundaries before opening user-controlled pack or plugin paths."""
    from rigora.application_services import content_library, plugins

    root = tmp_path / "workspace"
    root.mkdir()
    api = RigoraAPI(root)
    expected_count = len(api.execute("library_list").data["items"])
    outside = tmp_path / "outside.rigpack"
    outside.write_bytes(b"not authorized")
    api.library.additional_packs = (outside,)
    original = content_library.read_pack
    reads = []

    def authorized_read(path, **kwargs):
        """Record actual pack reads, so rejected paths cannot be silently opened."""
        reads.append(path)
        return original(path, **kwargs)

    monkeypatch.setattr(content_library, "read_pack", authorized_read)
    assert len(api.execute("library_list").data["items"]) == expected_count
    assert outside not in reads
    assert "outside authorized" in api.library.warnings[0]
    api.library.preferences.data["plugin_development_dirs"] = [str(tmp_path)]
    inspected = []
    monkeypatch.setattr(plugins, "inspect_plugin", lambda *a, **kw: inspected.append(a))
    assert api.execute("plugin_list").data["items"] == []
    assert not inspected
