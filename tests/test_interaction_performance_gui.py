"""Repeatable offscreen profiling of production editor and Creator hot paths."""

import cProfile
import io
import json
import os
import pstats
import statistics
import time
from dataclasses import replace
from pathlib import Path

import pytest
from test_character_objects_gui import wait_for_artwork
from test_image_rigging_and_soft_drag import image_bytes
from test_object_workspace_redesign_gui import panel_editor as panel_editor

from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.image_rigging import ImageRigService
from rigora.domain.character_recipe import character_preset
from rigora.presentation.widgets.character_wizard import CharacterWizard

pytestmark = pytest.mark.gui


def test_editor_and_creator_interaction_profile(panel_editor, qtbot):
    window = panel_editor
    vm, doc, view = window.viewmodel, window.viewmodel.documents, window.viewport
    phase = os.environ.get("RIGORA_PROFILE_PHASE", "latest")
    output = Path("build/interaction-performance")
    output.mkdir(parents=True, exist_ok=True)
    metrics = {}

    def measure(name, operation, count=12):
        operation(0)
        samples = []
        for i in range(1, count + 1):
            start = time.perf_counter()
            operation(i)
            samples.append((time.perf_counter() - start) * 1000)
        metrics[name] = {"median_ms": statistics.median(samples), "max_ms": max(samples)}
        profile = cProfile.Profile()
        profile.runcall(operation, count + 1)
        report = io.StringIO()
        pstats.Stats(profile, stream=report).sort_stats("cumulative").print_stats(30)
        (output / f"{phase}-{name}.txt").write_text(report.getvalue(), encoding="utf-8")

    owner = CharacterCreationService(doc).create(build_character(character_preset("nova")))
    vm.changed.emit()
    wait_for_artwork(window, qtbot)
    window.object_edit.enter(owner)
    window.rig_workspace.set_mode(True)
    bone = next(b for r in doc.scene.skeletons for b in r.bones if b.name == "upper_arm.L")
    vm.rig.select(bone.id)
    vm.rig.begin_preview()
    measure("bone_animated", lambda i: vm.rig.preview_drag(bone.id, "chain_rotate", 10 + i / 10, 0))
    vm.rig.cancel_preview()
    doc.project = replace(doc.project, scenes=(replace(doc.scene, clips=(), timelines=()),))
    vm.changed.emit()
    vm.rig.begin_preview()
    measure("bone_rest", lambda i: vm.rig.preview_drag(bone.id, "chain_rotate", 10 + i / 10, 0))

    def move_bone_frame(i):
        vm.rig.preview_drag(bone.id, "chain_rotate", 10 + i / 10, 0)
        view.repaint()

    measure("bone_frame", move_bone_frame)
    measure("bone_paint", lambda i: view.repaint())
    vm.rig.cancel_preview()
    window.object_edit.exit()
    images = ImageRigService(doc)
    mesh_id = images.import_image_bytes("Dense.svg", image_bytes(), 32, 32)
    images.draw_bone(mesh_id, (900, 540), (1000, 540))
    vm.changed.emit()
    window.object_edit.enter(str(images.mesh(mesh_id).object_id))
    start = time.perf_counter()
    window.mesh_workspace.activate_tool("vertex")
    metrics["mesh_open"] = {"ms": (time.perf_counter() - start) * 1000}
    vm.mesh.select_mesh(mesh_id)
    wait_for_artwork(window, qtbot)
    window.mesh_workspace.frame_artwork()
    vertex = vm.mesh.mesh.vertices[544]
    baseline = doc.project

    def move_mesh(i):
        vm.mesh.preview_values = {(vertex.id, "x"): vertex.x + i / 10}
        view.set_pose(vm.mesh.pose)

    measure("mesh_move", move_mesh)

    def move_mesh_frame(i):
        move_mesh(i)
        view.repaint()

    measure("mesh_frame", move_mesh_frame)
    measure("mesh_paint", lambda i: view.repaint())
    vm.mesh.cancel_preview()
    assert doc.project is baseline
    window.object_edit.exit()

    wizard = CharacterWizard(window)
    qtbot.addWidget(wizard)
    wizard.show()
    qtbot.waitUntil(
        lambda: wizard.model.ready == wizard.recipe and not wizard.model.busy, timeout=90000
    )
    wizard.play.setChecked(False)
    measure("cc_motion", lambda i: wizard.select_motion(("Walk", "Run")[i % 2]))
    wizard.select_motion("Walk")

    def tick(i):
        wizard.play.setChecked(True)
        wizard.model.preview.animation.play()
        wizard._time = time.monotonic() - 1 / 24
        wizard.tick()
        wizard.play.setChecked(False)

    measure("cc_tick", tick)

    def creator_frame(i):
        tick(i)
        wizard.preview.repaint()

    measure("cc_frame", creator_frame)
    measure("cc_paint", lambda i: wizard.preview.repaint())
    recipe = wizard.recipe
    role = next(iter(recipe.colors))
    measure(
        "cc_color",
        lambda i: wizard.set_recipe(
            replace(recipe, colors={**recipe.colors, role: "#333333" if i % 2 else "#222222"})
        ),
        count=6,
    )
    wizard.close()
    (output / f"{phase}.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics))
