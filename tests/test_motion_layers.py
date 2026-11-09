"""Live action layers, body masks, additive poses and source synchronization."""

import pytest
from test_object_scene_actions import composition

from rigora.application_services.animation_editing import AnimationEditingService


def test_action_layers_masks_fades_additive_solo_and_source_edits(tmp_path):
    """The same live samples survive persistence, source edits and reversible layer settings."""
    doc, chars, _, root, a, b = composition()
    pa, pb = str(chars.mesh(a).object_id), str(chars.mesh(b).object_id)
    doc.set_animation_context(root, frozenset(chars.members(root)))
    base = chars.new_motion(root, "Walk")
    edit = AnimationEditingService(doc)
    edit.key(pa, "transform.rotation", 0, 40)
    edit.key(pb, "transform.rotation", 0, 60)
    overlay = chars.new_motion(root, "Wave")
    edit.key(pa, "transform.rotation", 0, 80)
    edit.key(pb, "transform.rotation", 0, 100)
    doc.set_animation_context(None)
    chars.place_motion(root, base, 0, 3)
    segment = chars.place_motion(root, overlay, 10, 20 / doc.scene.settings.fps)
    chars.edit_segment(segment, layer=1, mask=[pa], fade_in=10, fade_out=10)
    assert doc.animation.evaluate(15).nodes[pa].local.rotation == pytest.approx(60)
    assert doc.animation.evaluate(20).nodes[pa].local.rotation == pytest.approx(80)
    assert doc.animation.evaluate(20).nodes[pb].local.rotation == pytest.approx(60)
    before = doc.project
    chars.edit_segment(segment, blend="additive", weight=0.5)
    assert doc.animation.evaluate(20).nodes[pa].local.rotation == pytest.approx(80)
    doc.undo()
    assert doc.project == before
    chars.edit_segment(segment, solo=True)
    assert doc.animation.evaluate(20).nodes[pb].local.rotation == pytest.approx(0)
    chars.edit_segment(segment, solo=False, muted=True)
    assert doc.animation.evaluate(20).nodes[pa].local.rotation == pytest.approx(40)
    chars.edit_segment(segment, muted=False)
    sequence = doc.selected_clip_id
    doc.set_animation_context(root, frozenset(chars.members(root)))
    doc.select_animation_clip(overlay)
    edit.key(pa, "transform.rotation", 0, 120)
    doc.set_animation_context(None)
    doc.select_animation_clip(sequence)
    assert doc.animation.evaluate(15).nodes[pa].local.rotation == pytest.approx(80)
    doc.save(tmp_path / "layers.rigora")
    doc.open(doc.path)
    doc.select_animation_clip(sequence)
    assert doc.animation.evaluate(15).nodes[pa].local.rotation == pytest.approx(80)


def test_scene_action_eye_and_lock_survive_source_edits(tmp_path):
    """Scene row controls mute playback and protect timing without unlocking source keys."""
    from rigora.domain.project import ProjectError

    doc, chars, _, root, a, _ = composition()
    part = str(chars.mesh(a).object_id)
    doc.set_animation_context(root, frozenset(chars.members(root)))
    source = chars.new_motion(root, "Turn")
    edit = AnimationEditingService(doc)
    edit.key(part, "transform.rotation", 0, 60)
    doc.set_animation_context(None)
    segment = chars.place_motion(root, source, 0, 2)
    track = edit.timeline.tracks[0]
    edit.track_settings(track.id, locked=True, visible=False)
    assert doc.animation.evaluate(5).nodes[part].local.rotation == 0
    before = doc.project
    for operation in (
        lambda: chars.edit_segment(segment, start=5, end=65),
        lambda: chars.remove_segment(segment),
        lambda: chars.place_motion(root, source, 60, 2),
    ):
        with pytest.raises(ProjectError, match="Unlock"):
            operation()
        assert doc.project is before
    sequence = doc.selected_clip_id
    doc.set_animation_context(root, frozenset(chars.members(root)))
    edit.key(part, "transform.rotation", 0, 90)
    doc.set_animation_context(None)
    doc.select_animation_clip(sequence)
    track = edit.timeline.tracks[0]
    assert not track.visible and track.editing_locked and track.locked
    doc.save(tmp_path / "locked-action.rigora")
    from rigora.application_services.documents import DocumentService

    loaded = DocumentService()
    loaded.open(doc.path)
    loaded.set_animation_context(None)
    loaded.select_animation_clip(sequence)
    saved = AnimationEditingService(loaded).timeline.tracks[0]
    assert not saved.visible and saved.editing_locked and saved.locked
    edit.track_settings(track.id, locked=False, visible=True)
    assert doc.animation.evaluate(5).nodes[part].local.rotation == 90
    chars.edit_segment(segment, start=2, end=62)


def test_source_eye_mutes_linked_actions_without_overwriting_scene_eye():
    """Source and Scene mute states stay independent while both affect final playback."""
    doc, chars, _, root, a, _ = composition()
    part = str(chars.mesh(a).object_id)
    doc.set_animation_context(root, frozenset(chars.members(root)))
    source = chars.new_motion(root, "Turn")
    edit = AnimationEditingService(doc)
    edit.key(part, "transform.rotation", 0, 60)
    source_track = edit.timeline.tracks[0]
    doc.set_animation_context(None)
    chars.place_motion(root, source, 0, 2)
    sequence = doc.selected_clip_id
    for enabled in (False, True):
        doc.set_animation_context(root, frozenset(chars.members(root)))
        edit.track_settings(source_track.id, locked=False, visible=enabled)
        doc.set_animation_context(None)
        doc.select_animation_clip(sequence)
        assert edit.timeline.tracks[0].visible
        assert doc.animation.evaluate(5).nodes[part].local.rotation == (60 if enabled else 0)


def test_appearance_lock_rejects_a_new_choice_group():
    """Adding another clothing group cannot bypass the compound Clothing row lock."""
    from rigora.domain.project import ProjectError

    doc, chars, _, root, a, b = composition()
    pa, pb = str(chars.mesh(a).object_id), str(chars.mesh(b).object_id)
    chars.key_appearance(root, "outfits", "shirt", "Shirt", {(pa, "visibility"): 1})
    editor = AnimationEditingService(doc)
    editor.track_settings(editor.timeline.tracks[0].id, locked=True, visible=True)
    before = doc.project
    with pytest.raises(ProjectError, match="Unlock"):
        chars.key_appearance(root, "outfits", "coat", "Coat", {(pb, "visibility"): 1})
    assert doc.project is before
