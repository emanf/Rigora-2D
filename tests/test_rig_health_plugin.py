"""Exercise a distributable plugin through actual discovery, trust, worker and panel contracts."""

from dataclasses import replace
from pathlib import Path

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.plugin_jobs import run_isolated
from rigora.application_services.plugins import PluginManager
from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Deformer,
    Keyframe,
    Mesh,
    SceneObject,
    Skeleton,
    Timeline,
    Track,
    Transform,
    Vertex,
)
from rigora.domain.project import Project, Scene
from rigora.infrastructure.preferences import PreferencesStore
from rigora.sdk import PluginRequest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "rig_health"
KEY = "org.rigora.rig_health"


@pytest.fixture
def health(tmp_path):
    """Load exactly the shipped plugin with isolated, explicitly approved test trust."""
    manager = PluginManager(PreferencesStore(tmp_path / "preferences.json"))
    manager.discover((PLUGIN,), installed=False, allowed_roots=(PLUGIN,))
    manager.trust(KEY)
    manager.enable(KEY)
    yield manager
    manager.shutdown()


def document(*, risks=False):
    """Build valid canonical data with optional genuine binding/scale/clip-coverage risks."""
    first = Bone(name="Root", transform=Transform(scale_x=0 if risks else 1))
    second = Bone(name="Root" if risks else "Hand", parent_id=None if risks else first.id)
    rig = Skeleton(name="Example rig", bones=(first, second))
    owner = SceneObject(name="Arm")
    vertices = tuple(
        Vertex(x=x, y=y, weights={} if risks and i == 0 else {first.id: 1})
        for i, (x, y) in enumerate(((0, 0), (100, 0), (0, 100)))
    )
    mesh = Mesh(
        name="Arm mesh",
        object_id=owner.id,
        vertices=vertices,
        triangles=(tuple(v.id for v in vertices),),
    )
    skin = Deformer(
        owner_id=mesh.id,
        kind="skinning",
        parameters={"bind_matrices": {} if risks else {first.id: (1, 0, 0, 1, 0, 0)}},
    )
    track = Track(
        owner_id=first.id,
        property_path="transform.rotation",
        keyframes=tuple(Keyframe(frame=f, value=0) for f in (0, 15 if risks else 10, 20)),
    )
    timeline = Timeline(tracks=(track,))
    clips = tuple(
        AnimationClip(timeline_id=timeline.id, in_frame=a, out_frame=b)
        for a, b in ((0, 10), (20, 30))
    )
    service = DocumentService()
    service.new()
    service.project = Project(
        scenes=(
            Scene(
                objects=(owner,),
                skeletons=(rig,),
                meshes=(mesh,),
                deformers=(skin,),
                timelines=(timeline,),
                clips=clips,
            ),
        )
    )
    return service


def test_static_report_real_risks_clip_union_and_no_mutations(health):
    """Separate actual skin/scale errors from intentional roots and unused-key notes."""
    clean = document()
    report = health.invoke(KEY + ".scan", PluginRequest(clean))
    assert report["score"] == 100 and not report["findings"]
    assert report["totals"]["keys"] == 3
    risky = document(risks=True)
    before = risky.project
    report = health.invoke(KEY + ".scan", PluginRequest(risky))
    assert (report["errors"], report["warnings"], report["notes"]) == (2, 2, 2)
    assert report["score"] == 50
    assert {row["code"] for row in report["findings"]} == {
        "collapsed_scale",
        "duplicate_bone_names",
        "multiple_roots",
        "unweighted_vertices",
        "incomplete_bind",
        "keys_outside_clips",
    }
    assert all(row["suggestion"] and row["item_id"] for row in report["findings"])
    assert risky.project is before and not risky.history.undo_stack
    # Disabled skin stages and explicitly pinned vertices are not loose-skin warnings.
    scene = before.scenes[0]
    risky.project = replace(
        before, scenes=(replace(scene, deformers=(replace(scene.deformers[0], enabled=False),)),)
    )
    report = health.invoke(KEY + ".scan", PluginRequest(risky))
    assert not {row["code"] for row in report["findings"]} & {
        "unweighted_vertices",
        "incomplete_bind",
    }
    pinned = replace(scene.meshes[0].vertices[0], pinned=True)
    mesh = replace(scene.meshes[0], vertices=(pinned, *scene.meshes[0].vertices[1:]))
    skin = replace(scene.deformers[0], parameters={})
    risky.project = replace(before, scenes=(replace(scene, meshes=(mesh,), deformers=(skin,)),))
    codes = {row["code"] for row in health.invoke(KEY + ".scan", PluginRequest(risky))["findings"]}
    assert "missing_bind" in codes and "unweighted_vertices" not in codes


def test_bounded_report_prioritizes_late_errors_and_empty_has_no_grade(health):
    """Large projects retain accurate counts and serious findings even after many notes."""
    service = DocumentService()
    service.new()
    assert health.invoke(KEY + ".scan", PluginRequest(service))["score"] is None
    rigs = tuple(Skeleton(bones=(Bone(name="A"), Bone(name="B"))) for _ in range(205))
    item = SceneObject(transform=Transform(scale_y=0))
    service.project = Project(scenes=(Scene(skeletons=rigs), Scene(objects=(item,))))
    report = health.invoke(KEY + ".scan", PluginRequest(service))
    assert report["notes"] == 205 and report["errors"] == 1
    assert len(report["findings"]) == 200 and report["omitted_findings"] == 6
    assert report["findings"][0]["code"] == "collapsed_scale"


def test_source_plugin_isolated_validator_matches_direct_result(health):
    """The distributable Python package works through the real SDK subprocess protocol."""
    request = PluginRequest(document(risks=True))
    assert run_isolated(health, KEY + ".scan", request) == health.invoke(KEY + ".scan", request)


@pytest.mark.gui
def test_panel_background_scan_rebind_copy_and_disable(qtbot, tmp_path):
    """Scan a real immutable revision without blocking Qt; stale results cannot cross projects."""
    from PySide6.QtCore import QThreadPool
    from PySide6.QtWidgets import QApplication
    from test_plugins_gui import open_window

    window = open_window(qtbot, tmp_path, (PLUGIN,))
    model = window.viewmodel
    service = document(risks=True)
    model.documents.project = service.project
    model.changed.emit()
    model.enable_plugin(KEY, trust=True)
    assert not model.plugin_error
    panel = window.plugin_workspace.docks[0].widget()
    panel.scan_button.click()
    assert panel.job is not None and not panel.scan_button.isEnabled()
    qtbot.waitUntil(lambda: panel.job is None, timeout=10000)
    assert panel.report["score"] == 50 and panel.table.rowCount() == 6
    assert "Restore a nonzero scale" in panel.detail.toPlainText()
    panel.copy_button.click()
    assert '"score": 50' in QApplication.clipboard().text()
    panel.start_scan()
    panel.rigora_bind(PluginRequest(document()))
    qtbot.waitUntil(lambda: panel.job is None, timeout=10000)
    assert panel.report is None and not panel.copy_button.isEnabled()
    assert panel.table.rowCount() == 0
    panel.start_scan()
    qtbot.waitUntil(lambda: panel.job is None, timeout=10000)
    assert panel.report["score"] == 100
    panel.rigora_bind(PluginRequest())
    assert panel.report is None and not panel.scan_button.isEnabled()
    panel.rigora_bind(PluginRequest(document()))
    panel.start_scan()
    model.plugins.disable(KEY)
    assert not window.plugin_workspace.docks
    qtbot.waitUntil(lambda: QThreadPool.globalInstance().activeThreadCount() == 0)
    QApplication.processEvents()
    window.close()
