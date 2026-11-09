"""Turnaround swaps preserve one stage Object, reusable actions and view-local edits."""

from dataclasses import replace

import pytest

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_views import ObjectViewsService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.character_recipe import VIEWS, CharacterRecipe
from rigora.domain.entities import Constraint, Group, SceneObject
from rigora.domain.object_views import view_partitions
from rigora.domain.project import Scene


def test_legacy_view_constraints_follow_their_owner_instead_of_the_current_empty_slot():
    """Saved memberships missing constraints recover them in their owner's original view."""
    root = Group()
    part = SceneObject(parent_id=root.id)
    rule = Constraint(kind="parent", owner_id=part.id, target_id=root.id)
    root = replace(
        root,
        extra={
            "view_slots": True,
            "active_view": "Side",
            "view_members": {"Default": [part.id], "Side": []},
        },
    )
    scene = Scene(groups=(root,), objects=(part,), constraints=(rule,))
    result = view_partitions(scene, root)
    assert result["Default"] == {part.id, rule.id}
    assert result["Side"] == set()


def test_turnaround_preserves_stage_blocks_local_edits_and_undo():
    """Retain local edits and source bytes while evaluating only active parts."""
    doc = DocumentService()
    doc.new()
    recipe = CharacterRecipe(motions=("Idle", "Run"))
    root = CharacterCreationService(doc).create(build_character(recipe))
    service = ObjectViewsService(doc)
    SceneEditingService(doc).transform((root,), dx=35, dy=41, rotation=17)
    transform = service.root(root).transform
    clip = next(c for c in service.scene.clips if c.name == "Run")
    from rigora.application_services.animation_editing import AnimationEditingService

    doc.select_animation_clip(clip.id)
    AnimationEditingService(doc).clip_settings(name="My sprint")
    CharacterService(doc).place_motion(root, clip.id, 7, 2)
    blocks = tuple(
        t
        for t in service.scene.timelines
        if any(tr.property_path == "motion_window" for tr in t.tracks)
    )
    # A user-authored layer rename is local to this view.
    part = service.scene.objects[0]
    SceneEditingService(doc).rename(part.id, "Edited part")
    before = doc.project
    service.apply(root, service.prepare(root, "Back"))
    assert service.current(root) == "Back"
    assert service.root(root).transform == transform
    assert CharacterService(doc).scene_objects() == (root,)
    assert next(c for c in service.scene.clips if c.name == "Run").id == clip.id
    assert all(t in service.scene.timelines for t in blocks)
    assert len(service.scene.skeletons) == 1
    active_assets = {m.asset_id for m in service.scene.meshes}
    inactive = next(a.id for a in doc.project.assets if a.id not in active_assets)
    with pytest.raises(ValueError, match="in use|used by a saved Object"):
        SceneEditingService(doc).remove_asset(inactive)
    assert not doc.animation.evaluate(15).warnings
    doc.undo()
    assert doc.project == before
    doc.redo()
    service.apply(root, service.prepare(root, "Front 3/4"))
    assert any(o.name == "Edited part" for o in service.scene.objects)
    assets = len(doc.project.assets)
    service.apply(root, service.prepare(root, "Back"))
    service.apply(root, service.prepare(root, "Front 3/4"))
    assert len(doc.project.assets) == assets
    assert len(service.scene.skeletons) == 1


def test_little_preset_stature_is_smaller_than_tall_preset():
    """Measure authored preset geometry rather than auto-fit camera zoom."""
    from rigora.domain.illustration_catalog import design_by_id
    from rigora.infrastructure.illustration_motion import world_joints

    def height(identity):
        joints = world_joints(design_by_id(identity), "Front 3/4", rest=True)
        points = [v[1] for joint in joints.values() for v in (joint.root, joint.tip)]
        return max(points) - min(points)

    assert height("dot") < height("luca") * 0.85


def test_five_views_restore_edits_after_save_and_portable_import(tmp_path):
    """Opaque compressed snapshots resolve remapped assets when shared with another document."""
    from rigora.application_services.content_library import ContentService
    from rigora.domain.content import ContentItem

    doc = DocumentService()
    doc.new()
    root = CharacterCreationService(doc).create(build_character(CharacterRecipe(motions=())))
    views = ObjectViewsService(doc)
    for view in VIEWS:
        views.apply(root, views.prepare(root, view))
        assert views.current(root) == view
    path = tmp_path / "turnaround.rigora"
    doc.save(path)
    loaded = DocumentService()
    loaded.open(path)
    views = ObjectViewsService(loaded)
    views.apply(root, views.prepare(root, "Front 3/4"))
    assert not loaded.animation.pose.warnings
    files = {a.id: loaded.read_asset(a.id) for a in loaded.project.assets}
    item = ContentItem(
        name="Portable turnaround",
        author="Rigora contributors",
        license="CC0-1.0",
        kind="scene",
        category="Characters",
        payload={"project": loaded.project.to_dict(), "sources": {k: k for k in files}},
    )
    other = DocumentService()
    other.new()
    ContentService(other).apply(item, files)
    assert {a.id for a in loaded.project.assets}.isdisjoint(a.id for a in other.project.assets)
    root2 = next(g.id for g in other.project.scenes[0].groups if g.extra.get("character_recipe"))
    views = ObjectViewsService(other)
    for view in ("Back", "Front 3/4", "Back 3/4"):
        views.apply(root2, views.prepare(root2, view))
        assert views.current(root2) == view
        assert not other.animation.pose.warnings


@pytest.mark.parametrize(
    "saved",
    [None, {"codec": "zlib+base64", "data": 42}, {"codec": "zlib+base64", "data": "invalid"}],
)
def test_invalid_view_descriptor_is_a_project_error(saved):
    """Malformed portable metadata must fail before it can replace the active Object."""
    from rigora.application_services.object_views import decode_view
    from rigora.domain.project import ProjectError

    doc = DocumentService()
    doc.new()
    with pytest.raises(ProjectError):
        decode_view(saved, doc)
