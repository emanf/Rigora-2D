"""Independent scenes retain authored data while sharing only project assets and history."""

from dataclasses import replace
from unittest.mock import patch

import pytest

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.documents import AnimationSession, DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.project import ProjectError


def test_only_active_scene_has_runtime_and_edits_persist_in_the_correct_scene(tmp_path):
    """Adding an inactive scene compiles nothing; activation discards the previous runtime."""
    doc = DocumentService()
    doc.new()
    first = doc.scene.id
    first_shape = AppearanceService(doc).create_shape("rectangle", 10, 10, 30, 30)
    with patch(
        "rigora.application_services.documents.AnimationSession", wraps=AnimationSession
    ) as compile_scene:
        original = doc.animation
        original.seek(7)
        second = doc.add_scene()
        assert compile_scene.call_count == 1
        assert doc.scene.id == first
        doc.select_scene(second)
        assert doc._animation is None and not original.playback.is_playing
        second_shape = AppearanceService(doc).create_shape("ellipse", 50, 50, 30, 30)
        assert doc.animation.scene.id == second
        assert {m.id for m in doc.scene.meshes} == {second_shape}
        first_scene = next(s for s in doc.project.scenes if s.id == first)
        service = SceneEditingService(doc)
        owner = str(service.mesh(second_shape).object_id)
        scratch = doc.fork()
        SceneEditingService(scratch).transform((owner,), dx=15)
        assert scratch.scene.id == second
        assert next(s for s in scratch.project.scenes if s.id == first) is first_scene
        SceneEditingService(doc).rename_scene("Reference scene", first)
        assert doc.scene.id == second
        doc.animation.seek(19)
        assert all(call.args[0].id in (first, second) for call in compile_scene.call_args_list)
        doc.select_scene(first)
        assert doc._animation is None
        assert doc.animation.pose.frame == 7
        assert {m.id for m in doc.scene.meshes} == {first_shape}
        doc.select_scene(second)
        assert doc.animation.pose.frame == 19
    path = tmp_path / "scenes.rigora"
    doc.save(path)
    clone = DocumentService()
    clone.open(path)
    assert [s.name for s in clone.project.scenes] == ["Reference scene", "Scene 02"]
    clone.select_scene(second)
    assert {m.id for m in clone.scene.meshes} == {second_shape}


def test_scene_add_delete_undo_and_settings_never_touch_an_inactive_scene():
    """History restores complete scenes; deleting the last scene is rejected."""
    doc = DocumentService()
    doc.new()
    first = doc.scene
    second = doc.add_scene()
    doc.select_scene(second)
    assert doc.animation.scene.id == second
    doc.undo()
    assert doc.scene.id == first.id and doc._animation is None
    doc.redo()
    doc.select_scene(second)
    doc.update_settings("Project", "Close up", replace(doc.scene.settings, width=640))
    assert doc.scene.settings.width == 640
    assert next(s for s in doc.project.scenes if s.id == first.id) is first
    before = doc.project
    doc.delete_scene(second)
    assert doc.scene.id == first.id and len(doc.project.scenes) == 1
    doc.undo()
    assert doc.project == before
    doc.redo()
    with pytest.raises(ProjectError, match="at least one"):
        doc.delete_scene(first.id)


def test_scene_switch_from_object_context_restores_the_main_scene_cursor():
    """An object's local motion frame never becomes the paused main scene frame."""
    doc = DocumentService()
    doc.new()
    first = doc.scene.id
    owner = SceneEditingService(doc).group()
    second = doc.add_scene()
    doc.animation.seek(12)
    doc.set_animation_context(owner, frozenset((owner,)))
    doc.animation.seek(40)
    doc.select_scene(second)
    doc.select_scene(first)
    assert doc.animation_context is None
    assert doc.animation.pose.frame == 12
