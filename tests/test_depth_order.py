"""Depth outranks scene order while ordinary insertion preserves existing arrangements."""

from dataclasses import replace

import pytest
from current_media_fixtures import background as make_background
from current_media_fixtures import ball_item

from rigora.application_services.appearance import AppearanceService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_library import ObjectLibraryService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.entities import Group, Layer, SceneObject, Slot
from rigora.domain.project import ProjectError, Scene
from rigora.engine.evaluation import SceneEvaluator


def test_depth_precedes_layers_and_explicit_order_and_inherits_parent_offsets():
    """Default/equal Z follows normal order; a parent offset moves every owned part together."""
    back, front = Layer(order=-200), Layer(order=300)
    parent = Group(extra={"depth": 5})
    a = SceneObject(parent_id=parent.id, layer_id=back.id)
    b = SceneObject(layer_id=front.id, extra={"depth": 4})
    scene = Scene(groups=(parent,), layers=(back, front), objects=(a, b), draw_order=(a.id, b.id))
    assert SceneEvaluator(scene).evaluate(0).render_order == (b.id, a.id)
    same = replace(scene, objects=(a, replace(b, extra={"depth": 5})))
    assert SceneEvaluator(same).evaluate(0).render_order == (a.id, b.id)
    negative = replace(scene, groups=(replace(parent, extra={"depth": -1}),))
    assert SceneEvaluator(negative).evaluate(0).render_order == (a.id, b.id)
    default = replace(scene, groups=(replace(parent, extra={}),), objects=(a, replace(b, extra={})))
    assert SceneEvaluator(default).evaluate(0).render_order == (a.id, b.id)
    assert SceneEvaluator(replace(default, draw_order=())).evaluate(0).render_order == (a.id, b.id)


@pytest.mark.parametrize("value", (True, 1.5, "2", 1_000_001))
def test_invalid_depth_is_rejected_without_an_ambiguous_render_order(value):
    """Project/API metadata must use a bounded integer depth rather than implicit coercion."""
    with pytest.raises(ProjectError, match="Depth"):
        SceneEvaluator(Scene(objects=(SceneObject(extra={"depth": value}),)))


def test_new_artwork_and_shapes_stay_above_background_and_depth_is_local_and_persistent(tmp_path):
    """Actual packaged backgrounds, props and saved Object copies share reversible ordering."""
    doc = DocumentService()
    doc.new()
    background = make_background(doc)
    background_parts = {o.id for o in doc.scene.objects}
    slot = Slot(owner_id=next(iter(background_parts)))
    SceneEditingService(doc).commit(
        "Add slot", slots=(slot,), draw_order=(*doc.scene.draw_order, slot.id)
    )
    item, media = ball_item()
    ball = ContentService(doc).apply(item, media)
    owner = str(AppearanceService(doc).mesh(ball).object_id)
    assert doc.animation.pose.render_order[-1] == owner
    shape = AppearanceService(doc).create_shape("ellipse", 100, 100, 120, 120)
    shape_owner = str(AppearanceService(doc).mesh(shape).object_id)
    assert doc.animation.pose.render_order[-1] == shape_owner
    assert slot.id in doc.scene.draw_order
    service = SceneEditingService(doc)
    baseline = doc.project
    service.set_depth((background,), 10)
    assert set(doc.animation.pose.render_order[-len(background_parts) :]) == background_parts
    doc.undo()
    assert doc.project == baseline
    doc.redo()
    library = ObjectLibraryService(doc)
    definition = next(k for k, v in library.entries().items() if v["root"] == background)
    peer = library.place(definition, (1400, 600))
    assert slot.id in doc.scene.draw_order
    assert service.record(peer).extra.get("depth", 0) == 0
    assert service.record(background).extra["depth"] == 10
    service.set_depth((owner,), 20)
    assert doc.animation.pose.render_order[-1] == owner
    saved = tmp_path / "depth.rigora"
    doc.save(saved)
    reopened = DocumentService()
    reopened.open(saved)
    assert reopened.animation.pose.render_order == doc.animation.pose.render_order
    assert SceneEditingService(reopened).record(owner).extra["depth"] == 20
