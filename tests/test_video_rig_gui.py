"""The video rig workspace stays responsive, supports review and cannot publish stale workers."""

import io
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from PySide6.QtCore import QTimer
from test_roots_soft_drag_gui import editor as editor
from test_video_rig import specimen

from rigora.application_services.rigging import RigService
from rigora.domain.entities import Group
from rigora.presentation.widgets.video_rig import VideoRigDialog

pytestmark = pytest.mark.gui


def review_analysis():
    """Embed original deterministic preview pixels; models and media devices are unnecessary."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (320, 320), "#eeeeee")
    draw = ImageDraw.Draw(image)
    draw.ellipse((78, 0, 122, 44), fill="#bbbbbb")
    draw.rounded_rectangle((78, 50, 122, 145), radius=10, fill="#777777")
    for points in (
        ((80, 60), (40, 140)),
        ((120, 60), (160, 140)),
        ((85, 140), (75, 260)),
        ((115, 140), (125, 260)),
    ):
        draw.line(points, fill="#888888", width=14)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return replace(specimen(), image=stream.getvalue())


def test_video_window_background_analysis_review_corrections_publish_and_undo(
    editor, qtbot, monkeypatch, tmp_path
):
    """Background analysis and reviewed corrections publish one reusable scene Object."""
    from rigora.infrastructure.video_models import MODELS
    from rigora.presentation.viewmodels import video_rig

    analysis = review_analysis()
    entered, release = Event(), Event()

    def analyze(*args, cancel, progress, **kwargs):
        """Hold only the worker, exposing event-loop responsiveness and cancellation ownership."""
        entered.set()
        progress(0.5, "Analyzing movement")
        assert release.wait(5)
        return analysis

    monkeypatch.setattr(video_rig, "analyze_video", analyze)
    dialog = VideoRigDialog(editor)
    qtbot.addWidget(dialog)
    dialog.model.directory = tmp_path
    for key in MODELS:
        (tmp_path / (key + ".onnx")).write_bytes(b"test boundary")
    dialog.path = tmp_path / "clip.mp4"
    dialog.show()
    qtbot.waitExposed(dialog)
    baseline = editor.viewmodel.documents.project
    dialog.analyze_video()
    qtbot.waitUntil(entered.is_set)
    beats = []
    QTimer.singleShot(0, lambda: beats.append(True))
    qtbot.waitUntil(lambda: bool(beats))
    assert dialog.model.busy and not dialog.create_button.isEnabled()
    release.set()
    qtbot.waitUntil(lambda: not dialog.model.busy)
    assert dialog.create_button.isEnabled() and dialog.scrub.maximum() == 2
    dialog.correct_joint(9, 42, 138)
    assert dialog.model.analysis.poses[0].points[9] == (42, 138, 1)
    assert analysis.poses[0].points[9] != (42, 138, 1)
    dialog.set_reference()
    assert dialog.model.analysis.image == analysis.image
    dialog.output_mode.setCurrentIndex(1)
    dialog.create_character()
    qtbot.waitUntil(lambda: not dialog.model.busy, timeout=15000)
    assert not dialog.model.error
    document = editor.viewmodel.documents
    assert document.project is not baseline
    assert editor.viewmodel.scene.selected
    assert any(g.extra.get("video_rig_profile") for g in document.scene.groups)
    assert any(c.extra.get("motion_sequence") for c in document.scene.clips)
    assert len(document.history.undo_stack) == 1
    from rigora.domain.geometry import transform_point

    scale = min(document.scene.settings.width / 320, document.scene.settings.height / 320) * 0.8
    offset = (
        (document.scene.settings.width - 320 * scale) / 2,
        (document.scene.settings.height - 320 * scale) / 2,
    )
    bone = next(b for b in document.scene.skeletons[0].bones if b.name == "forearm.L")
    node = document.animation.evaluate(0).nodes[bone.id]
    assert transform_point(node.world_matrix, node.length, 0) == pytest.approx(
        (offset[0] + 42 * scale, offset[1] + 138 * scale)
    )
    assert not document.scene.objects and not document.scene.meshes
    Path("build").mkdir(exist_ok=True)
    dialog.grab().save("build/video-rig-window.png")
    document.undo()
    assert document.project == baseline
    dialog.close()


def test_video_create_rejects_stale_revision_and_late_closed_dialog(editor, qtbot, monkeypatch):
    """A completed analysis never overwrites edits made while the background rig was building."""
    from rigora.presentation.viewmodels import video_rig

    dialog = VideoRigDialog(editor)
    qtbot.addWidget(dialog)
    dialog.model.analysis = review_analysis()
    document = editor.viewmodel.documents
    entered, release, finished = Event(), Event(), Event()
    original = video_rig.VideoRigService.create

    def build(service, *args, **kwargs):
        """Delay publication while retaining actual service validation and animation compilation."""
        entered.set()
        assert release.wait(5)
        try:
            return original(service, *args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(video_rig.VideoRigService, "create", build)
    dialog.model.create("Tracked", 0.35, 0, False)
    qtbot.waitUntil(entered.is_set)
    RigService(document).commit(
        "Concurrent edit", groups=(*document.scene.groups, Group(name="Keep me"))
    )
    edited = document.project
    release.set()
    qtbot.waitUntil(lambda: not dialog.model.busy, timeout=15000)
    assert document.project is edited and "changed" in dialog.model.error
    entered.clear()
    release.clear()
    finished.clear()
    dialog.model.create("Cancelled", 0.35, 0, False)
    qtbot.waitUntil(entered.is_set)
    dialog.close()
    release.set()
    qtbot.waitUntil(finished.is_set)
    assert dialog.model.cancel.is_set() and document.project is edited


def test_preview_zoom_labels_ghost_and_length_locks(editor, qtbot):
    """Review overlays remain read-only and joint picking uses the zoomed/panned image transform."""
    import math

    from PySide6.QtCore import QPoint, QPointF, Qt

    from rigora.application_services.video_rig import segments

    dialog = VideoRigDialog(editor)
    qtbot.addWidget(dialog)
    analysis = review_analysis()
    # Keep the ghost away from all current joints to exercise unpickable geometry.
    ghost = replace(analysis.poses[0], points=((300, 300, 1),) * 17)
    analysis = replace(analysis, poses=(ghost, *analysis.poses[1:]))
    dialog.model.analysis = analysis
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.show_frame(analysis.image, 1)
    dialog.refresh()
    qtbot.mouseClick(dialog.previous, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(dialog.labels, Qt.MouseButton.LeftButton)
    assert dialog.preview.show_previous and dialog.preview.show_labels
    assert dialog.preview.previous_pose is ghost
    preview = dialog.preview
    preview.update_bounds()
    ratio = preview.bounds.width() / preview.image.width()
    ghost_point = preview.bounds.topLeft() + QPointF(300 * ratio, 300 * ratio)
    assert preview.hit(ghost_point) is None
    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton, pos=ghost_point.toPoint())
    assert dialog.model.analysis is analysis
    preview.zoom_by(1.5)
    assert preview.zoom == 1.5
    ratio = preview.bounds.width() / preview.image.width()
    x, y, _ = preview.pose.points[9]
    wrist = preview.bounds.topLeft() + QPointF(x * ratio, y * ratio)
    assert preview.hit(wrist) == 9
    qtbot.mousePress(preview, Qt.MouseButton.LeftButton, pos=wrist.toPoint())
    qtbot.mouseMove(preview, (wrist + QPointF(8, -5)).toPoint())
    qtbot.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=(wrist + QPointF(8, -5)).toPoint())
    moved = dialog.model.analysis.poses[1].points[9]
    assert moved[:2] == pytest.approx((x + 8 / ratio, y - 5 / ratio), abs=1)
    assert dialog.model.analysis.poses[0] is ghost
    snapshot = dialog.model.analysis
    qtbot.mousePress(preview, Qt.MouseButton.MiddleButton, pos=QPoint(100, 100))
    qtbot.mouseMove(preview, QPoint(130, 120))
    qtbot.mouseRelease(preview, Qt.MouseButton.MiddleButton, pos=QPoint(130, 120))
    assert preview.pan == QPointF(30, 20) and dialog.model.analysis is snapshot
    preview.fit()
    assert preview.zoom == 1 and preview.pan.isNull()
    assert dialog.length_lock.parentWidget() is dialog.transport
    qtbot.mouseClick(dialog.length_lock, Qt.MouseButton.LeftButton)
    assert len(dialog.model.analysis.locked_lengths) == 11
    assert dialog.length_lock.isChecked()
    before = segments("Human", dialog.preview.pose.points)
    x, y, _ = dialog.preview.pose.points[7]
    dialog.correct_joint(7, x + 15, y - 10)
    after = segments("Human", dialog.preview.pose.points)
    for role, (_, a, b) in before.items():
        _, c, d = after[role]
        assert math.dist(c[:2], d[:2]) == pytest.approx(math.dist(a[:2], b[:2]), abs=1e-6)
    qtbot.mouseClick(dialog.length_lock, Qt.MouseButton.LeftButton)
    assert not dialog.model.analysis.locked_lengths and not dialog.length_lock.isChecked()
    dialog.show_frame(analysis.image, 0)
    assert dialog.preview.previous_pose is None
    dialog.close()


def test_cutout_preview_and_final_art_share_exact_keyed_png(editor, qtbot, monkeypatch):
    """Creation reuses the reviewed PNG instead of recomputing a different mask."""
    from rigora.presentation.viewmodels import video_rig

    dialog = VideoRigDialog(editor)
    qtbot.addWidget(dialog)
    analysis = review_analysis()
    dialog.model.analysis = analysis
    dialog.show_frame(analysis.image, analysis.reference)
    calls, artwork = [], []
    image = io.BytesIO()
    from PIL import Image

    Image.new("RGBA", (320, 320), (100, 100, 100, 128)).save(image, format="PNG")
    png = image.getvalue()

    def key(data, settings, *, cancel):
        calls.append((data, settings))
        return png

    original = video_rig.VideoRigService.create

    def create(service, *args, **kwargs):
        artwork.append(kwargs["artwork"])
        return original(service, *args, **kwargs)

    monkeypatch.setattr(video_rig, "key_cutout", key)
    monkeypatch.setattr(video_rig.VideoRigService, "create", create)
    dialog.show_cutout()
    qtbot.waitUntil(lambda: not dialog.model.busy)
    assert not dialog.model.error and len(calls) == 1
    assert dialog.preview.image.toImage().pixelColor(0, 0).alpha() == 128
    assert dialog.frame_png == analysis.image
    dialog.create_character()
    qtbot.waitUntil(lambda: not dialog.model.busy, timeout=15000)
    assert not dialog.model.error
    assert len(calls) == 1 and artwork == [png]
    # Changed controls invalidate the single-entry preview cache.
    dialog.key_tolerance.setValue(0.3)
    dialog.show_cutout()
    qtbot.waitUntil(lambda: not dialog.model.busy)
    assert len(calls) == 2
    dialog.close()


@pytest.mark.parametrize("count", [1, 3])
def test_native_image_picker_flow_creates_still_or_animated_rig(
    editor, qtbot, monkeypatch, tmp_path, count
):
    """Still and sequence sources use the same review UI, retaining alpha without Blender."""
    from PIL import Image

    from rigora.infrastructure import video_rig
    from rigora.infrastructure.video_models import MODELS
    from rigora.presentation.widgets import video_rig as widget

    paths = []
    for index in reversed(range(count)):
        path = tmp_path / f"pose{index + 1}.png"
        image = Image.new("RGBA", (320, 320), (160, 160, 160, 255))
        image.putpixel((0, 0), (0, 0, 0, 0))
        image.save(path)
        paths.append(str(path))

    class Detector:
        def __init__(self, directory):
            pass

        def candidates(self, image, profile):
            return [("Human", (20.0, 10.0, 190.0, 290.0))]

        def pose(self, image, profile, box):
            return specimen().poses[0].points

        def close(self):
            pass

    monkeypatch.setattr(video_rig, "VideoDetector", Detector)
    monkeypatch.setattr(widget, "choose_open_files", lambda *a: paths)
    dialog = VideoRigDialog(editor)
    qtbot.addWidget(dialog)
    dialog.model.directory = tmp_path
    for key in MODELS:
        (tmp_path / (key + ".onnx")).write_bytes(b"model boundary")
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.choose_images()
    qtbot.waitUntil(lambda: not dialog.model.busy)
    assert not dialog.model.error and not dialog.preview.image.isNull()
    assert dialog.model.images[0].name == "pose1.png"
    assert dialog.start_field.isHidden() and dialog.duration_field.isHidden()
    dialog.sample_fps.setValue(12)
    dialog.analyze_video()
    qtbot.waitUntil(lambda: not dialog.model.busy)
    assert not dialog.model.error and len(dialog.model.analysis.poses) == count
    assert dialog.play.isEnabled() == (count > 1)
    dialog.correct_joint(9, 45, 135)
    dialog.create_character()
    qtbot.waitUntil(lambda: not dialog.model.busy, timeout=15000)
    assert not dialog.model.error
    assert bool(dialog.model.output["clip_id"]) == (count > 1)
    assert len(editor.viewmodel.documents.scene.meshes) == 1
    assert editor.command_actions["video_rig"].text() == "Media to Rig…"
    dialog.close()


def test_builtin_keyer_preview_and_creation_need_no_external_program(editor, qtbot, monkeypatch):
    """Actual opaque-screen processing feeds the same reviewed pixels into character skinning."""
    import subprocess

    from PIL import Image, ImageDraw

    from rigora.presentation.viewmodels import video_rig

    image = Image.new("RGB", (320, 320), "#00ff00")
    ImageDraw.Draw(image).rectangle((80, 50, 122, 145), fill="red")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    analysis = replace(specimen(), image=stream.getvalue())
    captured = []
    original = video_rig.VideoRigService.create

    def create(service, *args, **kwargs):
        captured.append(kwargs["artwork"])
        return original(service, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Media keying must never launch an external executable")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(video_rig.VideoRigService, "create", create)
    dialog = VideoRigDialog(editor)
    qtbot.addWidget(dialog)
    dialog.model.analysis = analysis
    dialog.show_frame(analysis.image, 0)
    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.refresh()
    assert not hasattr(dialog, "blender_button") and not hasattr(dialog, "bone_choice")
    dialog.show_cutout()
    qtbot.waitUntil(lambda: not dialog.model.busy)
    assert not dialog.model.error
    assert dialog.preview.image.toImage().pixelColor(0, 0).alpha() == 0
    assert dialog.preview.image.toImage().pixelColor(100, 100).getRgb() == (255, 0, 0, 255)
    cached = dialog.model.keyed_reference[1]
    dialog.create_character()
    qtbot.waitUntil(lambda: not dialog.model.busy, timeout=15000)
    assert not dialog.model.error and captured == [cached]
    assert len(editor.viewmodel.documents.scene.meshes) == 1
    dialog.close()
