"""Stage bone overlays follow the same placement as their skinned premade artwork."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage, QPainter
from test_character_objects_gui import editor as editor
from test_timeline_title_gui import add_animal

from rigora.application_services.characters import CharacterService
from rigora.application_services.object_library import LINK, ObjectLibraryService
from rigora.domain.geometry import inverse, multiply, transform_point
from rigora.presentation.themes import PALETTES

pytestmark = pytest.mark.gui


def painted_bones(viewport, pose, monkeypatch, translation=None):
    """Observe actual bone-shape draw endpoints without changing the renderer or OS pointer."""
    drawn = []
    original = viewport._draw_needle

    def capture(painter, root, tip, tone):
        """Retain endpoint values before delegating to the real SVG silhouette renderer."""
        drawn.append((QPointF(root), QPointF(tip)))
        original(painter, root, tip, tone)

    image = QImage(1200, 800, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(viewport, "_draw_needle", capture)
            viewport._draw_pose(painter, PALETTES["dark"], pose, translation=translation)
    finally:
        painter.end()
    return drawn


def assert_stage_bones(viewport, raw, monkeypatch, *, translation=None):
    """Compare real paint and pick geometry to the skin's group/inverse-bind transform."""
    shown = raw.for_display()
    drawn = painted_bones(viewport, raw, monkeypatch, translation)
    expected = []
    offset = viewport.offset + (translation or QPointF())
    for key in raw.render_order:
        node = raw.nodes[key]
        if node.kind != "bone" or not node.visible:
            continue
        world = multiply(raw.bone_placements[key], node.world_matrix)
        assert shown.nodes[key].world_matrix == pytest.approx(world)
        expected.append(
            tuple(
                offset + QPointF(*transform_point(world, x, 0)) * viewport.zoom
                for x in (0, node.length)
            )
        )
    assert drawn and len(drawn) == len(expected)
    for actual, wanted in zip(drawn, expected, strict=True):
        for a, b in zip(actual, wanted, strict=True):
            assert (a - b).manhattanLength() < 1e-6
    assert shown.for_display() is shown
    assert shown.meshes is raw.meshes


def test_premade_bones_follow_stage_preview_commit_linked_placement_and_object_edit(
    editor, qtbot, monkeypatch
):
    """Use a creator Panda through stage gestures, saved Object placement and composer context."""
    root = add_animal(editor)
    vm, viewport, doc = editor.viewmodel, editor.viewport, editor.viewmodel.documents
    doc.set_animation_context(None)
    vm.changed.emit()
    editor.navigate()
    editor.scene_workspace.select_entries((root,))
    viewport.show_bones, viewport.zoom, viewport.offset = True, 0.5, QPointF(15, 25)
    qtbot.waitUntil(lambda: len(viewport.artwork.images) >= len(doc.project.assets), timeout=15000)
    before = doc.animation.pose
    viewport.subdivision_pose = before
    viewport.grab()
    assert viewport._artwork_pose is before, (
        "Bone display mapping must retain subdivision artwork caching."
    )
    viewport.subdivision_pose = None
    vm.scene.begin_preview()
    for values in (
        {"dx": 160, "dy": -70},
        {"dx": -90, "dy": 120, "rotation": 37, "scale_x": 1.4, "scale_y": 0.8},
        {"dx": 110, "dy": -40, "rotation": -25, "scale_x": -1, "scale_y": 1.2},
    ):
        vm.scene.preview_transform(**values)
        assert not vm.scene.error and vm.scene.preview is not None
        raw = viewport.source_pose
        assert_stage_bones(viewport, raw, monkeypatch)
        assert viewport.pose.nodes == raw.for_display().nodes
        assert any(
            viewport.pose.nodes[key].world_matrix != node.world_matrix
            for key, node in raw.nodes.items()
            if node.kind == "bone"
        ), "This case must expose the original bind-space/scene-space mismatch."
        assert doc.animation.pose is before
    vm.scene.finish_preview()
    assert_stage_bones(viewport, viewport.source_pose, monkeypatch)
    transformed = doc.project
    vm.undo()
    assert_stage_bones(viewport, viewport.source_pose, monkeypatch)
    vm.redo()
    assert doc.project == transformed
    assert_stage_bones(viewport, viewport.source_pose, monkeypatch)

    definition = CharacterService(doc).record(root).extra[LINK]["definition"]
    peer = ObjectLibraryService(doc).place(definition, (420, 330))
    vm.changed.emit()
    assert_stage_bones(viewport, viewport.source_pose, monkeypatch)
    editor.preview_project_asset("object:" + definition, doc.session_id, QPointF(310, 215))
    assert viewport.drop_pose and viewport.drop_pose.bone_placements
    assert_stage_bones(
        viewport, viewport.drop_pose, monkeypatch, translation=viewport.drop_translation
    )
    editor.clear_asset_preview()
    editor.object_edit.enter(root)
    raw = viewport.source_pose
    assert_stage_bones(viewport, raw, monkeypatch)
    owner = raw.nodes[root]
    stage = next(s for s in doc.scene.deformers if s.parameters.get("object_group") == root)
    assert multiply(
        owner.world_matrix, inverse(tuple(stage.parameters["object_group_bind"]))
    ) == pytest.approx((1, 0, 0, 1, 0, 0))
    editor.command_actions["scene_context"].setChecked(True)
    editor.object_edit.update_reference()
    reference = viewport.reference_pose
    assert reference is not None and not reference.bone_placements
    assert peer in reference.nodes
    editor.object_edit.exit()
    assert_stage_bones(viewport, viewport.source_pose, monkeypatch)
    viewport.show_bones = False
    assert not painted_bones(viewport, viewport.source_pose, monkeypatch)
    viewport.show_bones = True
    assert not painted_bones(
        viewport,
        replace(
            viewport.source_pose,
            nodes={k: replace(n, visible=False) for k, n in viewport.source_pose.nodes.items()},
        ),
        monkeypatch,
    )
