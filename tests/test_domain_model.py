"""Persistence and validation contracts for the complete authoring data model."""

import copy
from dataclasses import replace
from uuid import uuid4

import pytest

from rigora.domain.entities import (
    AnimationClip,
    Asset,
    AssetReference,
    Attachment,
    Bone,
    Character,
    Constraint,
    Deformer,
    Group,
    Keyframe,
    Layer,
    Mesh,
    PluginExtension,
    SceneObject,
    Skeleton,
    Slot,
    Timeline,
    Track,
    Transform,
    Vertex,
    nested_records,
)
from rigora.domain.project import Project, ProjectError, Scene
from rigora.infrastructure.project_storage import ProjectStorage


@pytest.fixture
def rich_project():
    """Connect every persistent entity family in one valid immutable authoring graph."""
    asset = Asset(name="Source", kind="vector", source="art/shape.svg")
    layer = Layer(name="Artwork")
    group = Group(name="Root", layer_id=layer.id)
    obj = SceneObject(name="Body", parent_id=group.id, layer_id=layer.id, asset_id=asset.id)
    bone = Bone(name="Root bone")
    child = Bone(name="Tip", parent_id=bone.id)
    skeleton = Skeleton(name="Rig", bones=(bone, child))
    vertices = tuple(
        Vertex(name=f"Vertex {i}", x=x, y=y, weights={bone.id: 1.0})
        for i, (x, y) in enumerate(((0, 0), (100, 0), (0, 100)))
    )
    mesh = Mesh(asset_id=asset.id, vertices=vertices, triangles=(tuple(v.id for v in vertices),))
    character = Character(skeleton_id=skeleton.id, object_ids=(obj.id,), mesh_ids=(mesh.id,))
    slot_id, attachment_id = str(uuid4()), str(uuid4())
    slot = Slot(
        id=slot_id,
        owner_id=bone.id,
        attachment_ids=(attachment_id,),
        active_attachment_id=attachment_id,
    )
    attachment = Attachment(id=attachment_id, slot_id=slot.id, asset_id=asset.id, mesh_id=mesh.id)
    keys = (
        Keyframe(frame=0, value=0),
        Keyframe(
            frame=24, value=40, interpolation="bezier", tangent_in=(-8, 0), tangent_out=(8, 0)
        ),
    )
    track = Track(owner_id=obj.id, property_path="transform.x", keyframes=keys)
    timeline = Timeline(tracks=(track,))
    clip = AnimationClip(timeline_id=timeline.id, out_frame=24, loop=True)
    extension = PluginExtension(plugin_id="org.rigora.example", payload={"inert": [1, 2]})
    scene = Scene(
        layers=(layer,),
        groups=(group,),
        objects=(obj,),
        characters=(character,),
        skeletons=(skeleton,),
        meshes=(mesh,),
        slots=(slot,),
        attachments=(attachment,),
        timelines=(timeline,),
        clips=(clip,),
        deformers=(Deformer(owner_id=mesh.id, kind="lattice", parameters={"columns": 3}),),
        constraints=(Constraint(owner_id=child.id, target_id=obj.id, kind="aim"),),
        extensions=(extension,),
        draw_order=(obj.id, slot.id),
    )
    return Project(
        name="Authoring contract",
        scenes=(scene,),
        assets=(asset,),
        asset_references=(AssetReference(asset_id=asset.id),),
    )


def test_complete_graph_roundtrip_stable_ids_and_optional_fields(rich_project):
    data = rich_project.to_dict()
    data["future"] = {"flags": [True, "preserved"]}
    data["scenes"][0]["skeletons"][0]["bones"][0]["future_solver"] = {"gain": 0.2}
    data["scenes"][0]["objects"][0]["transform"]["future_pivot"] = 3
    original = copy.deepcopy(data)
    loaded = Project.from_dict(data)
    data["future"]["flags"].clear()
    assert loaded.to_dict() == original
    assert {r.id for r in nested_records(loaded)} == {r.id for r in nested_records(rich_project)}
    with pytest.raises(TypeError):
        loaded.extra["new"] = 1
    assert loaded.scenes[0].timelines[0].tracks[0].keyframes[1].interpolation == "bezier"


def test_complete_graph_package_roundtrip(rich_project, tmp_path):
    path = tmp_path / "complete.rigora"
    ProjectStorage().save(path, rich_project, {})
    loaded = ProjectStorage().load_document(path)
    assert loaded.project == rich_project
    assert loaded.project.to_dict() == rich_project.to_dict()


def test_invalid_entity_references_types_duplicates_and_cycles(rich_project):
    scene = rich_project.scenes[0]
    variants = [
        replace(scene, objects=(replace(scene.objects[0], asset_id=str(uuid4())),)),
        replace(scene, objects=(replace(scene.objects[0], layer_id=scene.groups[0].id),)),
        replace(scene, groups=(replace(scene.groups[0], parent_id=scene.groups[0].id),)),
        replace(scene, objects=scene.objects * 2),
        replace(scene, draw_order=(scene.objects[0].id,) * 2),
        replace(scene, slots=(replace(scene.slots[0], attachment_ids=()),)),
        replace(
            scene,
            timelines=(
                replace(
                    scene.timelines[0],
                    tracks=(
                        replace(scene.timelines[0].tracks[0], owner_id=rich_project.assets[0].id),
                    ),
                ),
            ),
        ),
    ]
    for invalid in variants:
        with pytest.raises(ProjectError):
            replace(rich_project, scenes=(invalid,))
    with pytest.raises(ProjectError, match="same skeleton"):
        replace(
            rich_project,
            scenes=(
                replace(
                    scene,
                    skeletons=(
                        replace(
                            scene.skeletons[0],
                            bones=(
                                replace(scene.skeletons[0].bones[0], parent_id=scene.objects[0].id),
                                scene.skeletons[0].bones[1],
                            ),
                        ),
                    ),
                ),
            ),
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Transform(x=float("nan")),
        lambda: Transform(x=10**400),
        lambda: Transform(scale_x=True),
        lambda: Bone(length=-1),
        lambda: Keyframe(frame=-1, value=0),
        lambda: Keyframe(frame=0, value=float("inf")),
        lambda: AnimationClip(timeline_id=str(uuid4()), in_frame=3, out_frame=2),
        lambda: Track(
            owner_id=str(uuid4()),
            property_path="x",
            keyframes=(Keyframe(frame=1, value=1), Keyframe(frame=1, value=2)),
        ),
        lambda: Vertex(x=0, y=0, weights={str(uuid4()): 0.2}),
        lambda: Vertex(x=0, y=0, weights={str(uuid4()): True}),
        lambda: Asset(source="../outside.png"),
        lambda: Asset(source="assets/invalid\x00name.png", storage="embedded"),
        lambda: Asset(source="assets/NUL.png", storage="embedded"),
        lambda: Asset(source="art/source.png:secret"),
        lambda: Asset(source="C:/outside.png"),
        lambda: Asset(source="assets/../outside.png", storage="embedded"),
        lambda: SceneObject.from_dict({"name": "missing stable ID"}),
    ],
)
def test_invalid_authored_values_are_rejected(factory):
    with pytest.raises(ProjectError):
        factory()


def test_mesh_geometry_and_transform_convention():
    vertices = tuple(Vertex(x=i, y=i) for i in range(3))
    with pytest.raises(ProjectError, match="degenerate"):
        Mesh(vertices=vertices, triangles=(tuple(v.id for v in vertices),))
    transform = Transform(x=10, y=20, rotation=90, scale_x=2, pivot_x=5)
    a, b, c, d, tx, ty = transform.matrix()
    assert (a * 5 + c * 0 + tx, b * 5 + d * 0 + ty) == pytest.approx((15, 20))
    assert (a, b, c, d) == pytest.approx((0, 2, -1, 0))
