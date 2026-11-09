"""Object-local actions and saved looks placed above global scene animation."""

from pathlib import Path

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rigging import RigService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import inverse, multiply, transform_point


def composition():
    """Build two independent vector parts in a solid Object without introducing a rig."""
    document = DocumentService()
    document.new()
    service, look = CharacterService(document), AppearanceService(document)
    a = look.create_shape("ellipse", 200, 200, 100, 100)
    b = look.create_shape("rectangle", 400, 200, 100, 100)
    root = service.create_object(tuple(str(service.mesh(k).object_id) for k in (a, b)))
    return document, service, look, root, a, b


def test_scene_and_object_cursors_and_independent_named_timelines():
    document, service, _, root, a, _ = composition()
    document.set_animation_context(None)
    editor = AnimationEditingService(document)
    editor.auto_key_values({(root, "transform.x"): 600}, 20)
    main = editor.clip.id
    document.animation.seek(17)
    revision = document.project
    document.set_animation_context(root, frozenset(service.members(root)))
    assert document.selected_clip_id is None and not document.animation.pose.clip_id
    assert document.project is revision
    idle = service.new_motion(root, "Idle")
    part = str(service.mesh(a).object_id)
    editor.auto_key_values({(part, "transform.rotation"): 10}, 0)
    document.animation.seek(9)
    walk = service.new_motion(root, "Walk")
    assert not editor.timeline.tracks
    editor.auto_key_values({(part, "transform.rotation"): 60}, 15)
    document.select_animation_clip(idle)
    document.animation.seek(9)
    document.select_animation_clip(walk)
    document.animation.seek(12)
    document.select_animation_clip(idle)
    assert document.animation.pose.frame == 9
    assert document.animation.pose.nodes[part].local.rotation == 10
    document.set_animation_context(None)
    assert document.selected_clip_id == main and document.animation.pose.frame == 17
    assert {c.id for c in document.context_clips()} == {main}
    document.set_animation_context(root, frozenset(service.members(root)))
    assert document.selected_clip_id == idle and document.animation.pose.frame == 9
    assert {c.id for c in document.context_clips()} == {idle, walk}


def test_object_scope_skips_other_meshes_and_owns_empty_object_bones():
    document, service, look, root, a, b = composition()
    background = look.create_shape("star", 700, 300, 300, 300)
    document.set_animation_context(root, frozenset(service.members(root)))
    assert set(document.animation.pose.meshes) == {a, b}
    assert background not in document.animation.pose.meshes
    other = service.create_object(name="Rig only")
    document.set_animation_context(other, frozenset(service.members(other)))
    rig = RigService(document)
    bone = rig.create_bone((100, 100), (180, 100))
    document.set_animation_context(other, frozenset(service.members(other)))
    assert bone in service.members(other)
    assert service.object_root(bone).id == other
    assert set(document.animation.pose.meshes) == set()
    assert not any(c in service.scene_objects() for c in (a, b, bone))
    document.set_animation_context(None)
    assert set(document.animation.pose.meshes) == {a, b, background}


def test_saved_skin_and_clothing_keys_in_both_workspaces_and_roundtrip(tmp_path: Path):
    document, service, look, root, a, b = composition()
    document.set_animation_context(root, frozenset(service.members(root)))
    group = service.skin_group(root, "Palette")
    original = service.save_skin(root, group, (a,), "Original")
    look.edit((a,), {"tint.r": 255, "tint.g": 0, "tint.b": 0, "tint.amount": 0.5})
    warm = service.save_skin(root, group, (a,), "Warm")
    service.appearance_default(root, "skins", group, original)
    service.apply_skin(root, group, original)
    outfits = service.wardrobe_group(root, "Dress")
    service.add_variant(root, outfits, (b,), "Blue dress")
    variant = service.record(root).extra["outfits"][0]["variants"][0]["id"]
    idle = service.new_motion(root, "Idle")
    document.animation.seek(10)
    service.apply_skin(root, group, warm, auto_key=True)
    service.show_variant(root, outfits, None, False, auto_key=True)
    assert document.animation.evaluate(9).meshes[a].appearance["tint"]["amount"] == 0
    assert document.animation.evaluate(10).meshes[a].appearance["tint"]["amount"] == 0.5
    part = str(service.mesh(b).object_id)
    assert document.animation.evaluate(9).nodes[part].visible
    assert not document.animation.evaluate(10).nodes[part].visible
    document.set_animation_context(None)
    segment = service.place_motion(root, idle, 0, 2)
    scene_clip = document.selected_clip_id
    document.animation.seek(20)
    service.apply_skin(root, group, original, auto_key=True)
    service.show_variant(root, outfits, variant, True, auto_key=True)
    assert document.animation.evaluate(19).meshes[a].appearance["tint"]["amount"] == 0.5
    service.edit_segment(segment, speed=0.5)
    assert document.animation.evaluate(20).meshes[a].appearance["tint"]["amount"] == 0
    assert document.animation.evaluate(20).nodes[part].visible
    service.place_motion(root, idle, 60, 2, speed=2)
    assert document.animation.evaluate(70).meshes[a].appearance["tint"]["amount"] == 0
    assert service.motions(root)[0].id == idle
    document.save(tmp_path / "actions.rigora")
    loaded = DocumentService()
    loaded.open(tmp_path / "actions.rigora")
    loaded.set_animation_context(None)
    assert loaded.selected_clip_id == scene_clip
    assert loaded.animation.evaluate(20).nodes[part].visible
    assert CharacterService(loaded).record(root).extra["skins"][0]["default"] == original
    assert not service.scene.characters


def test_keyed_choices_have_single_undo_and_no_mesh_or_bone_tracks_in_main_catalog():
    document, service, _, root, a, _ = composition()
    group = service.skin_group(root, "Colors")
    variant = service.save_skin(root, group, (a,), "Default")
    document.set_animation_context(None)
    document.animation.seek(10)
    before = document.project
    count = len(document.history.undo_stack)
    service.apply_skin(root, group, variant, auto_key=True)
    assert len(document.history.undo_stack) == count + 1
    document.undo()
    assert document.project == before
    with pytest.raises(ValueError, match="existing skin"):
        service.apply_skin(root, group, "not-an-option")


def test_editing_source_updates_placed_blocks_and_global_transform_stays_editable():
    """Source edits refresh instances; global keys remain above their locked source layers."""
    document, service, _, root, a, _ = composition()
    document.set_animation_context(root, frozenset(service.members(root)))
    source = service.new_motion(root, "Walk")
    editor = AnimationEditingService(document)
    part = str(service.mesh(a).object_id)
    editor.key(part, "transform.rotation", 0, 0)
    editor.key(part, "transform.rotation", 30, 60)
    editor.key(root, "transform.x", 0, 300)
    editor.key(root, "transform.x", 30, 600)
    document.set_animation_context(None)
    segment = service.place_motion(root, source, 0, 2, speed=0.5)
    document.animation.seek(20)
    editor.auto_key_values({(root, "transform.x"): 750}, 20)
    assert document.animation.pose.nodes[root].local.x == 750
    document.set_animation_context(root, frozenset(service.members(root)))
    editor.key(part, "transform.rotation", 30, 120)
    document.set_animation_context(None)
    assert document.animation.evaluate(20).nodes[part].local.rotation == 40
    assert document.animation.evaluate(20).nodes[root].local.x == 750
    window = next(
        t.extra["motion_window"] for t in editor.timeline.tracks if t.extra.get("motion_window")
    )
    assert window["id"] == segment and window["speed"] == 0.5
    document.animation.seek(25)
    document.set_animation_context(root, frozenset(service.members(root)))
    document.set_animation_context(None, prepare=False)
    assert document._animation is None
    assert document.animation.pose.frame == 25


def test_legacy_character_skin_presets_and_vertex_actions_place_completely():
    """Explicit image characters retain skin snapshots and all vertex animation channels."""
    document = DocumentService()
    document.new()
    look = AppearanceService(document)
    mesh = look.create_shape("ellipse", 100, 100, 60, 80)
    actor = ImageRigService(document).convert((mesh,))
    service = CharacterService(document)
    document.set_animation_context(actor, frozenset(service.members(actor)))
    group = service.skin_group(actor, "Colors")
    variant = service.save_skin(actor, group, (mesh,), "Default")
    clip = service.new_motion(actor, "Sculpt")
    vertex = service.mesh(mesh).vertices[0]
    animation = AnimationEditingService(document)
    animation.key(vertex.id, "x", 0, vertex.x)
    animation.key(vertex.id, "x", 20, vertex.x + 10)
    service.apply_skin(actor, group, variant, auto_key=True)
    source = document.animation.evaluate(20).meshes[mesh].positions
    service.place_motion(actor, clip, 0, 2)
    assert document.animation_context is None
    assert document.animation.evaluate(20).meshes[mesh].positions == source


def test_scene_object_translation_keeps_source_bone_bounce_and_rotation():
    """Global positioning wraps the skinned action rather than replacing its root-bone keys."""
    document, service, _, root, mesh, _ = composition()
    document.set_animation_context(root, frozenset(service.members(root)))
    images = ImageRigService(document)
    bone = images.draw_bone(mesh, (200, 200), (250, 200))
    document.set_animation_context(root, frozenset(service.members(root)))
    source = service.new_motion(root, "Bounce")
    animation = AnimationEditingService(document)
    animation.key(bone, "transform.y", 0, 200)
    animation.key(bone, "transform.y", 30, 220)
    animation.key(bone, "transform.rotation", 0, 0)
    animation.key(bone, "transform.rotation", 30, 25)
    service.place_motion(root, source, 0, 2)

    def world(frame):
        pose = document.animation.evaluate(frame)
        return [
            transform_point(pose.nodes[str(service.mesh(mesh).object_id)].world_matrix, *p)
            for p in pose.meshes[mesh].positions
        ]

    before = world(30)
    scene = SceneEditingService(document)
    scene.auto_key = scene.part_edit = True
    scene.transform((root,), dx=100, dy=50)
    for actual, (x, y) in zip(world(30), before, strict=True):
        assert actual == pytest.approx((x + 100, y + 50))
    before = world(30)
    old_matrix = document.animation.evaluate(30).nodes[root].world_matrix
    scene.transform((root,), rotation=30, scale_x=1.2, scale_y=1.2)
    delta = multiply(document.animation.evaluate(30).nodes[root].world_matrix, inverse(old_matrix))
    for actual, point in zip(world(30), before, strict=True):
        assert actual == pytest.approx(transform_point(delta, *point))
    assert not any(
        t.owner_id == bone and not t.extra.get("motion_window") for t in animation.timeline.tracks
    )
