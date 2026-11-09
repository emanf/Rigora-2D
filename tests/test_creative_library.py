"""Creative presets produce real geometry, motion and physics through canonical services."""

import math
from collections import Counter
from dataclasses import replace

import pytest

from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.application_services.template_catalog import creative_items
from rigora.domain.geometry import transform_point
from rigora.domain.project import Project
from rigora.engine.evaluation import SceneEvaluator

ITEMS = creative_items()


def document():
    """Use an isolated scene and leave all actual user projects untouched."""
    value = DocumentService()
    value.new("Creative library test")
    return value


def test_catalog_has_licensed_data_presets_without_copied_artwork():
    """The catalog contains authored data and attributed MIT numeric motions."""
    assert Counter(i.kind for i in ITEMS) == {
        "rig": 11,
        "action": 85,
        "deformation": 26,
        "spring": 20,
    }
    assert len({i.id for i in ITEMS}) == len(ITEMS)
    assert {i.license for i in ITEMS} == {"CC0-1.0", "MIT"}
    assert len([i for i in ITEMS if i.license == "MIT"]) == 8
    for item in ITEMS:
        assert "source" not in item.payload and "project" not in item.payload
        assert item.author and item.category


@pytest.mark.parametrize("item", [i for i in ITEMS if i.kind == "rig"], ids=lambda i: i.name)
def test_skeleton_drop_creates_owned_editable_bones_and_whole_deletion(item):
    """Every bare rig has a centered selectable container and deletes without orphan bones."""
    doc = document()
    before = doc.project
    service = ContentService(doc)
    key = service.place(item, {}, position=(270, 190))
    root = CharacterService(doc).object_root(key)
    assert root and root.extra["object_container"]
    pose = doc.animation.pose
    assert transform_point(
        pose.nodes[root.id].world_matrix, root.transform.pivot_x, root.transform.pivot_y
    ) == pytest.approx((270, 190))
    assert all(b.id in pose.nodes for b in service.skeleton(key).bones)
    base = next(b for b in service.skeleton(key).bones if not b.parent_id)
    assert pose.nodes[base.id].world_matrix[4:] == pytest.approx(
        transform_point(pose.nodes[root.id].world_matrix, base.transform.x, base.transform.y)
    )
    SceneEditingService(doc).delete_entries((root.id,))
    assert not doc.scene.skeletons and not doc.scene.characters
    doc.undo()
    assert doc.scene.skeletons
    doc.undo()
    assert doc.project == before


@pytest.mark.parametrize("item", [i for i in ITEMS if i.kind == "action"], ids=lambda i: i.name)
def test_every_motion_has_changing_finite_poses_and_round_trips(item):
    """All advertised motions animate bones and keep original lengths and reusable source clips."""
    doc = document()
    before = doc.project
    clip_id = ContentService(doc).place(item, {}, position=(400, 300))
    rig = doc.scene.skeletons[0]
    root = CharacterService(doc).object_root(rig.id)
    assert root
    clips = CharacterService(doc).motions(root.id)
    assert any(c.id == clip_id for c in clips)
    evaluator = SceneEvaluator(doc.scene, clip_id)
    duration = float(item.payload["duration"]) * doc.scene.settings.fps / float(item.payload["fps"])
    poses = [evaluator.evaluate(duration * f) for f in (0, 0.13, 0.31, 0.57, 0.83)]
    assert any(
        poses[0].nodes[b.id].world_matrix != poses[2].nodes[b.id].world_matrix for b in rig.bones
    )
    for pose in poses:
        assert not pose.warnings
        for bone in rig.bones:
            node = pose.nodes[bone.id]
            assert all(math.isfinite(v) for v in node.world_matrix)
            assert node.length == pytest.approx(bone.length)
    assert Project.from_dict(doc.project.to_dict()) == doc.project
    doc.undo()
    assert doc.project == before


@pytest.mark.parametrize(
    "item", [i for i in ITEMS if i.kind == "deformation"], ids=lambda i: i.name
)
def test_ffd_presets_change_vector_geometry_and_keep_original_source(item):
    """Actual evaluated vertices move; no preset substitutes a flattened artwork poster."""
    doc = document()
    before = doc.project
    key = ContentService(doc).place(item, {}, position=(320, 240))
    stage = next(d for d in doc.scene.deformers if d.id == key)
    mesh = next(m for m in doc.scene.meshes if m.id == stage.owner_id)
    assert doc.project.assets[0].kind == "vector"
    source = doc.read_asset(mesh.asset_id)
    baseline = [(v.x, v.y) for v in mesh.vertices]
    poses = [doc.animation.evaluate(t).meshes[mesh.id].positions for t in (0, 6, 13, 25, 37, 47)]
    assert any(
        any(math.dist(a, b) > 1e-5 for a, b in zip(baseline, points, strict=True))
        for points in poses
    )
    assert doc.read_asset(mesh.asset_id) == source
    assert Project.from_dict(doc.project.to_dict()) == doc.project
    doc.undo()
    assert doc.project == before


@pytest.mark.parametrize("item", [i for i in ITEMS if i.kind == "spring"], ids=lambda i: i.name)
def test_spring_presets_create_live_constraints_and_finite_secondary_motion(item):
    """Empty-space spring drops carry editable driver keys and deterministic live constraints."""
    doc = document()
    before = doc.project
    rig_id = ContentService(doc).place(item, {}, position=(350, 260))
    assert doc.scene.constraints and all(c.kind == "spring" for c in doc.scene.constraints)
    assert all(
        c.parameters["frequency"] == item.payload["parameters"]["frequency"]
        for c in doc.scene.constraints
    )
    rig = ContentService(doc).skeleton(rig_id)
    poses = [doc.animation.evaluate(t) for t in (0, 9, 18, 36, 60)]
    assert any(
        poses[0].nodes[b.id].world_matrix != poses[2].nodes[b.id].world_matrix for b in rig.bones
    )
    assert all(
        abs(v) < 10000 and math.isfinite(v)
        for pose in poses
        for b in rig.bones
        for v in pose.nodes[b.id].world_matrix
    )
    assert Project.from_dict(doc.project.to_dict()) == doc.project
    doc.undo()
    assert doc.project == before


def test_relative_motion_retargets_size_and_rest_angles_without_writing_bone_lengths():
    """A different sized/posed skeleton keeps its rest transforms and receives normalized deltas."""
    source = next(i for i in ITEMS if i.name == "Human · full body")
    doc = document()
    service = ContentService(doc)
    rig_id = service.place(source, {}, position=(0, 0))
    rig = service.skeleton(rig_id)
    edited = replace(
        rig,
        bones=tuple(
            replace(
                b,
                length=b.length * 1.5,
                transform=replace(b.transform, rotation=b.transform.rotation + 5),
            )
            for b in rig.bones
        ),
    )
    service.commit("Customize rest skeleton", skeletons=(edited,))
    before = doc.scene.skeletons
    motion = next(i for i in ITEMS if i.name == "Natural · Walk")
    clip = service.place(motion, {}, target=rig_id)
    assert doc.scene.skeletons == before
    timeline = next(
        t
        for t in doc.scene.timelines
        if t.id == next(c.timeline_id for c in doc.scene.clips if c.id == clip)
    )
    mapping = service.mapping(edited)
    source_x = next(
        c for c in motion.payload["channels"] if c["semantic"] == "hips" and c["path"] == "x"
    )
    track = next(
        t
        for t in timeline.tracks
        if t.owner_id == mapping["hips"] and t.property_path == "transform.x"
    )
    root = next(b for b in edited.bones if b.id == mapping["hips"])
    assert track.keyframes[3].value == pytest.approx(
        root.transform.x + source_x["keys"][3][1] * 1.5
    )


def test_added_skeleton_can_bind_to_existing_artwork_without_pose_or_artwork_jumps():
    """A template remains in its Object's coordinate space before and after explicit binding."""
    from rigora.application_services.appearance import AppearanceService
    from rigora.application_services.skinning import SkinService

    doc = document()
    mesh_id = AppearanceService(doc).create_shape("rectangle", 100, 100, 160, 180)
    characters = CharacterService(doc)
    owner = characters.mesh(mesh_id).object_id
    mesh_before = doc.animation.pose.meshes[mesh_id]
    item = next(i for i in ITEMS if i.name == "Human · full body")
    rig_id = ContentService(doc).place(item, {}, position=(180, 190), object_id=owner)
    rig = ContentService(doc).skeleton(rig_id)
    assert doc.animation.pose.meshes[mesh_id].positions == mesh_before.positions
    pose = doc.animation.pose.for_display()
    points = {b.id: pose.nodes[b.id].world_matrix for b in rig.bones}
    world_before = [
        transform_point(pose.nodes[doc.animation.pose.meshes[mesh_id].object_id].world_matrix, *p)
        for p in doc.animation.pose.meshes[mesh_id].positions
    ]
    SkinService(doc).bind(mesh_id, tuple(b.id for b in rig.bones))
    bound = doc.animation.pose.for_display()
    for bone in rig.bones:
        assert bound.nodes[bone.id].world_matrix == pytest.approx(points[bone.id])
    mesh = bound.meshes[mesh_id]
    world_after = [
        transform_point(bound.nodes[mesh.object_id].world_matrix, *p) for p in mesh.positions
    ]
    for actual, expected in zip(world_after, world_before, strict=True):
        assert actual == pytest.approx(expected, abs=1e-7)


@pytest.mark.parametrize(
    "item", [i for i in ITEMS if i.kind == "action" and i.payload.get("loop")], ids=lambda i: i.name
)
def test_loop_motion_scene_segments_retain_source_period_and_velocity_at_the_seam(item):
    """Scene repetition uses the continuous endpoint, with no dropped sample or duplicate hold."""
    from rigora.engine.sampling import CompiledTrack

    doc = document()
    doc.separated_animation = True
    source_id = ContentService(doc).place(item, {}, position=(300, 260))
    source = next(c for c in doc.scene.clips if c.id == source_id)
    period = float(item.payload["duration"]) * doc.scene.settings.fps / float(item.payload["fps"])
    assert source.out_frame + 1 == pytest.approx(period)
    main = next(t for t in doc.scene.timelines if t.id == doc.animation.evaluator.clip.timeline_id)
    window = main.tracks[0].extra["motion_window"]
    assert window["source_end"] == pytest.approx(period)
    CharacterService(doc).edit_segment(window["id"], end=period * 3)
    main = next(t for t in doc.scene.timelines if t.id == doc.animation.evaluator.clip.timeline_id)
    for track in main.tracks:
        sampler = CompiledTrack(track)
        assert sampler.sample(period * 0.37) == pytest.approx(sampler.sample(period * 1.37))
        first, last = track.keyframes[0], track.keyframes[-1]
        assert first.value == pytest.approx(last.value, abs=1e-9)
        assert first.tangent_out[1] / first.tangent_out[0] == pytest.approx(
            last.tangent_in[1] / last.tangent_in[0], abs=1e-9
        )


@pytest.mark.parametrize("kind", ("rig", "action", "spring"))
def test_placed_bone_object_transform_moves_all_displayed_bones_exactly_once(kind):
    """The Object owns bone placement before skinning, so dragging cannot leave the rig behind."""
    doc = document()
    item = next(i for i in ITEMS if i.kind == kind)
    ContentService(doc).place(item, {}, position=(300, 220))
    rig = doc.scene.skeletons[0]
    root = CharacterService(doc).object_root(rig.id)
    before = doc.animation.pose.for_display()
    SceneEditingService(doc).transform((root.id,), dx=123, dy=47)
    after = doc.animation.pose.for_display()
    for bone in rig.bones:
        a, b = before.nodes[bone.id].world_matrix, after.nodes[bone.id].world_matrix
        assert b[:4] == pytest.approx(a[:4])
        assert b[4:] == pytest.approx((a[4] + 123, a[5] + 47))


def test_skeleton_and_motion_added_in_object_context_remain_inside_that_object():
    """Empty preview space in Object Editor still belongs to the currently edited Object."""
    from rigora.application_services.appearance import AppearanceService

    doc = document()
    doc.separated_animation = True
    mesh = AppearanceService(doc).create_shape("rectangle", 100, 100, 160, 180)
    characters = CharacterService(doc)
    owner = characters.record(characters.promote_object(characters.mesh(mesh).object_id))
    doc.set_animation_context(owner.id, frozenset(CharacterService(doc).members(owner.id)))
    rig_item = next(i for i in ITEMS if i.kind == "rig")
    rig_id = ContentService(doc).place(rig_item, {}, position=(80, 90))
    assert CharacterService(doc).object_root(rig_id).id == owner.id
    motion = next(i for i in ITEMS if i.name == "Natural · Walk")
    source_id = ContentService(doc).place(motion, {}, target=rig_id)
    assert source_id in {c.id for c in CharacterService(doc).motions(owner.id)}
    assert doc.animation_context == owner.id
    assert not any(c.extra.get("motion_sequence") for c in doc.scene.clips)


def test_reference_only_raster_recovery_packs_stay_excluded_from_stale_preferences(tmp_path):
    """A retained workspace registration cannot reintroduce reference-only recovered textures."""
    from rigora.application_services.content_library import ContentLibrary
    from rigora.application_services.object_templates import build_artwork
    from rigora.domain.content import ContentPack
    from rigora.infrastructure.content_packs import write_pack
    from rigora.infrastructure.object_catalog import shapes
    from rigora.infrastructure.preferences import PreferencesStore

    built = build_artwork(shapes()[0])
    bundled = tmp_path / "bundled.rigpack"
    write_pack(
        bundled,
        ContentPack(name="Original", author="Rigora", license="CC0-1.0", items=(built.item,)),
        built.files,
    )
    local = tmp_path / "reference"
    local.mkdir()
    recovered = replace(
        built.item,
        author="Reference archive",
        extra={"recovery": "paired color and alpha PNG streams"},
    )
    write_pack(
        local / "recovered.rigpack",
        ContentPack(
            name="Reference",
            author="Reference archive",
            license="Reference-only",
            items=(recovered,),
        ),
        built.files,
    )
    permitted = replace(built.item, id=ITEMS[0].id, name="Unrelated user template")
    write_pack(
        local / "user.rigpack",
        ContentPack(
            name="User", author="Reference archive", license="User-supplied", items=(permitted,)
        ),
        built.files,
    )
    preferences = PreferencesStore(tmp_path / "workspace.json")
    preferences.data["template_pack_directories"] = [str(local)]
    library = ContentLibrary(preferences, bundled=bundled)
    assert {entry.item.name for entry in library.entries()} == {built.item.name, permitted.name}
    assert not library.warnings
