"""Bounded source loading, warm project switches and inactive-document ownership."""

import gc
import weakref

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF
from test_workspace_redesign_gui import editor as editor

from rigora.application_services.meshes import MeshService

pytestmark = pytest.mark.gui


def add_art(editor, color="white", count=1):
    """Register detached sources, place the first, and publish one document refresh."""
    service = MeshService(editor.viewmodel.documents)
    ids = []
    for i in range(count):
        ids.append(
            service.register_image_bytes(
                f"source-{i}.svg",
                (
                    f'<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
                    f'<rect width="100" height="100" fill="{color}"/></svg>'
                ).encode(),
            )
        )
    mesh = service.instantiate_asset(ids[0])
    editor.viewmodel.changed.emit()
    return ids, mesh


def loaded(editor, qtbot, ids):
    """Wait until every expected original source has reached its owning GUI cache."""
    qtbot.waitUntil(
        lambda: (
            set(ids).issubset(editor.viewport.artwork.images) and not editor.mesh_workspace.jobs
        ),
        timeout=15000,
    )


def test_warm_tabs_reuse_original_art_and_keep_view_selection_and_transport(
    editor, qtbot, monkeypatch
):
    """Switching tabs decodes nothing, pauses the old transport, and preserves authored data."""
    vm, viewport = editor.viewmodel, editor.viewport
    first = vm.documents
    ids, mesh_id = add_art(editor)
    loaded(editor, qtbot, ids)
    first_cache = viewport.artwork
    original = first_cache.vectors[ids[0]]
    owner = vm.mesh.service.mesh(mesh_id).object_id
    editor.scene_workspace.select_entries((owner,))
    viewport.zoom, viewport.offset = 0.7, QPointF(43, 67)
    first.animation.seek(8)
    vm.playback.play_pause()
    assert first.animation.playback.is_playing
    vm.new_project("Second")
    assert not first.animation.playback.is_playing and not vm.playback.timer.isActive()
    other_ids, _ = add_art(editor, "red")
    loaded(editor, qtbot, other_ids)
    second = vm.documents
    snapshots = [(d.project, len(d.history.undo_stack)) for d in (first, second)]
    loads = []
    submit = editor.mesh_workspace.submit

    def record(*args):
        loads.append(1)
        return submit(*args)

    monkeypatch.setattr(editor.mesh_workspace, "submit", record)
    for _ in range(3):
        vm.activate_project(0)
        assert viewport.artwork is first_cache
        assert viewport.artwork.vectors[ids[0]] is original
        assert viewport.zoom == 0.7 and viewport.offset == QPointF(43, 67)
        assert vm.scene.selected == (owner,) and first.animation.pose.frame == 8
        viewport.grab()
        vm.activate_project(1)
        assert set(other_ids).issubset(viewport.artwork.images)
        viewport.grab()
    assert not loads
    assert [(d.project, len(d.history.undo_stack)) for d in (first, second)] == snapshots


def test_loading_is_bounded_and_new_tab_takes_the_next_free_worker(editor, qtbot, monkeypatch):
    """An inactive project's many sources cannot queue ahead of current-scene artwork."""
    vm, workspace = editor.viewmodel, editor.mesh_workspace
    old = vm.documents
    reads = []
    submit = workspace.submit

    def record(job, key, importing):
        if vm.documents is old:
            reads.append(key)
        return submit(job, key, importing)

    monkeypatch.setattr(workspace, "submit", record)
    ids, _ = add_art(editor, count=12)
    assert len(workspace.jobs) <= 2
    vm.new_project("Priority")
    current, _ = add_art(editor, "blue")
    loaded(editor, qtbot, current)
    assert len(reads) <= 2
    assert set(ids[:2]).issuperset(reads)
    vm.activate_project(0)
    loaded(editor, qtbot, ids)
    assert len(reads) == len(ids)
    assert len(workspace.jobs) == 0


def test_closed_tabs_release_sources_and_selection_state_with_bounded_inactive_retention(
    editor, qtbot
):
    """Keep at most three inactive source caches and release a closed document completely."""
    vm, workspace = editor.viewmodel, editor.mesh_workspace
    for i in range(6):
        if i:
            vm.new_project(f"Project {i}")
        ids, mesh_id = add_art(editor)
        loaded(editor, qtbot, ids)
        editor.viewport.grab()
        if i == 0:
            source_reference = weakref.ref(editor.viewport.artwork.vectors[ids[0]])
        owner = vm.mesh.service.mesh(mesh_id).object_id
        editor.scene_workspace.select_entries((owner,))
        editor.viewport.offset = QPointF(i, i)
    assert len(workspace.artwork_tabs) <= 4
    assert source_reference() is None
    first = vm.workspace.documents[0]
    closed = first.session_id
    reference = weakref.ref(first)
    del first
    vm.close_project(0, discard=True)
    assert closed not in workspace.artwork_tabs
    assert (
        closed not in vm.mesh._tabs
        and closed not in vm.rig._tab_states
        and closed not in vm.scene._tabs
    )
    assert closed not in editor._view_states
    gc.collect()
    assert reference() is None
