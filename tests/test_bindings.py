"""Real relationship edits preserve endpoints, ownership and unrelated motion."""

import pytest

from rigora.api import RigoraAPI
from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.bindings import BindingService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.project import ProjectError


@pytest.fixture
def character():
    """Create a two-part character by drawing actual image-bound bones."""
    doc = DocumentService()
    doc.new()
    shapes = AppearanceService(doc)
    first = shapes.create_shape("rectangle", 100, 100, 100, 150)
    second = shapes.create_shape("ellipse", 200, 150, 100, 100)
    images = ImageRigService(doc)
    actor = images.convert((first, second), "Character")
    root = images.draw_bone(first, (120, 130), (180, 130))
    child = images.draw_bone(first, (180, 130), (240, 150), root)
    return doc, images, actor, first, second, root, child


def test_unbind_artwork_keeps_composer_membership_and_does_not_rebind_on_draw(character):
    """Unbinding the anchor part leaves bones visible and later drawing honors that choice."""
    doc, images, actor, first, second, root, _ = character
    before = doc.project
    count = len(doc.history.undo_stack)
    images.detach((first,))
    assert len(doc.history.undo_stack) == count + 1
    assert not any(d.owner_id == first and d.kind == "skinning" for d in images.scene.deformers)
    owner = next(c for c in images.scene.characters if c.id == actor)
    assert owner.mesh_ids == (first, second)
    assert images.mesh(first).object_id in owner.object_ids
    assert RigService(doc).bone(root)
    doc.undo()
    assert doc.project == before
    doc.redo()
    images.draw_bone(second, (180, 130), (180, 220), root)
    assert len(images.scene.characters) == 1
    assert not any(d.owner_id == first and d.kind == "skinning" for d in images.scene.deformers)
    BindingService(doc).bind((first,), root)
    assert any(d.owner_id == first and d.kind == "skinning" for d in images.scene.deformers)
    assert images.mesh(first).extra["auto_bind_artwork"]


def test_unbind_one_bone_preserves_other_influences_and_cleans_physics(character):
    """A selected bone loses its connections, not every binding on the same mesh."""
    doc, images, _, first, _, root, child = character
    dynamics = DynamicsService(doc)
    dynamics.configure((root, child), group="Hair")
    dynamics.activation("Hair", False, 8)
    dynamics.activation("Hair", True, 0, master=True)
    animator = AnimationEditingService(doc)
    animator.key(child, "transform.rotation", 0, 12)
    animator.key(child, "transform.rotation", 12, 20)
    images.add_area_pin(first, (50, 50), child)
    before = doc.project
    count = len(doc.history.undo_stack)
    original_bones = {b.id for r in images.scene.skeletons for b in r.bones}
    BindingService(doc).unbind((child,))
    assert {b.id for r in images.scene.skeletons for b in r.bones} == original_bones
    master = next(b for b in images.scene.skeletons[0].bones if b.extra.get("rig_root"))
    assert RigService(doc).bone(child).parent_id == master.id
    assert all(child not in v.weights for m in images.scene.meshes for v in m.vertices)
    assert all(
        set(d.parameters["bind_matrices"]) == {root}
        for d in images.scene.deformers
        if d.kind == "skinning"
    )
    assert not images.mesh(first).extra["area_pins"]
    assert {c.owner_id for c in images.scene.constraints if c.kind == "spring"} == {root}
    assert not any(
        t.owner_id == child and t.property_path.startswith("spring.")
        for tl in images.scene.timelines
        for t in tl.tracks
    )
    assert any(
        t.owner_id == child and t.property_path == "transform.rotation"
        for tl in images.scene.timelines
        for t in tl.tracks
    )
    assert any(
        t.property_path == "spring.master" for tl in images.scene.timelines for t in tl.tracks
    )
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before


def test_partial_skin_release_stays_released_after_drawing(character):
    """Automatic weighting excludes an explicitly removed influence until manual rebinding."""
    doc, images, _, first, _, root, child = character
    bindings = BindingService(doc)
    row = next(
        r
        for r in bindings.relationships()
        if r.kind == "Skin" and r.source == first and r.target == child
    )
    bindings.remove_relationships((row.id,))
    new_bone = images.draw_bone(first, (240, 150), (260, 200), child)
    stage = next(d for d in images.scene.deformers if d.owner_id == first and d.kind == "skinning")
    assert set(stage.parameters["bind_matrices"]) == {root, new_bone}
    assert all(child not in v.weights for v in images.mesh(first).vertices)
    images.bind_image(first, root)
    assert (
        child
        in next(
            d for d in images.scene.deformers if d.owner_id == first and d.kind == "skinning"
        ).parameters["bind_matrices"]
    )


def test_last_artwork_unbind_removes_spring_controls_but_not_bones(character):
    """The last skin release clears live physics and activation, including root master keys."""
    doc, images, actor, first, second, root, child = character
    dynamics = DynamicsService(doc)
    dynamics.configure((root, child), group="Hair")
    dynamics.activation("Hair", False, 8)
    dynamics.activation("Hair", True, 0, master=True)
    images.detach((first, second))
    assert not images.scene.constraints
    assert all(
        not t.property_path.startswith("spring.")
        for tl in images.scene.timelines
        for t in tl.tracks
    )
    assert len([b for b in images.scene.skeletons[0].bones if not b.extra.get("rig_root")]) == 2
    assert len([b for b in images.scene.skeletons[0].bones if b.extra.get("rig_root")]) == 1
    assert next(c for c in images.scene.characters if c.id == actor).mesh_ids == (first, second)
    assert RigService(doc).bone(child).parent_id == root


def test_sprite_to_sprite_binding_follows_target_and_unbind_keeps_world(character):
    """Rigid image/shape links use real evaluated transforms and preserve appearance on release."""
    doc, images, _, first, second, _, _ = character
    bindings = BindingService(doc)
    source, target = str(images.mesh(first).object_id), str(images.mesh(second).object_id)
    start = doc.animation.pose.nodes[source].world_matrix
    bindings.bind((source,), target)
    assert doc.animation.pose.nodes[source].world_matrix == pytest.approx(start)
    bindings.transform((target,), dx=50, dy=25)
    moved = doc.animation.pose.nodes[source].world_matrix
    assert moved[4:] == pytest.approx((start[4] + 50, start[5] + 25))
    target_start = doc.animation.pose.nodes[target].world_matrix
    bindings.transform((source,), dx=-20, dy=10)
    moved = doc.animation.pose.nodes[source].world_matrix
    assert moved[4:] == pytest.approx((start[4] + 30, start[5] + 35))
    assert doc.animation.pose.nodes[target].world_matrix[4:] == pytest.approx(
        (target_start[4] - 20, target_start[5] + 10)
    )
    before, count = doc.project, len(doc.history.undo_stack)
    bindings.unbind((source,))
    assert not any(c.owner_id == source for c in images.scene.constraints)
    assert doc.animation.pose.nodes[source].world_matrix == pytest.approx(moved)
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before


def test_remove_every_inspected_binding_preserves_object_membership(character):
    """Structural containment is not a removable binding, including nested part folders."""
    doc, images, _, first, second, _, _ = character
    bindings = BindingService(doc)
    sources = tuple(str(images.mesh(k).object_id) for k in (first, second))
    owner = CharacterService(doc).create_object(sources, "Object")
    folder = bindings.group(sources, "Parts")
    bindings.move_entries((folder,), owner)
    before, count = doc.project, len(doc.history.undo_stack)
    identities = tuple(row.id for row in bindings.relationships())
    assert f"parent:{folder}" not in identities
    bindings.remove_relationships(identities)
    assert not bindings.relationships()
    assert {CharacterService(doc).object_root(k).id for k in sources} == {owner}
    assert len(doc.history.undo_stack) == count + 1
    assert not doc.animation.pose.warnings
    doc.undo()
    assert doc.project == before


def test_binding_groups_partition_connections_without_structural_membership(character):
    """Every connection occurs in exactly one expandable connected component."""
    doc, images, _, first, second, _, _ = character
    bindings = BindingService(doc)
    sources = tuple(str(images.mesh(k).object_id) for k in (first, second))
    CharacterService(doc).create_object(sources, "Object")
    bindings.bind((sources[0],), sources[1])
    groups = bindings.groups()
    rows = [row for group in groups for row in group]
    assert set(rows) == set(bindings.relationships())
    assert len(rows) == len(set(rows))
    link = next(row for row in rows if row.id.startswith("constraint:"))
    component = next(group for group in groups if link in group)
    assert any(row.source in (first, second) for row in component)


def test_object_editing_cannot_move_an_external_binding_driver(character):
    """Reference-only outside objects cannot be authored through an inside follower drag."""
    doc, images, _, first, second, _, _ = character
    bindings = BindingService(doc)
    source, target = (str(images.mesh(k).object_id) for k in (first, second))
    root = CharacterService(doc).create_object((source,), "Editing")
    bindings.bind((source,), target)
    doc.set_animation_context(root, frozenset((root, source, first)))
    before = doc.project
    with pytest.raises(ProjectError, match="outside this Object"):
        bindings.transform((source,), dx=10)
    assert doc.project is before


def test_binding_cycle_and_locked_source_roll_back_every_change(character):
    """Rejected relationships do not leave detached skinning or partially changed rigs."""
    doc, images, _, first, second, root, child = character
    bindings = BindingService(doc)
    source, target = str(images.mesh(first).object_id), str(images.mesh(second).object_id)
    bindings.bind((source,), target)
    before, count = doc.project, len(doc.history.undo_stack)
    with pytest.raises(ProjectError, match="cycle"):
        bindings.bind((target,), source)
    assert doc.project == before and len(doc.history.undo_stack) == count
    with pytest.raises(ProjectError, match="cycle"):
        bindings.bind((root,), child)
    assert doc.project == before
    bindings.flags((source,), locked=True)
    before = doc.project
    with pytest.raises(ProjectError, match="Unlock"):
        bindings.unbind((source,))
    assert doc.project == before


def test_bone_parent_release_retains_children_and_rest_geometry(character):
    """Unbinding a parent bone does not disconnect its children from that bone."""
    doc, images, _, first, _, root, child = character
    tip = images.draw_bone(first, (240, 150), (260, 200), child)
    before = RigService(doc).rest_pose().nodes[child].world_matrix
    BindingService(doc).unbind((child,))
    assert RigService(doc).bone(tip).parent_id == child
    assert RigService(doc).rest_pose().nodes[child].world_matrix == pytest.approx(before)
    assert RigService(doc).bone(root)


def test_bindings_api_shares_inspection_undo_and_persistence(character, tmp_path):
    """Python/CLI/MCP operations use the canonical service, with dry-run and save/reopen."""
    doc, images, _, first, second, _, _ = character
    api = RigoraAPI(tmp_path, document=doc)
    source, target = str(images.mesh(first).object_id), str(images.mesh(second).object_id)
    before = doc.project
    api.execute("binding_create", {"sources": [source], "target": target}, dry_run=True)
    assert doc.project is before
    result = api.execute("binding_create", {"sources": [source], "target": target})
    row = next(
        r for r in result.data["bindings"] if r["source"] == source and r["kind"] == "Parent"
    )
    api.execute("project_save", {"path": "bound.rigora"})
    clone = RigoraAPI(tmp_path)
    clone.execute("project_open", {"path": "bound.rigora"})
    assert row in clone.execute("bindings_inspect").data["bindings"]
    clone.execute("binding_remove", {"relationships": [row["id"]]})
    assert row not in clone.execute("bindings_inspect").data["bindings"]
    clone.execute("undo")
    assert row in clone.execute("bindings_inspect").data["bindings"]


def test_unbind_artwork_keeps_its_layer_folder_and_future_draw_policy(character):
    """Releasing skinning does not extract a part from its object or parts folder."""
    doc, images, _, first, second, root, _ = character
    source, other = str(images.mesh(first).object_id), str(images.mesh(second).object_id)
    service = BindingService(doc)
    folder = CharacterService(doc).create_object((source, other), "Object")
    service.unbind((source,))
    assert service.record(source).parent_id == folder
    images.draw_bone(first, (120, 130), (120, 200), root)
    assert not any(d.kind == "skinning" and d.owner_id == first for d in images.scene.deformers)


def test_unbind_before_first_bone_is_respected(character):
    """An explicit unbound choice also survives when a converted actor has no bones yet."""
    doc, images, _, _, _, _, _ = character
    mesh = AppearanceService(doc).create_shape("ellipse", 400, 400, 100, 100)
    actor = images.convert((mesh,), "Unbound")
    BindingService(doc).unbind((mesh,))
    bone = images.draw_bone(mesh, (420, 420), (480, 420))
    assert RigService(doc).bone(bone)
    assert not any(d.kind == "skinning" and d.owner_id == mesh for d in images.scene.deformers)
    assert next(c for c in images.scene.characters if c.id == actor).mesh_ids == (mesh,)


def test_folder_rebinding_releases_nested_rigid_attachments(character):
    """Binding a folder to a rig clears its children's previous rigid links first."""
    doc, images, _, first, second, root, _ = character
    source, other = str(images.mesh(first).object_id), str(images.mesh(second).object_id)
    service = BindingService(doc)
    folder = service.group((source, other), "Parts")
    target = AppearanceService(doc).create_shape("rectangle", 500, 400, 100, 100)
    service.bind((first,), target)
    assert any(c.owner_id == source and c.kind == "parent" for c in images.scene.constraints)
    service.bind((folder,), root)
    assert not any(c.owner_id == source and c.kind == "parent" for c in images.scene.constraints)
    assert {first, second} <= {d.owner_id for d in images.scene.deformers if d.kind == "skinning"}


def test_weight_panel_explicit_binding_also_clears_the_unbound_policy(character):
    """The lower-level Bind action and automatic drawing share the same policy lifecycle."""
    doc, images, _, first, _, root, child = character
    images.detach((first,))
    SkinService(doc).bind(first, (root, child))
    assert images.mesh(first).extra["auto_bind_artwork"]
    assert "unbound_bones" not in images.mesh(first).extra
    new_bone = images.draw_bone(first, (180, 130), (180, 240), root)
    assert any(new_bone in v.weights for v in images.mesh(first).vertices)
