"""Measure real workspace input, painting and dense subdivision without changing user files.

Runs Qt offscreen by default. Timings are diagnostic medians, not portable test
thresholds. Fixture creation, worker discovery and warm-up are excluded.
"""

import argparse
import json
import os
import statistics
import time
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QMouseEvent
from PySide6.QtWidgets import QApplication

from rigora.app.application import ApplicationInfo
from rigora.application_services.character_creation import CharacterCreationService, build_character
from rigora.application_services.commands import ScenePatch
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.domain.character_recipe import character_preset
from rigora.domain.entities import Bone, Skeleton, Transform
from rigora.infrastructure.effect_catalog import spring_presets
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow


def fixture(case):
    """Build ordinary bones, imported sources, or bundled fully skinned characters."""
    doc = DocumentService()
    doc.new()
    if case == "willow":
        item = next(item for item in spring_presets() if item.name == "Long ponytail")
        ContentService(doc).place(item, {}, position=(700, 450))
        return doc
    if case in ("boy", "girl", "three-characters", "ten-characters"):
        count = 10 if case == "ten-characters" else 3 if case == "three-characters" else 1
        builds = [
            build_character(replace(character_preset(name), motions=("Walk",)))
            for name in ("Little", "Ribbon")
        ]
        for i in range(count):
            CharacterCreationService(doc).create(builds[1 if case == "girl" else i % 2])
        return doc
    service = MeshService(doc)
    if case != "bones":
        for i in range(3 if case == "sources" else 1):
            source = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="650">'
                f'<rect x="30" y="30" width="420" height="580" rx="80" fill="#{i + 3}56585"/>'
                '<circle cx="250" cy="200" r="60" fill="white"/></svg>'
            ).encode()
            mesh = service.import_image_bytes(f"Source {i}.svg", source, 12, 12)
            if case == "dense-wireframe":
                service.subdivide(
                    (mesh,), mode="full", density=32, alignment=10, discard_edits=True
                )
    bones = []
    for i in range(12):
        bones.append(
            Bone(
                name=f"Bone {i}",
                parent_id=bones[-1].id if i % 4 else None,
                length=90,
                transform=Transform(
                    x=90 if i % 4 else 100 + (i // 4) * 300, y=0 if i % 4 else 250, rotation=20
                ),
            )
        )
    scene = doc.project.scenes[0]
    doc.execute(
        ScenePatch(
            "Benchmark rig",
            scene.id,
            {"skeletons": scene.skeletons},
            {"skeletons": (Skeleton(bones=tuple(bones)),)},
        )
    )
    return doc


def measure(operation, samples):
    """Warm one call, then report independent unprofiled median and worst input latency."""
    operation()
    values = []
    for _ in range(samples):
        started = time.perf_counter()
        operation()
        values.append((time.perf_counter() - started) * 1000)
    return {"median_ms": round(statistics.median(values), 3), "max_ms": round(max(values), 3)}


def benchmark(case, samples, app, output, catalog_cache=None):
    """Exercise the same viewmodels, engine and painters as the interactive desktop."""
    started = time.perf_counter()
    doc = fixture(case)
    fixture_ms = (time.perf_counter() - started) * 1000
    vm = MainWindowViewModel(
        ApplicationInfo(), documents=doc, preferences=PreferencesStore(output / "preferences.json")
    )
    if catalog_cache is not None:
        vm.content.library.cache_root = catalog_cache
    window = MainWindow(vm)
    window.resize(1440, 900)
    window.show()
    scene = doc.project.scenes[0]
    expected = {m.asset_id for m in scene.meshes if m.asset_id}
    deadline = time.monotonic() + 30
    while (
        vm.content.busy
        or not window.viewport.pose
        or not expected.issubset(window.viewport.artwork.images)
    ) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    if vm.content.busy:
        window.confirm_discard = lambda: True
        window.close()
        raise RuntimeError("Content preparation did not finish; warm-editor timings are invalid")
    if not expected.issubset(window.viewport.artwork.images):
        raise RuntimeError("Artwork decoding did not finish before the benchmark deadline")
    for _ in range(3):
        app.processEvents()
    vm.playback.timer.stop()
    viewport = window.viewport
    viewport.mesh_wireframe = case == "dense-wireframe"
    bone = scene.skeletons[0].bones[-2].id
    index = [0]

    def changed_frame():
        """Force fresh geometry, then paint the changed pose rather than the retained layer."""
        index[0] += 1
        viewport.set_pose(doc.animation.evaluate((index[0] * 0.37) % 20))
        return viewport.grab()

    def cold_paint():
        """Force uncached source rendering, as when adopting newly generated topology."""
        viewport._artwork_pose = None
        viewport._mesh_layers.clear()
        return viewport.grab()

    def pointer(kind, position, button, buttons):
        """Deliver navigation through the widget's real editor event filters."""
        app.sendEvent(
            viewport,
            QMouseEvent(kind, position, position, button, buttons, Qt.KeyboardModifier.NoModifier),
        )

    pointer_position = QPointF(100, 100)

    def pan():
        """Include a hand-tool input and completed repaint at a different camera position."""
        nonlocal pointer_position
        pointer_position += QPointF(7, 5)
        pointer(
            QEvent.Type.MouseMove,
            pointer_position,
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
        )
        return viewport.grab()

    def pan_timing():
        """Measure one navigation gesture without retaining its camera or tool changes."""
        pan_origin, pan_tool = QPointF(viewport.offset), viewport.pan_tool
        viewport.pan_tool = True
        pointer(
            QEvent.Type.MouseButtonPress,
            pointer_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
        )
        result = measure(pan, samples)
        pointer(
            QEvent.Type.MouseButtonRelease,
            pointer_position,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
        )
        viewport.pan_tool = pan_tool
        viewport.offset = pan_origin
        return result

    pan_result = pan_timing()
    selected_pan = mesh_pan = None
    if scene.objects:
        vm.scene.select((scene.objects[0].id,))
        selected_pan = pan_timing()
        vm.scene.select(())
    if case == "dense-wireframe":
        vm.mesh.select_mesh(scene.meshes[0].id)
        window.mesh_workspace.set_mode(True)
        mesh_pan = pan_timing()
        window.mesh_workspace.set_mode(False)

    results = {
        "fixture_ms": round(fixture_ms, 3),
        "objects": len(scene.objects),
        "bones": sum(len(r.bones) for r in scene.skeletons),
        "triangles": sum(len(m.triangles) for m in scene.meshes),
        "metadata_mib": round(
            len(json.dumps(doc.project.to_dict(), ensure_ascii=False, indent=2).encode("utf8"))
            / 1024**2,
            2,
        ),
        "hand_pan": pan_result,
        "hand_pan_selected": selected_pan,
        "hand_pan_mesh": mesh_pan,
        "evaluate": measure(lambda: doc.animation.evaluate(9.25), samples),
        "cold_paint": measure(cold_paint, samples),
        "changed_frame_paint": measure(changed_frame, samples),
        "cached_paint": measure(viewport.grab, samples),
        "hover": measure(lambda: viewport.refresh_cursor(QPointF(200, 220)), samples),
        "select": measure(lambda: vm.scene.select((bone,)), samples),
    }
    vm.rig.active = True
    vm.rig.select(bone)
    vm.rig.begin_preview()
    x, y = vm.rig.pose.nodes[bone].world_matrix[4:]

    def drag():
        """Include live geometry and painting for an actual bone move preview."""
        index[0] += 1
        vm.rig.preview_drag(bone, "move", x + 5 + index[0] % 9, y + 5)
        if vm.rig.error:
            raise RuntimeError(vm.rig.error)
        viewport.grab()

    results["bone_drag"] = measure(drag, samples)

    def rotate():
        """Measure changing default FK poses, retaining the same gesture baseline."""
        index[0] += 1
        vm.rig.preview_drag(bone, "chain_rotate", 3 + index[0] % 9, 0)
        if vm.rig.error:
            raise RuntimeError(vm.rig.error)
        viewport.grab()

    results["fk_drag"] = measure(rotate, samples)
    vm.rig.cancel_preview()
    results["document_refresh"] = measure(window.refresh_document, samples)
    if case == "willow":
        doc.animation.seek(60)
        doc.animation.play()

        def playback():
            """Include late-clip spring integration, skin evaluation and the completed repaint."""
            viewport.set_pose(doc.animation.advance(1 / scene.settings.fps))
            return viewport.grab()

        results["sequential_playback"] = measure(playback, samples)
        doc.animation.pause()
    window.confirm_discard = lambda: True
    window.close()
    app.processEvents()
    print(case, json.dumps(results), flush=True)
    return results


def benchmark_tabs(samples, app, output, catalog_cache=None):
    """Cycle three fully loaded detailed projects, including UI binding and completed paints."""
    doc = fixture("boy")
    vm = MainWindowViewModel(
        ApplicationInfo(), documents=doc, preferences=PreferencesStore(output / "tabs-ui.json")
    )
    built = build_character(replace(character_preset("Ribbon"), motions=("Walk",)))
    for i in range(2):
        added = vm.workspace.new(f"Detailed project {i + 2}")
        CharacterCreationService(added).create(built)
    if catalog_cache is not None:
        vm.content.library.cache_root = catalog_cache
    window = MainWindow(vm)
    window.resize(1440, 900)
    window.show()
    for i, document in enumerate(vm.workspace.documents):
        vm.activate_project(i)
        expected = {m.asset_id for m in document.project.scenes[0].meshes if m.asset_id}
        deadline = time.monotonic() + 30
        while (
            vm.content.busy or not expected.issubset(window.viewport.artwork.images)
        ) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.005)
        if vm.content.busy or not expected.issubset(window.viewport.artwork.images):
            raise RuntimeError("A project tab did not finish decoding")
        window.viewport.grab()
    loads = []
    submit = window.mesh_workspace.submit

    def record(*args):
        """Count redundant decoding after all three tab caches have warmed."""
        loads.append(1)
        return submit(*args)

    window.mesh_workspace.submit = record
    index = [2]

    def switch():
        """Activate a different document, then finish queued UI work and the actual paint."""
        index[0] = (index[0] + 1) % 3
        vm.activate_project(index[0])
        app.processEvents()
        window.viewport.grab()

    result = {
        "projects": 3,
        "triangles": sum(
            len(m.triangles) for d in vm.workspace.documents for m in d.project.scenes[0].meshes
        ),
        "switch_and_paint": measure(switch, samples),
        "redundant_decodes": len(loads),
        "cached_raster_mib": round(
            sum(
                image.sizeInBytes()
                for state in window.mesh_workspace.artwork_tabs.values()
                for image in state.cache.images.values()
            )
            / 1024**2,
            2,
        ),
        "inactive_playing": sum(
            d.animation.playback.is_playing for d in vm.workspace.documents if d is not vm.documents
        ),
    }
    window.confirm_discard = lambda: True
    window.close()
    app.processEvents()
    print("tabs", json.dumps(result), flush=True)
    return result


def main():
    """Write repeatable measurements for ordinary and dense editor workloads."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        choices=(
            "all",
            "bones",
            "sources",
            "boy",
            "girl",
            "three-characters",
            "ten-characters",
            "dense-wireframe",
            "willow",
            "tabs",
        ),
        default="all",
    )
    parser.add_argument(
        "--catalog-cache", type=Path, help="Prepared content cache root for warm measurements"
    )
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--output", type=Path, default=Path("build/performance"))
    args = parser.parse_args()
    if not 1 <= args.samples <= 100:
        parser.error("samples must be between 1 and 100")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication([])
    # The Windows offscreen plugin can discover only bundled icon fonts. Register
    # the normal OS text face so diagnostic timings include readable scene labels.
    if os.name == "nt" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        font = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "Fonts/segoeui.ttf"
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    cases = (
        (
            "bones",
            "sources",
            "boy",
            "girl",
            "three-characters",
            "ten-characters",
            "dense-wireframe",
            "willow",
            "tabs",
        )
        if args.case == "all"
        else (args.case,)
    )
    results = {
        case: benchmark_tabs(args.samples, app, args.output, args.catalog_cache)
        if case == "tabs"
        else benchmark(case, args.samples, app, args.output, args.catalog_cache)
        for case in cases
    }
    (args.output / "workspace.json").write_text(json.dumps(results, indent=2), encoding="utf8")


if __name__ == "__main__":
    main()
