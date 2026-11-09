"""Typed content remapping and prepared revision adoption retain validation and identity safety."""

from dataclasses import replace
from uuid import uuid4

import pytest

from rigora.application_services.commands import PreparedProjectChange
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_library import remap_ids, remap_scene
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import Group, Keyframe, Timeline, Track, nested_records
from rigora.domain.project import ProjectError, Scene


def test_typed_remapping_matches_json_codec_and_preserves_source_and_mutability_guards():
    """Weights, opaque metadata, dotted paths and nested animation values remap identically."""
    group = Group()
    data = {"points": [[1, 2]], "owner": group.id}
    key = Keyframe(frame=0, value=data)
    track = Track(
        owner_id=group.id, property_path=f"parameters.controls.{group.id}.0", keyframes=(key,)
    )
    source = Scene(groups=(group,), timelines=(Timeline(tracks=(track,)),))
    ids = {r.id: str(uuid4()) for r in nested_records(source)}
    result = remap_scene(source, ids)
    assert result.to_dict() == remap_ids(source.to_dict(), ids)
    assert result.groups[0].id != group.id
    data["points"][0][0] = 99
    assert source.timelines[0].tracks[0].keyframes[0].value["points"][0][0] == 1
    assert result.timelines[0].tracks[0].keyframes[0].value["owner"] == ids[group.id]
    with pytest.raises(TypeError):
        result.timelines[0].tracks[0].keyframes[0].value["new"] = True
    for bad in (float("inf"), float("nan")):
        with pytest.raises(ProjectError):
            Keyframe(frame=0, value=bad)


def test_prepared_adoption_is_atomic_reversible_and_rejects_stale_sources():
    """Publishing never replays imports, discards concurrent edits or crosses scene boundaries."""
    doc = DocumentService()
    doc.new()
    baseline = doc.project
    snapshot = doc.fork()
    snapshot._link_objects = True
    key = SceneEditingService(snapshot).group()
    _ = snapshot.animation.pose
    doc.adopt_prepared(snapshot, baseline, "Place prepared template")
    result = doc.project
    assert key in SceneEditingService(doc).records()
    assert len(doc.history.undo_stack) == 1
    doc.undo()
    assert doc.project is baseline
    doc.redo()
    assert doc.project is result
    newer = doc.fork()
    newer._link_objects = True
    SceneEditingService(doc).group()
    with pytest.raises(ProjectError, match="changed"):
        doc.adopt_prepared(newer, result, "Stale")
    with pytest.raises(ProjectError, match="conflicts"):
        PreparedProjectChange("Stale", baseline, result).apply(doc.project)


def test_cached_timeline_index_retains_duplicate_and_missing_reference_validation():
    """Reusing immutable animation indexes never bypasses checks in a new scene revision."""
    from rigora.domain.project import Project

    owner = Group()
    track = Track(
        owner_id=owner.id, property_path="transform.x", keyframes=(Keyframe(frame=0, value=2),)
    )
    timeline = Timeline(tracks=(track,))
    scene = Scene(groups=(owner,), timelines=(timeline,))
    project = Project(scenes=(scene,))
    assert nested_records(project) == nested_records(project)
    with pytest.raises(ProjectError, match="unique"):
        replace(project, scenes=(replace(scene, timelines=(timeline, timeline)),))
    with pytest.raises(ProjectError, match="missing"):
        replace(project, scenes=(replace(scene, groups=()),))


def test_transform_only_revisions_reuse_geometry_but_mesh_edits_invalidate_it():
    """Moving an Object retains compiled deformation; changing geometry rebuilds it."""
    from rigora.application_services.appearance import AppearanceService

    doc = DocumentService()
    doc.new()
    mesh = AppearanceService(doc).create_shape("rectangle", 100, 100, 80, 60)
    source = AppearanceService(doc).mesh(mesh)
    owner = source.object_id
    old = doc.animation.evaluator.deformation
    SceneEditingService(doc).transform((owner,), dx=40)
    assert doc.animation.evaluator.deformation is old
    AppearanceService(doc).replace_mesh(
        replace(source, vertices=tuple(replace(v, x=v.x * 2) for v in source.vertices))
    )
    assert doc.animation.evaluator.deformation is not old
