"""Reusable character drags prepare once off-thread and retain atomic placement history."""

import json
import threading
from pathlib import Path
from time import perf_counter

import pytest
from PySide6.QtCore import QPointF, QTimer
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.content_library import ContentService
from rigora.domain.geometry import transform_point

pytestmark = pytest.mark.gui


def test_full_character_preview_and_drop_keep_ui_live_and_reuse_the_prepared_graph(
    editor, qtbot, monkeypatch
):
    """Exercise the real dense human template, recording callback and UI-heartbeat durations."""
    vm, viewport, workspace = editor.viewmodel, editor.viewport, editor.content_drop
    entry = next(
        e
        for e in vm.content.entries
        if e.item.category == "Characters" and e.item.name == "Dash · Runner"
    )
    baseline = vm.documents.project
    calls = []
    original_place = ContentService.place
    main_thread = threading.get_ident()

    def placed(service, *args, **kwargs):
        """Record actual full graph assembly calls without replacing any authoring behavior."""
        calls.append(threading.get_ident())
        return original_place(service, *args, **kwargs)

    monkeypatch.setattr(ContentService, "place", placed)
    monkeypatch.setattr(
        workspace, "targets", lambda *_: pytest.fail("New scene fragments do not need hit testing")
    )
    pulses = []
    heartbeat = QTimer(editor)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: pulses.append(perf_counter()))
    heartbeat.start()
    point = QPointF(360, 260)
    start = perf_counter()
    workspace.move(entry.key, point)
    move_submit = perf_counter() - start
    qtbot.waitUntil(lambda: viewport.drop_pose is not None, timeout=30000)
    ready_seconds = perf_counter() - start
    assert vm.documents.project is baseline
    assert calls == [calls[0]] and calls[0] != main_thread
    assert len(viewport.drop_pose.meshes) >= 40
    assert workspace.document is not None
    ghost = viewport.drop_pose
    for index in range(40):
        workspace.move(entry.key, point + QPointF(index, index / 2))
    assert calls == [calls[0]] and viewport.drop_pose is ghost
    before_drop_pulses = len(pulses)
    start = perf_counter()
    workspace.drop(entry.key, point)
    drop_submit = perf_counter() - start
    assert vm.documents.project is baseline
    qtbot.waitUntil(lambda: not workspace.placing, timeout=30000)
    placed_seconds = perf_counter() - start
    heartbeat.stop()
    assert not vm.content.error
    assert len(pulses) > before_drop_pulses or placed_seconds < 0.05
    assert calls == [calls[0]]
    assert not editor.object_edit.active
    doc = vm.documents
    assert len(doc.history.undo_stack) == 1 and len(doc.scene.meshes) >= 40
    assert len(doc.project.assets) >= 40
    assert all(m.asset_id in {a.id for a in doc.project.assets} for m in doc.scene.meshes)
    assert not doc.animation.pose.warnings
    root = next(g for g in doc.scene.groups if g.extra.get("object_container"))
    assert root.id in ghost.nodes
    assert root.extra.get("linked_object")
    expected = viewport.scene_point(point)
    assert transform_point(
        doc.animation.pose.nodes[root.id].world_matrix,
        root.transform.pivot_x,
        root.transform.pivot_y,
    ) == pytest.approx(expected.toTuple())
    result = doc.project
    vm.undo()
    assert doc.project is baseline
    vm.redo()
    assert doc.project is result
    qtbot.waitUntil(
        lambda: {a.id for a in doc.project.assets} <= viewport.artwork.vectors.keys(), timeout=15000
    )
    editor.scene_workspace.select_entries((root.id,))
    viewport.grab()
    preview_times = []
    runtime = doc.animation
    undo_count = len(doc.history.undo_stack)
    vm.scene.begin_preview()
    for index in range(1, 9):
        sample_start = perf_counter()
        vm.scene.preview_transform(dx=index * 5, dy=index * 2)
        assert doc.project is result and doc.animation is runtime
        assert len(doc.history.undo_stack) == undo_count
        viewport.grab()
        preview_times.append(perf_counter() - sample_start)
    sample_start = perf_counter()
    vm.scene.finish_preview()
    transform_commit = perf_counter() - sample_start
    assert len(doc.history.undo_stack) == undo_count + 1
    assert vm.scene.error == ""
    preview = viewport.source_pose
    assert preview is not None
    for mesh in doc.animation.pose.meshes.values():
        assert mesh.positions == preview.meshes[mesh.id].positions
    gaps = [b - a for a, b in zip(pulses, pulses[1:], strict=False)]
    report = {
        "first_move_callback_seconds": move_submit,
        "preview_ready_seconds": ready_seconds,
        "drop_callback_seconds": drop_submit,
        "placement_ready_seconds": placed_seconds,
        "max_ui_heartbeat_gap_seconds": max(gaps),
        "heartbeat_count": len(pulses),
        "scene_drag_frame_seconds": preview_times,
        "scene_drag_max_frame_seconds": max(preview_times),
        "scene_drag_mean_frame_seconds": sum(preview_times) / len(preview_times),
        "scene_drag_release_seconds": transform_commit,
        "assemblies": len(calls),
        "all_assembly_off_ui_thread": all(t != main_thread for t in calls),
    }
    Path("build/character-template-drag-performance.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    assert move_submit < 0.5 and drop_submit < 0.5


@pytest.mark.parametrize("vertical", (False, True))
def test_whole_character_flip_mirrors_every_part_once_and_preserves_rig(editor, qtbot, vertical):
    """Use the real toolbar with bones hidden, including feet, clothing and alternate hands."""
    vm, workspace = editor.viewmodel, editor.content_drop
    entry = next(
        e
        for e in vm.content.entries
        if e.item.category == "Characters" and e.item.name == "Dash · Runner"
    )
    workspace.drop(entry.key, QPointF(360, 260))
    qtbot.waitUntil(lambda: bool(vm.documents.scene.meshes), timeout=30000)
    qtbot.waitUntil(lambda: not workspace.placing, timeout=30000)
    assert not vm.content.error
    doc = vm.documents
    root = next(g for g in doc.scene.groups if g.extra.get("object_container"))
    assets = {a.id for a in doc.project.assets}
    qtbot.waitUntil(lambda: assets <= editor.viewport.artwork.vectors.keys(), timeout=15000)
    editor.scene_workspace.select_entries((root.id,))
    vm.scene.selection_types.discard("bones")
    before = doc.project
    bones = doc.scene.skeletons
    stages = doc.scene.deformers
    original = doc.animation.pose
    points = [
        transform_point(original.nodes[m.object_id].world_matrix, *p)
        for m in original.meshes.values()
        for p in m.positions
    ]
    axis = 1 if vertical else 0
    twice_center = min(p[axis] for p in points) + max(p[axis] for p in points)
    undo_count = len(doc.history.undo_stack)
    (
        editor.selection_properties.vertical if vertical else editor.selection_properties.horizontal
    ).click()
    assert not vm.scene.error
    assert assets <= editor.viewport.artwork.vectors.keys()
    assert doc.scene.skeletons == bones and doc.scene.deformers == stages
    assert len(doc.history.undo_stack) == undo_count + 1
    after = doc.project
    pose = doc.animation.pose
    assert not pose.warnings
    for key, mesh in original.meshes.items():
        flipped = pose.meshes[key]
        for old, new in zip(mesh.positions, flipped.positions, strict=True):
            expected = list(transform_point(original.nodes[mesh.object_id].world_matrix, *old))
            expected[axis] = twice_center - expected[axis]
            assert transform_point(pose.nodes[mesh.object_id].world_matrix, *new) == pytest.approx(
                expected
            )
    vm.undo()
    assert doc.project == before
    vm.redo()
    assert doc.project == after
    assert assets <= editor.viewport.artwork.vectors.keys()
    vm.scene.begin_preview()
    vm.scene.preview_transform(dx=75, dy=25)
    preview = vm.scene.preview
    assert preview is not None
    vm.scene.finish_preview()
    for key, mesh in pose.meshes.items():
        moved = doc.animation.pose
        a = transform_point(pose.nodes[mesh.object_id].world_matrix, *mesh.positions[0])
        b = transform_point(
            moved.nodes[mesh.object_id].world_matrix, *moved.meshes[key].positions[0]
        )
        assert b == pytest.approx((a[0] + 75, a[1] + 25))


def test_cancelled_preview_and_stale_drop_never_publish_into_another_document(
    editor, qtbot, monkeypatch
):
    """Queue a real placement, switch documents while it runs, and reject its late result."""
    from rigora.infrastructure.content_packs import read_pack

    workspace, vm = editor.content_drop, editor.viewmodel
    entry = next(e for e in vm.content.entries if e.item.name == "Dash · Runner")
    _, files = read_pack(entry.path)
    workspace.cache[entry.path] = files, {}
    gate, started = threading.Event(), threading.Event()
    original = ContentService.place

    def delayed(service, *args, **kwargs):
        """Hold the worker only, allowing the test's UI loop to change the active document."""
        started.set()
        assert gate.wait(5)
        return original(service, *args, **kwargs)

    monkeypatch.setattr(ContentService, "place", delayed)
    workspace.drop(entry.key, QPointF(300, 200))
    qtbot.waitUntil(started.is_set, timeout=5000)
    vm.new_project()
    next_project = vm.documents.project
    gate.set()
    qtbot.waitUntil(lambda: not workspace.placing, timeout=10000)
    assert vm.documents.project is next_project and not vm.documents.scene.objects
    assert not vm.documents.can_undo


def test_releasing_before_preview_finishes_reuses_the_inflight_graph(editor, qtbot, monkeypatch):
    """A quick drag/drop performs one import even when release precedes preview completion."""
    from rigora.infrastructure.content_packs import read_pack

    vm, workspace = editor.viewmodel, editor.content_drop
    entry = next(e for e in vm.content.entries if e.item.name == "Dash · Runner")
    _, files = read_pack(entry.path)
    workspace.cache[entry.path] = files, {}
    started, gate = threading.Event(), threading.Event()
    original = ContentService.place
    calls = []

    def delayed(service, *args, **kwargs):
        """Pause the worker while the UI delivers the release event."""
        calls.append(1)
        started.set()
        assert gate.wait(5)
        return original(service, *args, **kwargs)

    monkeypatch.setattr(ContentService, "place", delayed)
    baseline = vm.documents.project
    workspace.move(entry.key, QPointF(200, 200))
    qtbot.waitUntil(started.is_set, timeout=5000)
    workspace.drop(entry.key, QPointF(320, 240))
    assert vm.documents.project is baseline and workspace.placing
    gate.set()
    qtbot.waitUntil(lambda: not workspace.placing, timeout=15000)
    assert not vm.content.error and calls == [1]
    assert len(vm.documents.scene.meshes) >= 40
    assert len(vm.documents.history.undo_stack) == 1
