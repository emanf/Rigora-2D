"""Desktop discovery and actual raster verification of canonical SVG preview exports."""

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMessageBox

from rigora.api import RigoraAPI
from rigora.app.application import ApplicationInfo
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow


def test_svg_pixels_preserve_transparency_without_internal_mesh_seams(tmp_path, qapp):
    """A headless vector export paints continuous translucent art at the requested resolution."""
    source = tmp_path / "rectangle.svg"
    source.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
        '<rect width="100" height="100" fill="#cccccc"/></svg>',
        encoding="utf-8",
    )
    api = RigoraAPI(tmp_path)
    api.execute("project_create", {"width": 200, "height": 200})
    api.execute("asset_import", {"path": "rectangle.svg", "place": True})
    obj = api.document.project.scenes[0].objects[0]
    api.execute(
        "keyframe_set", {"owner_id": obj.id, "property_path": "opacity", "frame": 0, "value": 0.5}
    )
    api.execute("frame_render", {"path": "frame.svg", "width": 400, "height": 400})
    renderer = QSvgRenderer(QByteArray((tmp_path / "frame.svg").read_bytes()))
    image = QImage(400, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    assert renderer.isValid() and image.pixelColor(20, 20).alpha() == 0
    for y in range(110, 290, 7):
        for x in range(110, 290, 7):
            pixel = image.pixelColor(x, y)
            assert 126 <= pixel.alpha() <= 129 and 202 <= pixel.red() <= 206


def test_desktop_inspection_connection_config_and_preview_export(qtbot, tmp_path, monkeypatch):
    """Discoverable desktop controls inspect current state and export via a background API fork."""
    from rigora.presentation.views import main_window

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    window = MainWindow(vm)
    window.confirm_discard = lambda: True
    qtbot.addWidget(window)
    window.show()
    vm.new_project()
    api = RigoraAPI(tmp_path, document=vm.documents)
    api.execute("character_create", {"x": 900, "y": 350})
    baseline = vm.documents.project
    window.command_actions["automation"].trigger()
    dialog = window.automation_dialog
    qtbot.addWidget(dialog)
    dialog.root.setText(str(tmp_path))
    dialog.refresh()
    inspection = json.loads(dialog.inspect_output.toPlainText())
    assert inspection["data"]["counts"]["meshes"] == len(vm.documents.scene.meshes)
    config = json.loads(dialog.config_output.toPlainText())["mcpServers"]["rigora"]
    assert config["args"][-1] == str(tmp_path)
    destination = tmp_path / "preview.svg"
    monkeypatch.setattr(main_window, "choose_save_file", lambda *args: (str(destination), ""))
    window.command_actions["export"].trigger()
    qtbot.waitUntil(lambda: destination.exists() and not vm.content.busy, timeout=15000)
    assert b"<image" in destination.read_bytes() and vm.documents.project is baseline
    previous = destination.read_bytes()
    monkeypatch.setattr(main_window, "ask_question", lambda *args: QMessageBox.StandardButton.No)
    window.command_actions["export"].trigger()
    assert destination.read_bytes() == previous
    dialog.root.setText(str(tmp_path / "absent"))
    dialog.refresh()
    assert not dialog.config_output.toPlainText()
