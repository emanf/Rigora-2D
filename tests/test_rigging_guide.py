"""Guided artwork-to-character assembly remains editable, undoable and reusable offline."""

from dataclasses import replace

import pytest

from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging_guide import RIG_TEMPLATES, RiggingGuideService
from rigora.domain.project import ProjectError
from rigora.infrastructure.content_packs import read_pack
from rigora.resources import asset_path


@pytest.mark.parametrize("template", RIG_TEMPLATES)
def test_guided_character_round_trip_reuse_and_editable_deformation(tmp_path, template):
    """Every guide template fits real SVG artwork and produces a reusable weighted character."""
    doc = DocumentService()
    doc.new()
    original = doc.project
    guide = RiggingGuideService(doc)
    meshes = guide.import_parts((asset_path("examples/prop.svg"),))
    mesh = guide.mesh(meshes[0])
    guide.identify({mesh.object_id: ("Character artwork", "Body")})
    rig_id = guide.generate_rig(template, meshes)
    guide.generate_meshes(meshes, 4, 5)
    assert len(guide.mesh(meshes[0]).vertices) == 30
    guide.bind_parts(rig_id, meshes)
    assert all(v.weights for v in guide.mesh(meshes[0]).vertices)
    rig = next(r for r in guide.scene.skeletons if r.id == rig_id)
    before = doc.project
    posed = guide.test_pose(rig.bones[0].id, 30)
    assert doc.project is before
    assert posed.meshes[meshes[0]].positions != doc.animation.pose.meshes[meshes[0]].positions
    guide.share(tmp_path / "character.rigpack", author="Test author", license="CC0-1.0")
    pack, files = read_pack(tmp_path / "character.rigpack")
    copy = DocumentService()
    copy.new()
    ContentService(copy).apply_scene(pack.items[0], files)
    assert copy.project.scenes[0].meshes and copy.animation.pose.meshes
    assert copy.project.scenes[0].characters[0].mesh_ids
    doc.save(tmp_path / "character.rigora")
    reopened = DocumentService()
    reopened.open(tmp_path / "character.rigora")
    assert reopened.animation.pose == doc.animation.pose
    while doc.history.undo_stack:
        doc.undo()
    assert doc.project == original


def test_guide_refuses_silent_topology_loss_and_rolls_back_partial_import(tmp_path):
    """Edited geometry requires explicit replacement and failed batches preserve the project."""
    doc = DocumentService()
    doc.new()
    guide = RiggingGuideService(doc)
    meshes = guide.import_parts((asset_path("examples/prop.svg"),))
    mesh = guide.mesh(meshes[0])
    guide.replace_mesh(
        replace(mesh, vertices=(replace(mesh.vertices[0], protected=True), *mesh.vertices[1:]))
    )
    before = doc.project
    with pytest.raises(ProjectError, match="contains edits"):
        guide.generate_meshes(meshes, 5, 5)
    assert doc.project is before
    with pytest.raises((ProjectError, OSError)):
        guide.import_parts((asset_path("examples/prop.svg"), tmp_path / "missing.svg"))
    assert doc.project == before
    guide.generate_meshes(meshes, 5, 5, replace_edits=True)
    assert len(guide.mesh(meshes[0]).vertices) == 36


@pytest.mark.gui
def test_modeless_guide_edits_weights_previews_and_resumes(qtbot, tmp_path):
    """The real guide runs its six steps and hands off to the standard stage weight brush."""
    pytest.importorskip("PySide6")
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    vm.new_project()
    vm.content.pool.waitForDone(3000)
    RiggingGuideService(vm.documents).import_parts((asset_path("examples/prop.svg"),))
    vm.changed.emit()
    qtbot.waitUntil(lambda: bool(window.viewport.artwork.vectors), timeout=5000)
    window.show_rigging_guide()
    guide = window.rigging_guide
    qtbot.addWidget(guide)
    assert not guide.isModal() and guide.mesh_ids()
    guide.identify()
    guide.steps.setCurrentRow(1)
    guide.generate_rig()
    assert not vm.animation_editor.error and guide.bones.rowCount() > 0
    guide.save_bones()
    guide.generate_meshes()
    guide.steps.setCurrentRow(3)
    guide.bind_parts()
    assert not vm.animation_editor.error
    before = vm.documents.project
    guide.steps.setCurrentRow(4)
    guide.angle.setValue(20)
    assert vm.documents.project is before and vm.animation_editor.preview_pose is not None
    assert guide.grab().save(str(tmp_path / "rigging-guide.png"))
    guide.paint_weights()
    assert vm.mesh.tool == "paint" and vm.mesh.active
    window.show_rigging_guide()
    assert window.rigging_guide is guide and guide.isVisible()
    guide.close()
