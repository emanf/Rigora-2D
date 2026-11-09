"""Private loopback browser frames, canonical vector parity and explicit output lifecycle."""

import io
import urllib.error
import urllib.request

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.rendering import svg_frame, svg_pose
from rigora.domain.project import ProjectError
from rigora.infrastructure.broadcast import LocalBroadcast


def png_frame():
    """Create an actual transparent raster from the shared original-vector renderer."""
    import resvg_py

    doc = DocumentService()
    doc.new()
    pose = doc.animation.evaluate(0)
    assert svg_pose(doc, pose, width=64, height=36) == svg_frame(doc, 0, width=64, height=36)
    return resvg_py.svg_to_bytes(svg_string=svg_pose(doc, pose, width=64, height=36).decode())


def test_local_output_is_private_bounded_transparent_and_releases_its_listener():
    """No listener exists before Start; only the private session serves owned PNG bytes."""
    from PIL import Image

    output = LocalBroadcast()
    assert output.server is None
    address = output.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(address, timeout=2) as response:
            assert b"URL.createObjectURL" in response.read()
            assert response.headers["Cache-Control"] == "no-store"
        with opener.open(address + "frame.png", timeout=2) as response:
            assert response.status == 204
        with pytest.raises(urllib.error.HTTPError) as error:
            opener.open(address.split("/", 3)[0] + "//" + address.split("/", 3)[2] + "/", timeout=2)
        assert error.value.code == 404
        png = png_frame()
        output.publish(png)
        with opener.open(address + "frame.png", timeout=2) as response:
            served = response.read()
            assert served == png and response.headers["Content-Type"] == "image/png"
        with Image.open(io.BytesIO(served)) as image:
            assert image.size == (64, 36) and image.getextrema()[3] == (0, 0)
        with pytest.raises(ProjectError, match="PNG frame"):
            output.publish(b"invalid")
    finally:
        output.stop()
    assert output.frame is None and output.server is None and not output.url
    with pytest.raises(urllib.error.URLError):
        opener.open(address, timeout=1)


@pytest.mark.gui
def test_broadcast_controls_start_render_and_stop_on_project_change(qtbot, tmp_path):
    """The actual UI publishes vector frames without changing the project or taking focus."""
    from rigora.app.application import ApplicationInfo
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow

    vm = MainWindowViewModel(ApplicationInfo(), preferences=PreferencesStore(tmp_path / "ui.json"))
    host = MainWindow(vm)
    host.confirm_discard = lambda: True
    qtbot.addWidget(host)
    vm.new_project()
    original = vm.documents.project
    host.command_actions["broadcast"].trigger()
    dialog = host.broadcast_output
    qtbot.addWidget(dialog)
    assert dialog.output.server is None
    dialog.frame_width.setValue(64)
    dialog.frame_height.setValue(36)
    dialog.start()
    qtbot.waitUntil(lambda: dialog.output.frames > 0, timeout=5000)
    assert vm.documents.project is original and dialog.address.text().startswith(
        "http://127.0.0.1:"
    )
    vm.new_project()
    assert dialog.output.server is None and not dialog.timer.isActive()
    qtbot.waitUntil(lambda: dialog.job is None, timeout=5000)
    dialog.close()
