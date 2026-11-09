"""Character ownership, vector appearance and motion timing through the shared services."""

import base64
import re
from xml.etree import ElementTree as ET

import pytest

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.documents import DocumentService
from rigora.application_services.image_rigging import ImageRigService
from rigora.application_services.rendering import svg_frame
from rigora.application_services.rigging import RigService
from rigora.domain.geometry import transform_point
from rigora.engine.vector_appearance import palette, styled_artwork

SOURCE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="160" height="240">'
    b'<g fill="#ff0000"><rect width="160" height="240" stroke="#333333"/></g></svg>'
)


@pytest.fixture
def artwork():
    """Create two solid instances backed by original editable vector sources."""
    doc = DocumentService()
    doc.new()
    service = ImageRigService(doc)
    a = service.import_image_bytes("First.svg", SOURCE)
    b = service.import_image_bytes("Second.svg", SOURCE)
    return doc, service, a, b


def test_solids_conversion_root_clamping_follows_object_and_undo(artwork):
    doc, images, a, b = artwork
    assert not images.scene.characters and not images.scene.skeletons
    before, count = doc.project, len(doc.history.undo_stack)
    actor = images.convert((a, b), "Actor")
    assert len(doc.history.undo_stack) == count + 1
    assert not images.scene.skeletons[0].bones
    assert set(images.scene.characters[0].mesh_ids) == {a, b}
    rig = RigService(doc)
    initial = rig.origin(actor)
    CharacterService(doc).transform(images.scene.characters[0].object_ids, dx=30, dy=40)
    assert rig.origin(actor) == pytest.approx((initial[0] + 30, initial[1] + 40))
    rig.move_origin(-1000, -1000, actor)
    assert rig.origin(actor)[0] > 0 and rig.origin(actor)[1] > 0
    rig.move_origin(-1000, -1000, actor, free=True)
    assert rig.origin(actor) == pytest.approx((-1000, -1000))
    for _ in range(4):
        doc.undo()
    assert doc.project == before


def test_add_parts_reattach_and_detach_reanchor_ownership(artwork):
    doc, images, a, b = artwork
    first = images.convert((a,), "First")
    images.add_parts(first, (b,))
    assert set(images.scene.characters[0].mesh_ids) == {a, b}
    bone = images.draw_bone(a, (900, 480), (1000, 480))
    assert {d.owner_id for d in images.scene.deformers if d.kind == "skinning"} == {a, b}
    c = images.import_image_bytes("Third.svg", SOURCE)
    second = images.convert((c,), "Second")
    other = images.draw_bone(c, (950, 520), (1050, 520))
    original_root = RigService(doc).origin(first)
    images.bind_image(a, other, rigid=True)
    owners = {actor.id: actor for actor in images.scene.characters}
    assert a not in owners[first].mesh_ids and a in owners[second].mesh_ids
    assert RigService(doc).origin(first) == pytest.approx(original_root)
    assert all(set(v.weights) == {other} for v in images.mesh(a).vertices)
    before = doc.project
    images.detach((a,))
    assert not images.mesh(a).extra.get("rig_skeleton_id")
    assert not any(v.weights for v in images.mesh(a).vertices)
    assert not any(d.kind == "skinning" and d.owner_id == a for d in images.scene.deformers)
    assert RigService(doc).bone(bone)
    doc.undo()
    assert doc.project == before


@pytest.mark.parametrize("angle", (15, 90, 168))
def test_drawn_endpoints_stay_put_under_animated_parent(angle):
    """A new child uses the displayed parent and never jumps to satisfy a fresh fold limit."""
    import math

    doc = DocumentService()
    doc.new()
    rig = RigService(doc)
    parent = rig.create_bone((200, 200), (300, 200))
    editor = AnimationEditingService(doc)
    editor.key(parent, "transform.rotation", 0, 0)
    editor.key(parent, "transform.rotation", 24, 75)
    doc.animation.seek(24)
    node = doc.animation.pose.nodes[parent]
    start = transform_point(node.world_matrix, node.length, 0)
    end = (
        start[0] + 100 * math.cos(math.radians(angle)),
        start[1] + 100 * math.sin(math.radians(angle)),
    )
    key = rig.create_bone(start, end, parent)
    actual = doc.animation.pose.nodes[key]
    assert transform_point(actual.world_matrix, 0, 0) == pytest.approx(start)
    assert transform_point(actual.world_matrix, actual.length, 0) == pytest.approx(end)


def test_vector_inheritance_styles_alpha_and_original_source(artwork):
    doc, images, a, b = artwork
    assert ("fill", "#ff0000") in palette(SOURCE)
    assert ("fill", "#000000") not in palette(SOURCE)
    service = AppearanceService(doc)
    service.paint((a, b), "fill", "#ff0000", "#0000ff")
    pose = doc.animation.pose
    styled = styled_artwork(SOURCE, pose.meshes[a].appearance)
    root = ET.fromstring(styled)
    assert root.find("{*}g").get("fill") == "#0000ff"
    assert root.find("{*}g/{*}rect").get("fill") is None
    assert doc.read_asset(images.mesh(a).asset_id) == SOURCE
    exported = svg_frame(doc, 0)
    encoded = re.search(rb'data:image/svg\+xml;base64,([^"\s]+)', exported)[1]
    assert b"#0000ff" in base64.b64decode(encoded)
    css = (
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>.skin{fill:#ff0000}</style>'
        b'<path class="skin"/></svg>'
    )
    assert b"#0000ff" in styled_artwork(css, pose.meshes[a].appearance)
    alpha = b'<svg xmlns="http://www.w3.org/2000/svg"><path fill="#ff000080"/></svg>'
    assert b"#0000ff80" in styled_artwork(alpha, pose.meshes[a].appearance)


def test_native_vector_preview_recolors_and_invalidates_source_variants(artwork, qapp):
    """Native previews render styled original vectors and never retain a superseded look."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    from rigora.presentation.artwork import ArtworkCache, decode_artwork

    doc, images, a, _ = artwork
    AppearanceService(doc).paint((a,), "fill", "#ff0000", "#0000ff")
    look = doc.animation.pose.meshes[a].appearance
    cache = ArtworkCache()
    cache.put("art", decode_artwork(SOURCE, 8), SOURCE)
    renderer = cache.styled("art", look)
    assert isinstance(renderer, QSvgRenderer) and renderer.isValid()
    output = QImage(160, 240, QImage.Format.Format_ARGB32_Premultiplied)
    output.fill(Qt.GlobalColor.transparent)
    painter = QPainter(output)
    renderer.render(painter)
    painter.end()
    assert output.pixelColor(80, 120).name() == "#0000ff"
    changed = SOURCE.replace(b"#ff0000", b"#00ff00")
    cache.put("art", decode_artwork(changed, 8), changed)
    assert not cache.looks
    assert cache.styled("art", look) is not renderer
    assert doc.read_asset(images.mesh(a).asset_id) == SOURCE


def test_color_and_shape_tweens_sample_midpoint_export_and_persist(artwork, tmp_path):
    doc, _, _, _ = artwork
    service = AppearanceService(doc)
    mesh = service.create_shape("ellipse", 100, 100, 200, 120)
    service.morph_target(mesh, "rectangle")
    doc.animation.seek(60)
    service.edit((mesh,), {"shape.mix": 1}, auto_key=True)
    service.paint((mesh,), "fill", "#bcbcbc", "#0000ff", auto_key=True)
    looks = [doc.animation.evaluate(frame).meshes[mesh].appearance for frame in (0, 30, 60)]
    assert [p["shape"]["mix"] for p in looks] == [0, 0.5, 1]
    assert looks[1]["palette"][0]["r"] == pytest.approx(94)
    assert looks[1]["palette"][0]["b"] == pytest.approx((188 + 255) / 2)
    frames = [styled_artwork(b"", look) for look in looks]
    assert len(set(frames)) == 3 and all(frame.count(b"C") == 120 for frame in frames)
    assert not doc.animation.evaluate(30).warnings
    assert doc.animation.evaluate(30).to_dict()["meshes"][-1]["appearance"]["shape"]["mix"] == 0.5
    doc.save(tmp_path / "appearance.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "appearance.rigora")
    assert clone.animation.evaluate(30).meshes[mesh].appearance == looks[1]


def test_outfit_groups_exclusive_multiple_hidden_and_keyed(artwork):
    doc, images, a, b = artwork
    actor = images.convert((a,), "Model")
    service = CharacterService(doc)
    group = service.wardrobe_group(actor, "Shirts")
    service.add_variant(actor, group, (a,), "Red")
    count = len(doc.history.undo_stack)
    service.add_variant(actor, group, (b,), "Blue")
    assert len(doc.history.undo_stack) == count + 1
    assert not doc.animation.pose.nodes[images.mesh(a).object_id].visible
    assert doc.animation.pose.nodes[images.mesh(b).object_id].visible
    service.show_variant(actor, group, None, False)
    assert all(not doc.animation.pose.nodes[images.mesh(k).object_id].visible for k in (a, b))
    multi = service.wardrobe_group(actor, "Accessories", multiple=True)
    service.add_variant(actor, multi, (a,), "First")
    service.add_variant(actor, multi, (b,), "Second")
    assert all(doc.animation.pose.nodes[images.mesh(k).object_id].visible for k in (a, b))
    doc.animation.seek(20)
    service.show_variant(actor, multi, None, False, auto_key=True)
    assert all(doc.animation.evaluate(19).nodes[images.mesh(k).object_id].visible for k in (a, b))
    assert all(
        not doc.animation.evaluate(20).nodes[images.mesh(k).object_id].visible for k in (a, b)
    )


def test_motion_blocks_trim_speed_repeat_source_and_save(artwork, tmp_path):
    doc, images, a, _ = artwork
    actor = images.convert((a,), "Actor")
    service = CharacterService(doc)
    source = service.new_motion(actor, "Walk")
    editor = AnimationEditingService(doc)
    owner = images.mesh(a).object_id
    editor.key(owner, "transform.rotation", 0, 0)
    editor.key(owner, "transform.rotation", 30, 90)
    editor.clip_settings(out_frame=30)
    original = next(t for t in service.scene.timelines if t.id == editor.clip.timeline_id)
    count = len(doc.history.undo_stack)
    block = service.place_motion(actor, source, 30, 2, speed=2, repeat=True)
    assert len(doc.history.undo_stack) == count + 1
    assert doc.animation.evaluate(29).nodes[owner].local.rotation == 0
    assert doc.animation.evaluate(37.5).nodes[owner].local.rotation == 45
    assert doc.animation.evaluate(45).nodes[owner].local.rotation == 0
    source_now = next(t for t in service.scene.timelines if t.id == original.id)
    assert source_now == original
    service.edit_segment(block, start=35, end=90)
    assert doc.animation.evaluate(37.5).nodes[owner].local.rotation == 45
    service.edit_segment(block, speed=1, repeat=False)
    assert doc.animation.evaluate(90).nodes[owner].local.rotation == 90
    doc.save(tmp_path / "motions.rigora")
    clone = DocumentService()
    clone.open(tmp_path / "motions.rigora")
    clone.select_animation_clip(doc.selected_clip_id)
    assert clone.animation.evaluate(37.5).nodes == doc.animation.evaluate(37.5).nodes
    service.remove_segment(block)
    assert service.motions(actor)[0].id == source
    doc.undo()
    assert doc.animation.evaluate(90).nodes[owner].local.rotation == 90


def test_facing_auto_key_switches_without_collapsing_between_frames(artwork):
    doc, images, a, _ = artwork
    images.convert((a,))
    owner = images.mesh(a).object_id
    doc.animation.seek(20)
    service = CharacterService(doc)
    service.auto_key = True
    service.flip((owner,))
    initial = doc.animation.evaluate(0).nodes[owner].world_matrix
    assert doc.animation.evaluate(19).nodes[owner].world_matrix == initial
    assert doc.animation.evaluate(20).nodes[owner].world_matrix != initial


def test_facing_key_preserves_existing_motion_before_the_flip(artwork):
    doc, images, a, _ = artwork
    owner = images.mesh(a).object_id
    editor = AnimationEditingService(doc)
    editor.key(owner, "transform.rotation", 0, 0)
    editor.key(owner, "transform.rotation", 30, 90)
    before = doc.animation.evaluate(10).nodes[owner].world_matrix
    doc.animation.seek(20)
    service = CharacterService(doc)
    service.auto_key = True
    service.flip((owner,))
    assert doc.animation.evaluate(10).nodes[owner].world_matrix == pytest.approx(before, abs=1e-5)


@pytest.mark.parametrize("folder", (False, True))
def test_asset_placement_into_character_or_owned_folder_is_atomic(artwork, folder):
    """Every source-placement caller can use character rows and keeps folders and ownership."""
    from rigora.application_services.asset_pipeline import AssetPipeline

    doc, images, a, _ = artwork
    actor = images.convert((a,))
    service = CharacterService(doc)
    target = service.part_group(actor, ()) if folder else actor
    source = images.mesh(a).asset_id
    before, count = doc.project, len(doc.history.undo_stack)
    result = AssetPipeline(doc).place_source(source, parent=target)
    added = result["mesh_ids"][0]
    assert added in service.character(actor).mesh_ids
    assert service.record(result["object_ids"][0]).parent_id == (target if folder else None)
    assert len(doc.history.undo_stack) == count + 1
    doc.undo()
    assert doc.project == before
    service.flags((actor,), locked=True)
    before = doc.project
    with pytest.raises(ValueError, match="[Uu]nlock"):
        AssetPipeline(doc).place_source(source, parent=target)
    assert doc.project == before
