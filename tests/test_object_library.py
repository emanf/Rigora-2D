"""Linked Object ownership, per-scene overrides, clipboard identity and persistence checks."""

from dataclasses import replace

import pytest

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.commands import ScenePatch
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.object_library import LINK, ObjectLibraryService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import Keyframe, Timeline, Track, nested_records
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.domain.validation import frozen_extra
from rigora.infrastructure.content_packs import read_pack


def example():
    """Create a compound object with one editable vector part through ordinary services."""
    doc = DocumentService()
    doc.new()
    mesh = AppearanceService(doc).create_shape("rectangle", 100, 120, 80, 100)
    characters = CharacterService(doc)
    part = characters.mesh(mesh).object_id
    root = characters.create_object((part,), "Hero")
    key = characters.record(root).extra[LINK]["definition"]
    return doc, ObjectLibraryService(doc), root, part, key


def test_asset_edit_snapshot_publishes_new_parts_without_extra_scene_instances_and_undoes():
    """An isolated source editor shares contents and new bytes, retaining placed transforms."""
    doc, library, root, part, key = example()
    peer = library.place(key, (700, 500))
    peer_transform = CharacterService(doc).record(peer).transform
    snapshot, edited = library.edit_snapshot(key)
    baseline = doc.project
    assert len(doc.scene.groups) == 2
    expected = library.entries()[key]
    new_mesh = AppearanceService(snapshot).create_shape("ellipse", 10, 20, 70, 40)
    CharacterService(snapshot).add_object_parts(edited, (new_mesh,))
    library.publish_snapshot(key, snapshot, expected)
    assert len(doc.scene.groups) == 2
    assert len(doc.scene.meshes) == 4
    assert len(doc.project.assets) == 2
    assert doc.read_asset(snapshot.scene.meshes[-1].asset_id)
    assert CharacterService(doc).record(peer).transform == peer_transform
    doc.undo()
    assert doc.project == baseline


def test_edit_and_publish_unplaced_asset_and_reject_conflicting_source_edits():
    """Removing placements does not remove the asset or require materialization to edit it."""
    doc, library, root, part, key = example()
    library.remove_scene_instances((key,))
    assert not doc.scene.objects and not doc.scene.groups
    snapshot, edited = library.edit_snapshot(key)
    expected = library.entries()[key]
    SceneEditingService(snapshot).rename(edited, "Edited asset")
    library.publish_snapshot(key, snapshot, expected)
    assert not doc.scene.objects and not doc.scene.groups
    assert library.entries()[key]["name"] == "Edited asset"
    with pytest.raises(ProjectError, match="changed elsewhere"):
        library.publish_snapshot(key, snapshot, expected)


def test_object_package_round_trip_into_another_project_keeps_rig_looks_and_actions(tmp_path):
    """Packages contain only referenced portable sources and import without scene placement."""
    from rigora.application_services.animation_editing import AnimationEditingService
    from rigora.application_services.rigging import RigService
    from rigora.application_services.skinning import SkinService

    doc, library, root, part, key = example()
    members = CharacterService(doc).members(root)
    doc.set_animation_context(root, frozenset(members))
    rig = RigService(doc)
    bone = rig.create_bone((100, 120), (180, 120))
    child = rig.create_bone((180, 120), (220, 140), bone)
    mesh = next(m.id for m in doc.scene.meshes if m.object_id == part)
    SkinService(doc).bind(mesh, (bone, child))
    AnimationEditingService(doc).key(child, "transform.rotation", 0, 0)
    AnimationEditingService(doc).key(child, "transform.rotation", 24, 45)
    AppearanceService(doc).edit((mesh,), {"tint.amount": 1, "tint.r": 1, "tint.g": 0, "tint.b": 0})
    doc.set_animation_context(None)
    AppearanceService(doc).create_shape("ellipse", 700, 500, 30, 30)
    path = tmp_path / "hero.rigpack"
    before = doc.project
    library.export_package((key,), path, category="My game heroes")
    assert doc.project == before
    pack, files = read_pack(path)
    assert pack.items[0].category == "My game heroes"
    assert len(pack.items[0].payload["sources"]) == 1
    other = DocumentService()
    other.new()
    target = ObjectLibraryService(other)
    scene = other.scene
    imported = target.import_package(path)
    assert other.scene == scene and len(imported) == 1
    assert len(other.project.assets) == 1
    placed = target.place(imported[0])
    assert placed and len(other.scene.skeletons[0].bones) == 3
    assert sum(bool(b.extra.get("rig_root")) for b in other.scene.skeletons[0].bones) == 1
    assert any(t.keyframes for line in other.scene.timelines for t in line.tracks)
    assert any(d.kind == "skinning" for d in other.scene.deformers)
    assert any(
        d.kind == "appearance" and d.parameters["tint"]["r"] == 1 for d in other.scene.deformers
    )
    assert other.read_asset(other.project.assets[0].id)
    other.undo()
    other.undo()
    assert not target.entries() and not other.project.assets and other.scene == scene


def test_linked_edits_keep_scene_overrides_and_atomic_undo_and_survive_reload(tmp_path):
    """Shared part edits reach an inactive scene without evaluating it or changing placement."""
    doc, library, root, part, key = example()
    first = doc.scene.id
    second = doc.add_scene("Second")
    doc.select_scene(second)
    copy = library.place(key, (500, 300))
    copies = SceneEditingService(doc)
    copy_part = copies.record(copy).extra[LINK]["ids"][part]
    copies.transform((copy,), dx=50, rotation=15, scale_x=1.2, scale_y=0.8)
    copies.flags((copy,), visible=False)
    entry = copies.record(copy)
    copies.update_records({copy: replace(entry, extra={**entry.extra, "opacity": 0.35})}, "Opacity")
    local = copies.record(copy)
    doc.select_scene(first)
    before, count = doc.project, len(doc.history.undo_stack)
    SceneEditingService(doc).rename(part, "Shared sleeve")
    assert doc._animation is None
    inactive = next(s for s in doc.project.scenes if s.id == second)
    assert next(o for o in inactive.objects if o.id == copy_part).name == "Shared sleeve"
    assert next(g for g in inactive.groups if g.id == copy) == local
    assert len(doc.history.undo_stack) == count + 1
    changed = doc.project
    doc.undo()
    assert doc.project == before
    doc.redo()
    assert doc.project == changed
    doc.save(tmp_path / "linked.rigora")
    loaded = DocumentService()
    loaded.open(tmp_path / "linked.rigora")
    assert loaded.project == doc.project
    loaded.select_scene(second)
    SceneEditingService(loaded).rename(copy_part, "Edited from second")
    original = next(s for s in loaded.project.scenes if s.id == first)
    assert next(o for o in original.objects if o.id == part).name == "Edited from second"


def test_parts_and_object_actions_propagate_both_directions_with_stable_ids():
    """Adding/deleting parts and editing action keys preserves peer IDs and shared actions."""
    doc, library, root, part, key = example()
    peer = library.place(key)
    service = CharacterService(doc)
    peer_part = service.record(peer).extra[LINK]["ids"][part]
    doc.set_animation_context(root, frozenset(service.members(root)))
    with doc.command_group("Add sleeve"):
        mesh = AppearanceService(doc).create_shape("ellipse", 140, 170, 25, 35)
        added = service.mesh(mesh).object_id
        service.add_object_parts(root, (mesh,))
    assert added in service.records()
    mapping = service.record(peer).extra[LINK]["ids"]
    peer_added = mapping[added]
    assert service.record(peer_added).parent_id == peer
    clip = service.new_motion(root, "Wave")
    timeline_id = next(c.timeline_id for c in doc.scene.clips if c.id == clip)
    timelines = tuple(
        replace(
            t,
            tracks=(
                Track(
                    owner_id=part,
                    property_path="transform.rotation",
                    keyframes=(Keyframe(frame=0, value=0), Keyframe(frame=12, value=45)),
                ),
            ),
        )
        if t.id == timeline_id
        else t
        for t in doc.scene.timelines
    )
    doc.execute(
        ScenePatch(
            "Key wave", doc.scene.id, {"timelines": doc.scene.timelines}, {"timelines": timelines}
        )
    )
    peer_clip = service.record(peer).extra[LINK]["ids"][clip]
    saved = next(c for c in doc.scene.clips if c.id == peer_clip)
    track = next(t for t in doc.scene.timelines if t.id == saved.timeline_id).tracks[0]
    assert track.owner_id == peer_part and track.keyframes[-1].value == 45
    SceneEditingService(doc).delete_entries((added,))
    assert peer_added not in service.records()
    assert service.record(peer).extra[LINK]["ids"][part] == peer_part


def test_scene_and_object_clipboard_remap_all_ids_and_preserve_links():
    """Whole scenes include independent arrangement keys while copied objects retain their link."""
    doc, library, root, part, key = example()
    track = Track(
        owner_id=root, property_path="transform.x", keyframes=(Keyframe(frame=0, value=150),)
    )
    timeline = Timeline(tracks=(track,))
    doc.execute(
        ScenePatch(
            "Scene arrangement",
            doc.scene.id,
            {"timelines": doc.scene.timelines},
            {"timelines": (timeline,)},
        )
    )
    first = doc.scene.id
    before, count = doc.project, len(doc.history.undo_stack)
    copied = library.paste(library.copy_scene(first))[0]
    assert len(doc.history.undo_stack) == count + 1
    doc.project.validate_references()
    doc.select_scene(copied)
    copied_root = next(g for g in doc.scene.groups if g.name == "Hero")
    assert copied_root.id != root and copied_root.extra[LINK]["definition"] == key
    assert doc.scene.timelines[0].tracks[0].owner_id == copied_root.id
    copied_part = copied_root.extra[LINK]["ids"][part]
    SceneEditingService(doc).rename(copied_part, "Linked across scenes")
    original = next(s for s in doc.project.scenes if s.id == first)
    assert next(o for o in original.objects if o.id == part).name == "Linked across scenes"
    pasted = library.paste(library.copy_objects((copied_root.id,)))[0]
    assert pasted != copied_root.id
    assert CharacterService(doc).record(pasted).extra[LINK]["definition"] == key
    ids = [r.id for r in nested_records(doc.project)]
    assert len(ids) == len(set(ids))
    for _ in range(3):
        doc.undo()
    assert doc.project == before


def test_saved_object_survives_last_instance_and_protects_source_and_library_remove_undo():
    """Definitions retain sources, can be duplicated independently, and detach safely on removal."""
    doc, library, root, part, key = example()
    service = SceneEditingService(doc)
    asset = next(o.asset_id for o in doc.scene.objects if o.id == part)
    service.delete_entries((root,))
    assert key in library.entries() and not doc.scene.objects
    with pytest.raises(ValueError, match="saved Object"):
        service.remove_asset(asset)
    restored = library.place(key)
    before = doc.project
    library.remove((key,))
    assert key not in library.entries() and restored in service.records()
    assert LINK not in service.record(restored).extra
    doc.undo()
    assert doc.project == before
    saved = library.save((restored,))
    assert saved == (key,)
    copied = library.paste(library.copy_definitions((key,)))[0]
    assert copied != key and library.entries()[copied]["name"] == "Hero copy"


def test_rigged_object_clones_keep_binding_and_springs_and_arranged_actions_refresh():
    """Rig dependencies and scene windows stay linked when action keys change in another scene."""
    doc = DocumentService()
    doc.new()
    mesh = AppearanceService(doc).create_shape("rectangle", 100, 120, 80, 100)
    images = ImageRigService(doc)
    actor = images.convert((mesh,), "Rigged")
    bone = images.draw_bone(mesh, (120, 140), (160, 140))
    service = CharacterService(doc)
    root = service.create_object((images.mesh(mesh).object_id,), "Rigged")
    rig = next(r for r in doc.scene.skeletons if any(b.id == bone for b in r.bones))
    clip = service.new_motion(root, "Wave")
    from rigora.application_services.animation_editing import AnimationEditingService

    editor = AnimationEditingService(doc)
    editor.key(bone, "transform.rotation", 0, 0)
    editor.key(bone, "transform.rotation", 12, 30)
    first = doc.scene.id
    key = service.record(root).extra[LINK]["definition"]
    second = doc.add_scene()
    doc.select_scene(second)
    library = ObjectLibraryService(doc)
    copy = library.place(key, (500, 300))
    mapping = service.record(copy).extra[LINK]["ids"]
    assert mapping[rig.id] in {r.id for r in doc.scene.skeletons}
    assert mapping[actor] in {c.id for c in doc.scene.characters}
    service.place_motion(copy, mapping[clip], 10, 2)
    arranged = next(
        t for t in doc.scene.timelines if any(t.extra.get("motion_window") for t in t.tracks)
    )
    timing = arranged.tracks[0].extra["motion_window"]
    doc.select_scene(first)
    doc.set_animation_context(root, frozenset(service.members(root)))
    doc.select_animation_clip(clip)
    AnimationEditingService(doc).key(bone, "transform.rotation", 12, 75)
    inactive = next(s for s in doc.project.scenes if s.id == second)
    arranged = next(t for t in inactive.timelines if t.id == arranged.id)
    assert arranged.tracks[0].keyframes[-1].value == 75
    assert arranged.tracks[0].extra["motion_window"]["start"] == timing["start"]
    assert arranged.tracks[0].extra["motion_window"]["end"] == timing["end"]


def test_bare_rig_and_empty_object_place_at_pointer_and_metadata_is_safely_shared():
    """Objects without images still have cursor placement; immutable metadata avoids move copies."""
    doc = DocumentService()
    doc.new()
    from rigora.application_services.rigging import RigService
    from rigora.domain.content import ContentItem

    source = DocumentService()
    source.new()
    RigService(source).template("Biped")
    item = ContentItem(
        name="Bare biped",
        kind="rig",
        category="Rigs",
        author="Test",
        license="CC0-1.0",
        payload={"skeleton": source.scene.skeletons[0].to_dict()},
    )
    ContentService(doc).place(item, {}, position=(200, 150))
    characters = CharacterService(doc)
    root = next(g for g in doc.scene.groups if g.extra.get("object_container"))
    key = root.extra[LINK]["definition"]
    library = ObjectLibraryService(doc)
    copy = library.place(key, (-100, 450))
    members = characters.members(copy)
    points = [
        transform_point(n.world_matrix, x, 0)
        for k, n in doc.animation.pose.nodes.items()
        if k in members and n.kind == "bone"
        for x in (0, n.length)
    ]
    assert tuple(
        (min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1)
    ) == pytest.approx((-100, 450))
    extra = doc.project.extra
    characters.transform((copy,), dx=10)
    assert doc.project.extra is extra
    raw = {"nested": {"items": [1, 2]}}
    frozen = frozen_extra(raw)
    raw["nested"]["items"].append(3)
    assert frozen["nested"]["items"] == (1, 2)
    assert frozen_extra(frozen) is frozen
    with pytest.raises(TypeError):
        frozen["nested"]["items"] = ()


def test_automation_uses_the_same_objects_and_scene_clipboard_services(tmp_path):
    """CLI/Python operations expose actual scene/library authoring rather than separate copies."""
    from rigora.application_services.automation import RigoraAPI

    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    first = api.document.scene.id
    root = api.execute("object_create", {"name": "Reusable"}).data["object_id"]
    key = api.execute("object_library_save", {"object_ids": [root]}).data["definition_ids"][0]
    entries = api.execute("object_library_list").data["objects"]
    assert {"id": key, "name": "Reusable"} in entries
    second = api.execute("scene_create", {"name": "Other"}).data["scene_id"]
    api.execute("scene_select", {"scene_id": second})
    copy = api.execute("object_library_place", {"definition_id": key, "x": 130, "y": 260}).data[
        "object_id"
    ]
    entry = SceneEditingService(api.document).record(copy)
    assert (entry.transform.x, entry.transform.y) == pytest.approx((130, 260))
    payload = api.execute("authoring_copy", {"scene_id": second}).data
    pasted = api.execute("authoring_paste", {"payload": payload}).data["ids"][0]
    assert pasted != second and len(api.document.project.scenes) == 3
    api.execute("scene_delete", {"scene_id": first})
    assert len(api.document.project.scenes) == 2
