"""Public SDK discovery, trust, dependencies, real engine extensions and optional isolation."""

import json
import shutil
from pathlib import Path

import pytest

from rigora.application_services.commands import ScenePatch
from rigora.application_services.content_library import ContentService
from rigora.application_services.deformation import DeformationPreset, DeformationService
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.plugin_jobs import run_isolated
from rigora.application_services.plugins import PluginManager
from rigora.domain.entities import AnimationClip, Keyframe, Timeline, Track
from rigora.domain.project import ProjectError
from rigora.infrastructure.content_packs import read_pack
from rigora.infrastructure.preferences import PreferencesStore
from rigora.sdk import PluginRequest
from rigora.sdk.scaffold import generate_plugin


def manager(tmp_path, *directories):
    """Discover isolated developer sources without importing installed third-party plugins."""
    instance = PluginManager(PreferencesStore(tmp_path / "settings.json"))
    instance.discover(tuple(directories), installed=False, allowed_roots=tuple(directories))
    return instance


def test_generated_examples_real_tool_deformer_content_and_disable(tmp_path):
    """Three generated examples affect actual canonical data and evaluation after explicit trust."""
    roots = [
        generate_plugin(tmp_path / kind, f"org.example.{kind}", kind)
        for kind in ("tool", "deformer", "content")
    ]
    plugins = manager(tmp_path, *roots)
    assert len(plugins.states) == 3 and not plugins.contexts
    with pytest.raises(ProjectError, match="trust"):
        plugins.enable("org.example.tool")
    for key in plugins.states:
        plugins.trust(key)
        plugins.enable(key)
    doc = DocumentService()
    doc.new()
    plugins.attach(doc)
    plugins.invoke(
        "org.example.tool.stamp", PluginRequest(doc, {"phase": "press", "x": 100, "y": 200})
    )
    bones = doc.scene.skeletons[0].bones
    root = next(b for b in bones if b.extra.get("rig_root"))
    assert len(bones) == 2 and root.length == 0 and root.parent_id is None
    assert next(b for b in bones if b.id != root.id).parent_id == root.id
    doc.undo()
    assert not doc.project.scenes[0].skeletons
    mesh = MeshService(doc).import_image(Path("assets/examples/prop.svg"), 2, 2)
    before = doc.animation.pose.meshes[mesh].positions
    stage = DeformationService(doc).add(
        mesh, DeformationPreset("Wave", "org.example.deformer.wave", {"amount": 25})
    )
    assert doc.animation.pose.meshes[mesh].positions != before
    path = plugins.invoke("org.example.content.starter")
    pack, files = read_pack(path)
    ContentService(doc).apply(pack.items[0], files)
    assert len([b for b in doc.scene.skeletons[0].bones if not b.extra.get("rig_root")]) == 3
    baseline = doc.project
    plugins.disable("org.example.deformer")
    plugins.attach(doc)
    assert doc.project is baseline
    assert any("unknown deformer" in warning for warning in doc.animation.pose.warnings)
    assert (
        next(d for d in doc.project.scenes[0].deformers if d.id == stage).kind
        == "org.example.deformer.wave"
    )
    plugins.shutdown()


def write_plugin(root, plugin_id, code, **changes):
    """Write a local test plugin with a bounded manifest and reviewable Python entry point."""
    package = generate_plugin(root, plugin_id)
    manifest = package / "rigora-plugin.json"
    data = json.loads(manifest.read_text())
    data.update(changes)
    manifest.write_text(json.dumps(data))
    (package / "__init__.py").write_text(code, encoding="utf-8")
    return package


def test_portable_and_user_plugins_share_trust_and_duplicate_protection(tmp_path, monkeypatch):
    """Discover app-adjacent plugins without importing them or replacing per-user plugins."""
    app = tmp_path / "portable app"
    portable = write_plugin(
        tmp_path / "source", "org.example.portable", "raise RuntimeError('must not import')"
    )
    shutil.copytree(portable, app / "plugins" / portable.name)
    monkeypatch.setattr("rigora.application_services.plugins.application_root", lambda: app)
    plugins = PluginManager(PreferencesStore(tmp_path / "profile" / "settings.json"))
    local = write_plugin(
        tmp_path / "local", "org.example.local", "raise RuntimeError('must not import')"
    )
    shutil.copytree(local, plugins.root / local.name)
    plugins.discover(installed=False)
    assert set(plugins.states) == {"org.example.portable", "org.example.local"}
    assert not plugins.contexts and not plugins.diagnostics
    assert plugins.states["org.example.portable"].root == app / "plugins" / portable.name
    with pytest.raises(ProjectError, match="trust"):
        plugins.enable("org.example.portable")
    # A second origin must not override or inherit the first origin's trust.
    shutil.copytree(portable, plugins.root / portable.name)
    plugins.discover(installed=False)
    assert "Duplicate" in plugins.states["org.example.portable"].error
    plugins.shutdown()


def test_discovery_never_executes_untrusted_code_and_changed_source_revokes_trust(tmp_path):
    """Imports begin only after trust, and source changes invalidate persisted activation."""
    marker = tmp_path / "imported.txt"
    source = write_plugin(
        tmp_path / "source",
        "org.example.trust",
        f"""from pathlib import Path
Path({str(marker)!r}).write_text('imported')
def register(context):
    context.register('commands', context.manifest.id + '.ok', 'Okay', lambda request: 7)
""",
        capabilities=["commands"],
    )
    plugins = manager(tmp_path, source)
    assert not marker.exists()
    plugins.trust("org.example.trust")
    plugins.enable("org.example.trust")
    assert marker.read_text() == "imported"
    assert plugins.invoke("org.example.trust.ok") == 7
    marker.unlink()
    (source / "__init__.py").write_text(
        (source / "__init__.py").read_text() + "\n# changed source\n"
    )
    plugins.discover((source,), installed=False)
    plugins.restore()
    assert not marker.exists() and not plugins.contexts
    assert not plugins.trusted(plugins.states["org.example.trust"])
    safe = PluginManager(plugins.preferences, safe_mode=True)
    safe.discover((source,), installed=False)
    safe.trust("org.example.trust")
    safe.restore()
    assert not safe.contexts and not marker.exists()
    with pytest.raises(ProjectError, match="Safe mode"):
        safe.enable("org.example.trust")
    safe.shutdown()
    plugins.shutdown()


def test_dependency_preflight_registration_rollback_callback_quarantine_and_cleanup(tmp_path):
    """Broken optional code cannot publish partial registrations or bypass dependency checks."""
    cleaned = tmp_path / "cleanup.txt"
    first = write_plugin(
        tmp_path / "base",
        "org.example.base",
        """def register(context):
    context.register('commands', context.manifest.id + '.fail', 'Failure', lambda request: 1 / 0)
""",
        capabilities=["commands"],
    )
    broken = write_plugin(
        tmp_path / "broken",
        "org.example.broken",
        f"""from pathlib import Path
def register(context):
    context.on_shutdown(lambda: Path({str(cleaned)!r}).write_text('released'))
    context.register('commands', context.manifest.id + '.partial', 'Partial', lambda request: 1)
    raise RuntimeError('registration failure')
""",
        capabilities=["commands"],
        dependencies=[{"id": "org.example.base", "minimum": "1.0.0", "maximum": "2.0.0"}],
    )
    plugins = manager(tmp_path, first, broken)
    plugins.trust("org.example.broken")
    with pytest.raises(ProjectError, match="trust"):
        plugins.enable("org.example.broken")
    assert not cleaned.exists() and not plugins.contexts
    plugins.trust("org.example.base")
    with pytest.raises(ProjectError, match="registration failure"):
        plugins.enable("org.example.broken")
    assert not plugins.contexts and not plugins.contributions()
    assert cleaned.read_text() == "released"
    plugins.enable("org.example.base")
    with pytest.raises(ProjectError, match="failed"):
        plugins.invoke("org.example.base.fail")
    count = len(plugins.diagnostics)
    with pytest.raises(ProjectError, match="unavailable"):
        plugins.invoke("org.example.base.fail")
    assert len(plugins.diagnostics) == count
    assert (tmp_path / "plugins.log").exists()
    plugins.shutdown()


def test_custom_numeric_sampler_and_isolated_read_only_job(tmp_path):
    """Plugin track samples drive actual playback; isolated job mutations stay in the child."""
    source = write_plugin(
        tmp_path / "jobs",
        "org.example.jobs",
        """from rigora.application_services.rigging import RigService
def sample(track, frame):
    return frame * 3
def job(request):
    doc = request.require_document()
    RigService(doc).create_bone((0, 0), (90, 0))
    return {'bones': len(doc.project.scenes[0].skeletons[0].bones)}
def register(context):
    context.register('track_types', context.manifest.id + '.sample', 'Triple time', sample)
    context.register('batch_jobs', context.manifest.id + '.count', 'Count copied bones', job)
""",
        capabilities=["track_types", "batch_jobs"],
        permissions=["project.read", "project.write"],
    )
    plugins = manager(tmp_path, source)
    plugins.trust("org.example.jobs")
    plugins.enable("org.example.jobs")
    doc = DocumentService()
    doc.new()
    from rigora.application_services.rigging import RigService

    root = RigService(doc).create_bone((100, 100), (200, 100))
    track = Track(
        owner_id=root,
        property_path="transform.rotation",
        extra={"sampler": "org.example.jobs.sample"},
        keyframes=(Keyframe(frame=0, value=0), Keyframe(frame=20, value=60)),
    )
    timeline = Timeline(tracks=(track,))
    clip = AnimationClip(timeline_id=timeline.id, out_frame=20)
    scene = doc.project.scenes[0]
    doc.execute(
        ScenePatch(
            "Add plugin track",
            scene.id,
            {"timelines": (), "clips": ()},
            {"timelines": (timeline,), "clips": (clip,)},
        )
    )
    plugins.attach(doc)
    assert doc.animation.evaluate(5).nodes[root].local.rotation == 15
    baseline = doc.project
    result = run_isolated(plugins, "org.example.jobs.count", PluginRequest(doc), timeout=10)
    # Opening the worker snapshot migrates this legacy bare chain to an explicit Rig Root.
    assert result == {"bones": 3} and doc.project is baseline
    plugins.disable("org.example.jobs")
    plugins.attach(doc)
    assert doc.project is baseline
    with pytest.raises(ProjectError, match="Missing numeric track sampler"):
        doc.animation.evaluate(5)
    plugins.shutdown()


def test_dependency_cycles_versions_duplicate_origins_and_api_fail_before_import(tmp_path):
    """Compatibility and cyclic dependencies are rejected before executable registration."""
    marker = tmp_path / "imported"
    code = f"from pathlib import Path\nPath({str(marker)!r}).touch()\ndef register(context): pass\n"
    a = write_plugin(tmp_path / "a", "org.check.a", code, dependencies=[{"id": "org.check.b"}])
    b = write_plugin(tmp_path / "b", "org.check.b", code, dependencies=[{"id": "org.check.a"}])
    plugins = manager(tmp_path, a, b)
    for key in plugins.states:
        plugins.trust(key)
    with pytest.raises(ProjectError, match="cycle"):
        plugins.enable("org.check.a")
    assert not marker.exists()
    data = json.loads((b / "rigora-plugin.json").read_text())
    data["dependencies"] = []
    data["version"] = "0.5.0"
    (b / "rigora-plugin.json").write_text(json.dumps(data))
    data = json.loads((a / "rigora-plugin.json").read_text())
    data["dependencies"][0]["minimum"] = "1.0.0"
    (a / "rigora-plugin.json").write_text(json.dumps(data))
    plugins.discover((a, b), installed=False)
    for key in plugins.states:
        plugins.trust(key)
    with pytest.raises(ProjectError, match="version"):
        plugins.enable("org.check.a")
    incompatible = write_plugin(tmp_path / "api", "org.check.api", code, api_version="999")
    duplicate = write_plugin(tmp_path / "duplicate", "org.check.a", code)
    plugins.discover((a, b, incompatible, duplicate), installed=False)
    assert "Duplicate" in plugins.states["org.check.a"].error
    assert "999" in plugins.states["org.check.api"].error
    plugins.trust("org.check.api")
    with pytest.raises(ProjectError, match="999"):
        plugins.enable("org.check.api")
    assert not marker.exists() and not plugins.contexts
    plugins.shutdown()


def test_isolated_native_exit_timeout_and_failed_command_rollback(tmp_path):
    """Child hard exits and hung jobs fail locally; failed project commands restore the baseline."""
    source = write_plugin(
        tmp_path / "process",
        "org.check.process",
        """import os, time
from rigora.application_services.rigging import RigService
def job(request):
    if request.arguments.get('crash'):
        os._exit(7)
    time.sleep(2)
    return 1
def broken(request):
    RigService(request.require_document()).create_bone((0, 0), (90, 0))
    raise RuntimeError('rollback')
def register(context):
    context.register('batch_jobs', 'org.check.process.job', 'Worker', job)
    context.register('commands', 'org.check.process.broken', 'Broken', broken)
""",
        capabilities=["batch_jobs", "commands"],
    )
    plugins = manager(tmp_path, source)
    plugins.trust("org.check.process")
    plugins.enable("org.check.process")
    with pytest.raises(ProjectError, match="response"):
        run_isolated(plugins, "org.check.process.job", PluginRequest(arguments={"crash": True}))
    with pytest.raises(ProjectError, match="timed out"):
        run_isolated(plugins, "org.check.process.job", PluginRequest(), timeout=0.1)
    doc = DocumentService()
    doc.new()
    original = doc.project
    with pytest.raises(ProjectError, match="rollback"), doc.command_group("Broken plugin"):
        plugins.invoke("org.check.process.broken", PluginRequest(doc))
    assert doc.project is original and not doc.can_undo
    plugins.shutdown()
