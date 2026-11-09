"""Real contact editor authoring through ordinary timeline channels and scene history."""

from dataclasses import replace
from threading import Event

import pytest
from test_roots_soft_drag_gui import editor as editor

from rigora.application_services.contact_editing import ContactEditingService
from rigora.application_services.rigging import RigService

pytestmark = pytest.mark.gui


def test_contact_editor_creates_edits_and_removes_timeline_support(editor, qtbot):
    """Selected segments create real constraints/keys; removal preserves their bones."""
    vm, doc = editor.viewmodel, editor.viewmodel.documents
    rig = RigService(doc)
    upper = rig.create_bone((100, 100), (200, 100))
    lower = rig.create_bone((200, 100), (300, 100), upper)
    bone_ids = {b.id for r in doc.scene.skeletons for b in r.bones}
    vm.changed.emit()
    editor.command_actions["foot_contacts"].trigger()
    dialog = editor.contact_editor
    qtbot.addWidget(dialog)
    dialog.upper.setCurrentIndex(dialog.upper.findData(upper))
    assert dialog.lower_bone.currentData() == lower
    dialog.start.setValue(0)
    dialog.end.setValue(20)
    dialog.apply()
    assert not vm.scene.error, dialog.note.text()
    key = dialog.contacts.currentData()
    assert any(t.owner_id == key for line in doc.scene.timelines for t in line.tracks)
    assert any("Foot contact" in row[1] for row in editor.timeline._groups)
    dialog.end.setValue(24)
    dialog.apply()
    assert not vm.scene.error, dialog.note.text()
    assert next(c for c in doc.scene.constraints if c.id == key).extra["contact_end"] == 24
    dialog.remove()
    assert not vm.scene.error, dialog.note.text()
    assert not any(c.id == key for c in doc.scene.constraints)
    assert {b.id for r in doc.scene.skeletons for b in r.bones} == bone_ids


def test_contact_baking_is_responsive_and_rejects_concurrent_edits(editor, qtbot, monkeypatch):
    """A blocked sampling worker leaves Qt responsive and cannot overwrite a newer edit."""
    doc = editor.viewmodel.documents
    rig = RigService(doc)
    upper = rig.create_bone((0, 0), (100, 0))
    lower = rig.create_bone((100, 0), (200, 0), upper)
    editor.viewmodel.changed.emit()
    editor.object_edit.exit()
    ContactEditingService(doc).interval(upper, lower, 0, 20)
    editor.viewmodel.changed.emit()
    editor.show_foot_contacts()
    dialog = editor.contact_editor
    qtbot.addWidget(dialog)
    entered, release = Event(), Event()
    original = ContactEditingService.bake_contacts

    def blocked(service, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(service, *args, **kwargs)

    monkeypatch.setattr(ContactEditingService, "bake_contacts", blocked)
    try:
        dialog.bake()
        qtbot.waitUntil(entered.is_set)
        rig.commit(
            "Rename rig",
            skeletons=tuple(replace(r, name="Renamed during bake") for r in doc.scene.skeletons),
        )
        revision = doc.project
        release.set()
        qtbot.waitUntil(lambda: dialog.bake_job is None)
        assert doc.project is revision
        assert "changed during baking" in dialog.note.text()
        dialog.bake()
        qtbot.waitUntil(lambda: dialog.bake_job is None)
        assert not editor.viewmodel.scene.error, dialog.note.text()
        assert any(c.extra.get("contact_bake") for c in doc.scene.clips), dialog.note.text()
        doc.undo()
        assert doc.project == revision
    finally:
        release.set()
