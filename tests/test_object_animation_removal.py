"""Removing reusable animations cleans their linked placements without removing artwork."""

from dataclasses import replace
from uuid import uuid4

import pytest

from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.state_machines import StateMachineService
from rigora.domain.project import ProjectError
from rigora.infrastructure.effect_catalog import ffd_presets


def animated_object():
    """Build a real reusable FFD source and linked Scene interval."""
    doc = DocumentService()
    doc.new()
    doc.set_animation_context(None)
    item = next(i for i in ffd_presets() if "motion" in i.payload)
    ContentService(doc).place(item, {})
    service = CharacterService(doc)
    owner = service.scene_objects()[0]
    (source,) = service.motions(owner)
    return doc, service, owner, source


def test_removal_cleans_linked_placements_preserves_other_actions_and_undoes_atomically(tmp_path):
    """Source, timeline and linked windows disappear together while artwork remains intact."""
    doc, service, owner, source = animated_object()
    other = service.new_motion(owner, "Other action", source.id)
    service.place_motion(owner, source.id, 50, 1)
    before, count = doc.project, len(doc.history.undo_stack)
    artwork = (doc.scene.groups, doc.scene.objects, doc.scene.meshes, doc.scene.deformers)
    service.remove_motion(owner, source.id)
    assert source.id not in {c.id for c in doc.scene.clips}
    assert source.timeline_id not in {t.id for t in doc.scene.timelines}
    assert {c.id for c in service.motions(owner)} == {other}
    assert not any(
        t.extra.get("motion_window", {}).get("source") == source.id
        for timeline in doc.scene.timelines
        for t in timeline.tracks
    )
    assert (doc.scene.groups, doc.scene.objects, doc.scene.meshes, doc.scene.deformers) == artwork
    assert len(doc.history.undo_stack) == count + 1
    removed = doc.project
    doc.undo()
    assert doc.project == before
    doc.redo()
    assert doc.project == removed
    path = tmp_path / "removed-action.rigora"
    doc.save(path)
    clone = DocumentService()
    clone.open(path)
    assert clone.project == removed


def test_removal_retains_timelines_still_used_by_another_clip():
    """Legacy clips can share a timeline; removing one must preserve the other's keys."""
    doc, service, owner, source = animated_object()
    shared = replace(source, id=str(uuid4()), name="Shared timeline")
    service.commit("Add legacy shared clip", clips=(*doc.scene.clips, shared))
    service.remove_motion(owner, source.id)
    assert shared in doc.scene.clips
    assert source.timeline_id in {t.id for t in doc.scene.timelines}


def test_animation_used_by_state_machine_requires_removing_that_reference_first():
    """Reject deletion before mutation instead of leaving invalid runtime states."""
    doc, service, owner, source = animated_object()
    StateMachineService(doc).define(owner, [{"name": "Idle", "clip": source.id}], [], {}, "Idle")
    before = doc.project
    with pytest.raises(ProjectError, match="state machine"):
        service.remove_motion(owner, source.id)
    assert doc.project == before


def test_animation_cannot_be_removed_from_an_unrelated_object():
    """Validate ownership before deleting any source or linked Scene keys."""
    doc, service, owner, source = animated_object()
    unrelated = service.create_object(name="Unrelated")
    before = doc.project
    with pytest.raises(ProjectError, match="belong"):
        service.remove_motion(unrelated, source.id)
    assert doc.project == before
