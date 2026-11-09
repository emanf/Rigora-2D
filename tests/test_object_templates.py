"""Original vector catalogs retain editable layers, framing and frame-rate independent motion."""

import io
from xml.etree import ElementTree

import pytest
from PIL import Image

from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.content_thumbnails import render_content_thumbnail
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_templates import build_artwork, build_effect
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.geometry import transform_point
from rigora.domain.project import Project, SceneSettings
from rigora.engine.sampling import CompiledTrack
from rigora.infrastructure.animated_object_catalog import animated_objects
from rigora.infrastructure.object_catalog import original_objects

ART = original_objects()
EFFECTS = animated_objects()


def document(fps=24):
    """Use the same separate Scene/Object animation ownership as the source application."""
    doc = DocumentService()
    doc.new(settings=SceneSettings(fps=fps))
    doc.separated_animation = True
    return doc


@pytest.mark.parametrize("art", ART, ids=lambda art: art.category + "/" + art.name)
def test_original_svg_has_visible_poster_and_editable_owned_artwork(art):
    """Each card decodes real SVG, frames its artwork and creates one reusable Object."""
    built = build_artwork(art)
    assert built.item.license == "CC0-1.0"
    source = next(iter(built.files.values()))
    ElementTree.fromstring(source)
    png = Image.open(io.BytesIO(render_content_thumbnail(built.item, built.files)))
    assert png.size == (144, 144)
    bounds = png.getbbox()
    assert bounds and max(bounds[2] - bounds[0], bounds[3] - bounds[1]) >= 120
    doc = document()
    before = doc.project
    mesh_id = ContentService(doc).place(built.item, built.files, position=(345, 260))
    mesh = next(mesh for mesh in doc.scene.meshes if mesh.id == mesh_id)
    root = CharacterService(doc).object_root(mesh.object_id)
    assert root and root.name == art.name
    pose = doc.animation.pose
    assert transform_point(
        pose.nodes[root.id].world_matrix, root.transform.pivot_x, root.transform.pivot_y
    ) == pytest.approx((345, 260))
    assert doc.read_asset(mesh.asset_id) == source
    assert Project.from_dict(doc.project.to_dict()) == doc.project
    assert len(doc.history.undo_stack) == 1
    doc.undo()
    assert doc.project == before


@pytest.mark.parametrize("spec", EFFECTS, ids=lambda spec: spec.name)
@pytest.mark.parametrize("fps", (24, 60))
def test_animated_object_has_editable_layers_and_fps_correct_continuous_scene_motion(spec, fps):
    """Both native and converted cadence retain real transforms/FFD and repeat at the exact seam."""
    built = build_effect(spec)
    assert build_effect(spec) == built
    doc = document(fps)
    baseline = doc.project
    ContentService(doc).place(built.item, built.files, position=(300, 230))
    roots = CharacterService(doc).scene_objects()
    assert len(roots) == 1 and len(doc.scene.cameras) == 1
    root = CharacterService(doc).record(roots[0])
    assert root.name == spec.name
    assert len(doc.scene.meshes) == len(spec.layers)
    assert all(asset.kind == "vector" for asset in doc.project.assets)
    source = CharacterService(doc).motions(root.id)[0]
    period = spec.frames * fps / 30
    assert source.out_frame + 1 == pytest.approx(period)
    timeline = next(
        t for t in doc.scene.timelines if t.id == doc.animation.evaluator.clip.timeline_id
    )
    window = timeline.tracks[0].extra["motion_window"]
    assert window["source_end"] == pytest.approx(period)
    assert window["end"] - window["start"] == pytest.approx(period)
    CharacterService(doc).edit_segment(window["id"], end=period * 2)
    timeline = next(
        t for t in doc.scene.timelines if t.id == doc.animation.evaluator.clip.timeline_id
    )
    samples = [doc.animation.evaluate(period * t) for t in (0.05, 0.23, 0.49, 0.78)]
    assert all(not sample.warnings for sample in samples)
    assert any(
        samples[0].nodes[obj.id].world_matrix != samples[2].nodes[obj.id].world_matrix
        or samples[0].nodes[obj.id].opacity != samples[2].nodes[obj.id].opacity
        for obj in doc.scene.objects
    ) or any(
        samples[0].meshes[mesh.id].positions != samples[2].meshes[mesh.id].positions
        for mesh in doc.scene.meshes
    )
    for track in timeline.tracks:
        sampled = CompiledTrack(track)
        assert sampled.sample(period * 0.27) == pytest.approx(
            sampled.sample(period * 1.27), abs=1e-6
        )
    assert Project.from_dict(doc.project.to_dict()) == doc.project
    SceneEditingService(doc).delete_entries((root.id,))
    assert not doc.scene.meshes and not doc.scene.deformers
    doc.undo()
    doc.undo()
    doc.undo()
    assert doc.project == baseline


@pytest.mark.parametrize("spec", EFFECTS, ids=lambda spec: spec.name)
def test_effect_poster_has_real_visible_art_and_no_camera_or_unowned_layers(spec):
    """Original vector fragments need no local installer or external artwork path."""
    built = build_effect(spec)
    source = built.item.payload["project_source"]
    assert all(not name.lower().endswith(("png", "jpg")) for name in built.files)
    assert source in built.files
    image = Image.open(io.BytesIO(render_content_thumbnail(built.item, built.files)))
    assert image.getbbox()


def test_motion_cannot_silently_create_an_unbound_rig_inside_static_artwork():
    """A target without bones needs explicit rigging instead of a misleading successful drop."""
    from rigora.application_services.template_catalog import creative_items
    from rigora.domain.project import ProjectError

    built = build_artwork(ART[0])
    doc = document()
    mesh_id = ContentService(doc).place(built.item, built.files, position=(200, 200))
    root = CharacterService(doc).object_root(mesh_id)
    motion = next(item for item in creative_items() if item.kind == "action")
    before = doc.project
    with pytest.raises(ProjectError, match="Add a skeleton"):
        ContentService(doc).place(motion, {}, object_id=root.id, position=(200, 200))
    assert doc.project == before


@pytest.mark.parametrize(
    "built", (build_artwork(ART[2]), build_effect(EFFECTS[0])), ids=("SVG part", "Animated torch")
)
def test_dropped_object_template_stays_in_active_object_editor_context(built):
    """Static and animated additions remain inside the edited Object."""
    doc = document()
    first = build_artwork(ART[0])
    mesh = ContentService(doc).place(first.item, first.files, position=(400, 300))
    characters = CharacterService(doc)
    root = characters.object_root(mesh)
    doc.set_animation_context(root.id, frozenset(characters.members(root.id)))
    baseline = doc.project
    ContentService(doc).place(built.item, built.files, position=(80, 90))
    assert doc.animation_context == root.id
    assert characters.scene_objects() == (root.id,)
    assert all(characters.object_root(mesh.object_id).id == root.id for mesh in doc.scene.meshes)
    if built.item.kind == "scene":
        assert characters.motions(root.id)
        assert not any(clip.extra.get("motion_sequence") for clip in doc.scene.clips)
    doc.undo()
    assert doc.project == baseline
