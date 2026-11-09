"""Stick body choices preserve editable vectors, limb attachment and facial animation."""

import json
import math
from dataclasses import replace
from xml.etree import ElementTree as ET

import pytest

from rigora.application_services.character_creation import build_character
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.domain.character_recipe import MOTION_CHOICES, VIEWS, CharacterRecipe
from rigora.domain.geometry import inverse, transform_point
from rigora.infrastructure.illustration import artwork
from rigora.infrastructure.illustration_motion import world_joints


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("shape", ("Simple", "Rounded rectangle"))
def test_body_contour_and_joint_sockets_follow_the_selected_shape(view, shape):
    """Both styles use real contours; rectangular joints sit at the torso's sides."""
    recipe = CharacterRecipe(view=view, body_shape=shape, proportions={"width": 1.3})
    design, rest, parts = artwork(recipe)
    body = next(p for p in parts if p.name == "Body")
    if shape == "Rounded rectangle":
        assert " C " in body.markup and " Q " in body.markup
        assert "<rect" not in body.markup
        assert 'fill="#ffffff"' in body.markup
        assert body.bounds[2] > 30
    else:
        assert 'fill="none"' in body.markup
        assert body.markup.count(" L ") == 1
    for phase in (0, 0.125, 0.5, 0.875, 1):
        sample = world_joints(design, view, "Run", phase)
        for side in ("R", "L"):
            arm = sample["upper_arm." + side]
            # Convert back into the spine's frame, where its base is the pelvis
            # and its tip is the shoulder. Attachment must survive torso lean.
            from rigora.domain.geometry import affine

            spine = sample["spine"]
            local = transform_point(
                inverse(affine(*spine.root, spine.angle, 1, 1, 0, 0)), *arm.root
            )
            assert local[0] == pytest.approx(design.body - 9)
            expected = (
                0 if shape == "Simple" else design.width * (0.25 if view == "Side" else 0.34) - 2
            )
            assert abs(local[1]) == pytest.approx(expected)
        assert all(j.length == pytest.approx(rest[name].length) for name, j in sample.items())
        assert all(math.isfinite(v) for j in sample.values() for v in (*j.root, *j.tip))


def test_both_body_recipes_round_trip_with_svg_sources_and_distinct_geometry():
    """Portable object metadata retains shape, width and ordinary editable motion tracks."""
    sources = []
    for shape in ("Simple", "Rounded rectangle"):
        recipe = CharacterRecipe(body_shape=shape, proportions={"width": 1.25})
        built = build_character(recipe)
        project = json.loads(built.files["character.json"])
        scene = project["scenes"][0]
        root = next(g for g in scene["groups"] if g["id"] == built.root_id)
        assert root["character_recipe"]["body_shape"] == shape
        assert root["character_recipe"]["proportions"]["width"] == 1.25
        assert {c["name"] for c in scene["clips"]} == set(MOTION_CHOICES)
        body = next(o for o in scene["objects"] if o["name"] == "Body")
        asset = next(a for a in project["assets"] if a["id"] == body["asset_id"])
        sources.append(built.files[asset["source"]])
        assert all(
            a["kind"] == "vector" and a["media_type"] == "image/svg+xml" for a in project["assets"]
        )
        for a in project["assets"]:
            ET.fromstring(built.files[a["source"]])
    assert sources[0] != sources[1]


def test_bound_stick_face_blinks_in_place_and_keys_all_retained_mouth_sets():
    """Skinning preserves a local facial pivot, and swapping mouth sets keeps speech timing."""
    doc = DocumentService()
    built = build_character(
        replace(CharacterRecipe(), motions=(), alternatives={"Mouth": ("Soft", "Graphic", "Ink")}),
        scratch=doc,
    )
    face = FaceService(doc)
    descriptor = face.face(built.root_id)
    eye = descriptor["eyes"][0]
    mesh = next(m for m in doc.scene.meshes if m.object_id == eye)

    def bounds(pose):
        points = [
            transform_point(pose.nodes[eye].world_matrix, *p)
            for p in pose.meshes[mesh.id].positions
        ]
        return (
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        )

    before = bounds(doc.animation.pose)
    face.controls(built.root_id, 0, blink=0.8)
    after = bounds(doc.animation.evaluate(0))
    assert after[3] - after[1] == pytest.approx((before[3] - before[1]) * 0.2)
    assert (after[1] + after[3]) / 2 == pytest.approx((before[1] + before[3]) / 2)
    face.lip_sync(built.root_id, ((0, "Rest"), (0.25, "AI"), (0.5, "MBP")))
    owner_ids = {t.owner_id for t in face.timeline.tracks if t.property_path == "visibility"}
    assert {
        key for mouths in descriptor["mouth_sets"].values() for key in mouths.values()
    } <= owner_ids
    assert doc.animation.evaluate(8).nodes[descriptor["mouths"]["AI"]].visible


@pytest.mark.gui
def test_creator_body_selector_and_width_publish_only_when_created(qtbot, tmp_path, monkeypatch):
    """Switching body geometry rebuilds the isolated preview and placement remains one Undo."""
    from PySide6.QtCore import QPointF, Qt

    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.asset_cards import AssetCardDelegate

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    qtbot.addWidget(window)
    window.confirm_discard = lambda: True
    try:
        qtbot.waitUntil(lambda: not vm.content.busy, timeout=45000)
        assert not vm.content.error
        vm.new_project()
        baseline = vm.documents.project
        window.show_character_wizard()
        creator = window.character_wizard

        def prepared():
            assert not creator.model.error
            return creator.model.ready == creator.recipe and not creator.model.busy

        qtbot.waitUntil(prepared, timeout=30000)
        assert not creator.adaptive_previews.isChecked()
        static_cards = {key: value[1] for key, value in creator.model.option_images.items()}
        assert static_cards and all(data.startswith(b"\x89PNG") for data in static_cards.values())
        assert (creator.preview.settings.width, creator.preview.settings.height) == (640, 480)
        assert creator.model.preview.scene.groups[0].transform.x == 320
        from rigora.domain.creator_options import COMPONENT_CHOICES

        for category in ("Eyes", "Mouth", "Hands"):
            grid = creator.grids[category]
            assert {
                grid.item(i).data(Qt.ItemDataRole.UserRole) for i in range(grid.count())
            } == set(COMPONENT_CHOICES[category])
        from PySide6.QtWidgets import QToolButton

        assert creator.zoom_in.property("materialIcon") == window.command_actions[
            "zoom_in"
        ].property("materialIcon")
        assert creator.zoom_out.property("materialIcon") == window.command_actions[
            "zoom_out"
        ].property("materialIcon")
        assert (
            len([b for b in creator.findChildren(QToolButton) if b.toolTip() == "Fit character"])
            == 1
        )
        assert not any(
            b.toolTip() in ("Fit camera · F", "Actual size · 1")
            for b in creator.findChildren(QToolButton)
        )
        for theme in ("light", "dark"):
            vm.set_theme(theme)
            qtbot.wait(30)
            assert (creator.preview.palette().window().color().lightness() > 128) == (
                theme == "light"
            )
            assert (
                creator.zoom_in.icon().cacheKey()
                == window.command_actions["zoom_in"].icon().cacheKey()
            )
        for grid in creator.grids.values():
            assert grid.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            assert all(not grid.item(i).icon().isNull() for i in range(grid.count()))
            for i in range(grid.count()):
                rect = grid.visualItemRect(grid.item(i))
                assert rect.width() == rect.height()
        creator.zoom_percent.setValue(75)
        assert creator.preview.zoom == pytest.approx(0.75)
        creator.zoom_in.click()
        assert creator.zoom_percent.value() == pytest.approx(90)
        creator.fit_preview()
        center = creator.preview.scene_point(QPointF(creator.preview.rect().center()))
        assert center.x() == pytest.approx(320, abs=2)
        assert center.y() == pytest.approx(240, abs=2)
        creator.set_background("Park")
        assert creator.preview.preview_background is not None
        creator.set_background("Transparent")
        assert creator.preview.preview_background is None and creator.preview.checker_visible
        creator.options_scroll.ensureWidgetVisible(creator.mouth)
        qtbot.wait(30)
        fangs = creator.mouth.item(8)
        qtbot.mouseClick(
            creator.mouth.viewport(),
            Qt.MouseButton.LeftButton,
            pos=creator.mouth.visualItemRect(fangs).center(),
        )
        assert creator.recipe.mouth_style == "Fangs"
        assert fangs.checkState() == Qt.CheckState.Unchecked
        soft = creator.mouth.item(0)
        qtbot.mouseClick(
            creator.mouth.viewport(),
            Qt.MouseButton.LeftButton,
            pos=AssetCardDelegate.check_rect(creator.mouth.visualItemRect(soft)).center(),
        )
        assert creator.recipe.mouth_style == "Fangs"
        assert creator.recipe.alternatives["Mouth"] == ("Soft",)
        qtbot.waitUntil(prepared, timeout=30000)
        creator.select_motion("Run")
        creator.model.preview.animation.seek(9)
        creator.preview.set_pose(creator.model.preview.animation.pose)
        before = creator.model.full_built
        with monkeypatch.context() as patch:

            def unexpected(*args, **kwargs):
                raise RuntimeError("Live paints must reuse existing bones and source actions")

            patch.setattr(
                "rigora.presentation.viewmodels.character_wizard.build_character", unexpected
            )
            creator.queue_paint("palette", "Ink", "#514337")
            creator.flush_paint()
            assert creator.recipe.colors["Ink"] == "#514337"
            qtbot.waitUntil(prepared, timeout=30000)
        assert creator.model.full_built.root_id == before.root_id
        assert creator.model.preview.animation.playback.frame == pytest.approx(9)
        assert {key: value[1] for key, value in creator.model.option_images.items()} == static_cards
        unchanged_recipe = creator.recipe
        creator.adaptive_previews.setChecked(True)
        qtbot.waitUntil(
            lambda: prepared() and creator.model.icons_recipe == creator.model.card_recipe(),
            timeout=30000,
        )
        assert creator.recipe == unchanged_recipe
        assert creator.model.full_built.root_id == before.root_id
        assert creator.model.preview.animation.playback.frame == pytest.approx(9)
        assert all(data[1].startswith(b"<svg") for data in creator.model.option_images.values())
        assert creator.model.option_images["Hands", "Open"][1] != static_cards["Hands", "Open"]
        creator.adaptive_previews.setChecked(False)
        qtbot.waitUntil(
            lambda: prepared() and creator.model.icons_recipe == creator.model.card_recipe(),
            timeout=30000,
        )
        assert {key: value[1] for key, value in creator.model.option_images.items()} == static_cards
        original_palette = creator.recipe
        with monkeypatch.context() as patch:

            def cancelled_paint(title, original, live):
                live("#ff0000")
                creator.flush_paint()
                assert creator.recipe.colors["Skin"] == "#ff0000"
                return None

            patch.setattr(creator, "pick_paint", cancelled_paint)
            creator.choose_color("Skin")
        assert creator.recipe == original_palette
        qtbot.waitUntil(prepared, timeout=30000)
        assert vm.documents.project is baseline
        assert creator.body_shape.currentText() == "Rounded rectangle"
        creator.body_shape.setCurrentText("Simple")
        qtbot.waitUntil(prepared, timeout=30000)
        assert creator.model.ready.body_shape == "Simple"
        creator.proportions["width"].setValue(135)
        creator.body_shape.setCurrentText("Rounded rectangle")
        qtbot.waitUntil(prepared, timeout=30000)
        assert creator.model.ready.proportions["width"] == 1.35
        assert vm.documents.project is baseline
        creator.create_character()
        root = next(g for g in vm.documents.scene.groups if g.extra.get("character_recipe"))
        assert root.extra["character_recipe"]["body_shape"] == "Rounded rectangle"
        assert root.extra["character_recipe"]["proportions"]["width"] == 1.35
        assert not window.object_edit.active
        vm.documents.undo()
        assert vm.documents.project == baseline
    finally:
        window.close()
