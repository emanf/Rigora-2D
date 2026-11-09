"""Main Scene discovers saved actions and holds instance-local clothing and skin choices."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.appearance import AppearanceService
from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.object_library import ObjectLibraryService, object_roots
from rigora.infrastructure.content_packs import read_pack

pytestmark = pytest.mark.gui


def action_choices(picker, kind, group=None):
    """Open a flat action category, then choose a collection in the card editor."""
    row = next(
        picker.tree.topLevelItem(i)
        for i in range(picker.tree.topLevelItemCount())
        if (picker.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 6) or (None, None))[1]
        == kind
    )
    picker.add((row,))
    dialog = picker.timeline.action_editor
    if group is not None:
        dialog.group.setCurrentIndex(dialog.group.findData(group))
    return dialog


def click_choice(picker, identity):
    """Use the action grid and its explicit Apply control rather than writing scalar keys."""
    kind, _, group, choice = identity
    dialog = action_choices(picker, kind, group if kind != "motion" else None)
    dialog.select_choice(choice or None)
    QTest.mouseClick(dialog.apply_button, Qt.MouseButton.LeftButton)
    return dialog


def test_premade_add_tracks_lists_every_action_and_places_a_scene_block(editor, qtbot):
    """The selected Template exposes its actions and can key user-authored saved looks."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    entry = next(e for e in vm.content.entries if e.item.name == "Dash · Runner")
    _, files = read_pack(entry.path)
    ContentService(doc).place(entry.item, files, position=(400, 300))
    root = object_roots(doc.scene)[0]
    vm.changed.emit()
    service = CharacterService(doc)
    meshes = service.meshes_for((root.id,))
    skin = service.skin_group(root.id, "Palette")
    service.save_skin(root.id, skin, meshes, "Original")
    clothing = service.wardrobe_group(root.id, "Accessories")
    service.add_variant(root.id, clothing, (meshes[0],), "Original accessory")
    vm.changed.emit()
    vm.scene.select((root.id,))
    vm.playback.seek(12)
    editor.timeline.open_picker()
    picker = editor.timeline.picker
    service = CharacterService(doc)
    motions = service.motions(root.id)
    dialog = action_choices(picker, "motion")
    assert {
        dialog.cards.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dialog.cards.count())
    } == {c.id for c in motions}
    assert {
        picker.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 6)[1]
        for i in range(picker.tree.topLevelItemCount())
        if picker.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole + 6)
    } == {"motion", "outfits", "skins", "views", "attachment"}
    assert picker.objects.currentItem() is picker.object_rows[root.id]
    assert not picker.tree.rootIsDecorated()
    assert all(
        picker.tree.topLevelItem(i).childCount() == 0
        for i in range(picker.tree.topLevelItemCount())
    )
    walking = next(c for c in motions if c.name == "Walk")
    original = next(t for t in doc.scene.timelines if t.id == walking.timeline_id)
    baseline, count = doc.project, len(doc.history.undo_stack)
    click_choice(picker, ("motion", root.id, "", walking.id))
    assert not vm.animation_editor.error
    assert doc.animation_context is None and len(doc.history.undo_stack) == count + 1
    assert editor.timeline.pages.currentIndex() == 0
    block = next(b for b in editor.timeline.dope.motions if b["source"] == walking.id)
    assert (block["source"], block["start"]) == (walking.id, 12)
    assert block["end"] == 12 + walking.out_frame - walking.in_frame
    assert next(t for t in doc.scene.timelines if t.id == original.id) == original
    assert doc.animation.evaluate(18).meshes != doc.animation.evaluate(22).meshes
    doc.undo()
    assert doc.project == baseline
    doc.redo()
    assert not doc.animation.pose.warnings
    owner = service.record(root.id)
    skins = next(g for g in owner.extra["skins"] if g["variants"])
    outfits = next(g for g in owner.extra["outfits"] if g["variants"])
    service.apply_skin(root.id, skins["id"], skins["variants"][0]["id"], auto_key=True, frame=18)
    service.show_variant(
        root.id, outfits["id"], outfits["variants"][0]["id"], True, auto_key=True, frame=24
    )
    editor.viewmodel.changed.emit()
    picker.close()
    editor.timeline.action_editor.close()
    editor.resizeDocks([editor.docks["timeline"]], [360], Qt.Orientation.Vertical)
    qtbot.wait(20)
    editor.timeline.grab().save("build/template-scene-actions.png")
    dialog = action_choices(picker, "outfits", outfits["id"])
    dialog.grab().save("build/template-clothing-action.png")
    editor.timeline.open_picker()
    picker.grab().save("build/template-add-tracks.png")


@pytest.fixture
def dressed_object(editor):
    """Create a small reusable Object with two actions, interchangeable clothes and saved colors."""
    doc = editor.viewmodel.documents
    looks, service = AppearanceService(doc), CharacterService(doc)
    body, first, second = [looks.create_shape("rectangle", 100, 100, 60, 100) for _ in range(3)]
    parts = tuple(looks.mesh(key).object_id for key in (body, first, second))
    root = service.create_object(parts, "Test actor")
    clothing = service.wardrobe_group(root, "Jackets")
    red = service.add_variant(root, clothing, (first,), "Red jacket", occludes=(body,))
    blue = service.add_variant(root, clothing, (second,), "Blue jacket", occludes=(body,))
    service.show_variant(root, clothing, red, True)
    skin = service.skin_group(root, "Body colors")
    normal = service.save_skin(root, skin, (body,), "Normal")
    looks.edit((body,), {"palette.0.r": 10, "palette.0.g": 20, "palette.0.b": 30})
    dark = service.save_skin(root, skin, (body,), "Dark")
    service.apply_skin(root, skin, normal)
    for name in ("Wave", "Bow"):
        service.new_motion(root, name)
        animation = AnimationEditingService(doc)
        animation.key(parts[0], "transform.rotation", 0, 0)
        animation.key(parts[0], "transform.rotation", 12, 30)
        animation.clip_settings(out_frame=12)
    doc.set_animation_context(None)
    definition = ObjectLibraryService(doc).save((root,))[0]
    other = ObjectLibraryService(doc).place(definition, (500, 300))
    editor.viewmodel.changed.emit()
    editor.viewmodel.scene.select((root,))
    editor.timeline.open_picker()
    return root, other, (body, first, second), clothing, (red, blue), skin, (normal, dark)


def test_scene_clothing_skin_keys_hold_and_keep_linked_defaults(editor, dressed_object, tmp_path):
    """Scene keys survive reload and leave other instances, shared defaults and actions intact."""
    root, other, meshes, clothing, (red, blue), skin, (normal, dark) = dressed_object
    doc, vm, picker = editor.viewmodel.documents, editor.viewmodel, editor.timeline.picker
    service = CharacterService(doc)
    baseline, library = doc.project, doc.project.extra["object_library"]
    source = tuple(
        t for t in doc.scene.timelines if t.id in {c.timeline_id for c in service.motions(root)}
    )
    parts = [service.mesh(k).object_id for k in meshes]
    original_color = doc.animation.pose.meshes[meshes[0]].appearance["palette"][0]
    other_parts = service.record(other).extra["linked_object"]["ids"]
    vm.playback.seek(12)
    dialog = action_choices(picker, "outfits", clothing)
    dialog.select_choice(blue)
    dialog.shown.setChecked(True)
    assert doc.project is baseline
    count = len(doc.history.undo_stack)
    click_choice(picker, ("outfits", root, clothing, blue))
    assert not vm.animation_editor.error and len(doc.history.undo_stack) == count + 1
    assert doc.scene.groups == baseline.scenes[0].groups
    for frame in (0, 11.9, 12, 20):
        pose = doc.animation.evaluate(frame)
        assert pose.nodes[parts[1]].visible == (frame < 12)
        assert pose.nodes[parts[2]].visible == (frame >= 12)
        assert not pose.nodes[parts[0]].visible
        assert pose.nodes[other_parts[parts[1]]].visible
        assert not pose.nodes[other_parts[parts[2]]].visible
    vm.playback.seek(20)
    click_choice(picker, ("skins", root, skin, dark))
    assert not vm.animation_editor.error
    assert doc.animation.evaluate(19.9).meshes[meshes[0]].appearance["palette"][0] == original_color
    assert doc.animation.evaluate(20).meshes[meshes[0]].appearance["palette"][0]["r"] == 10
    vm.playback.seek(36)
    click_choice(picker, ("skins", root, skin, normal))
    assert doc.animation.evaluate(35).meshes[meshes[0]].appearance["palette"][0]["r"] == 10
    assert doc.animation.evaluate(36).meshes[meshes[0]].appearance["palette"][0] == original_color
    assert doc.project.extra["object_library"] == library
    assert all(t in doc.scene.timelines for t in source)
    assert (
        doc.animation.evaluate(20).meshes[other_parts[meshes[0]]].appearance["palette"][0]
        == original_color
    )
    groups = [
        t for t in AnimationEditingService(doc).timeline.tracks if t.extra.get("appearance_group")
    ]
    assert {t.extra["appearance_kind"] for t in groups} == {"outfits", "skins"}
    assert all(k.interpolation == "step" for t in groups for k in t.keyframes)
    vm.playback.seek(40)
    click_choice(picker, ("outfits", root, clothing, ""))
    assert not vm.animation_editor.error
    assert doc.animation.evaluate(39).nodes[parts[2]].visible
    assert doc.animation.evaluate(40).nodes[parts[0]].visible
    assert not any(doc.animation.evaluate(40).nodes[p].visible for p in parts[1:])
    picker.resize(900, 760)
    for i in range(picker.tree.topLevelItemCount()):
        section = picker.tree.topLevelItem(i)
        section.setExpanded(True)
        for j in range(section.childCount()):
            section.child(j).setExpanded(True)
    picker.grab().save("build/main-scene-animation-choices.png")
    doc.save(tmp_path / "scene-choices.rigora")
    reopened = DocumentService()
    reopened.open(doc.path)
    reopened.set_animation_context(None)
    for frame in (0, 12, 20, 35, 36, 40):
        assert reopened.animation.evaluate(frame).meshes == doc.animation.evaluate(frame).meshes


def test_multi_selected_actions_place_sequentially_and_undo_once(editor, dressed_object):
    """Adding two saved actions uses their native durations and a single command boundary."""
    root = dressed_object[0]
    doc, picker = editor.viewmodel.documents, editor.timeline.picker
    service = CharacterService(doc)
    motions = service.motions(root)
    dialog = action_choices(picker, "motion")
    assert dialog.cards.count() == len(motions)
    dialog.cards.selectAll()
    baseline, count = doc.project, len(doc.history.undo_stack)
    dialog.apply()
    assert not editor.viewmodel.animation_editor.error
    assert len(doc.history.undo_stack) == count + 1
    assert [(b["start"], b["end"]) for b in editor.timeline.motion_blocks.blocks] == [
        (0, 12),
        (12, 24),
    ]
    doc.undo()
    assert doc.project == baseline
