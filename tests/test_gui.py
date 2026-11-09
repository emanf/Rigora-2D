import json
import os
import subprocess
import sys

import pytest

pytest.importorskip("PySide6")

from rigora.app.application import ApplicationInfo
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.views.main_window import MainWindow

pytestmark = pytest.mark.gui


def test_window_displays_viewmodel(qtbot) -> None:
    model = MainWindowViewModel(ApplicationInfo())
    window = MainWindow(model)
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()
    assert window.windowTitle() == model.title
    assert "textured mesh" in model.message
    assert "deformation studies" in model.message
    assert window.accessibleName() == "Rigora 2D main window"
    window.close()
    assert not window.isVisible()


def test_real_bootstrap_event_loop_starts_and_closes() -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["RIGORA_LOG_LEVEL"] = "INFO"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from PySide6.QtCore import QTimer
from rigora.app.bootstrap import run_desktop
from rigora.app.config import ApplicationConfig
from rigora.presentation.views.main_window import MainWindow
original_show = MainWindow.show
def show_then_close(self):
    original_show(self)
    QTimer.singleShot(50, self.close)
MainWindow.show = show_then_close
raise SystemExit(run_desktop(ApplicationConfig()))
""",
        ],
        env=environment,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in result.stderr.splitlines() if line.startswith("{")]
    assert [record["event"] for record in records] == [
        "application.started",
        "application.stopped",
    ]


def test_bootstrap_rejects_an_existing_qt_application(qtbot) -> None:
    from rigora.app.bootstrap import run_desktop
    from rigora.app.config import ApplicationConfig

    with pytest.raises(RuntimeError, match="ownership"):
        run_desktop(ApplicationConfig())
