"""Capture the real video conversion workspace offscreen with native inference review data."""

import json
import os
from pathlib import Path


def main() -> None:
    """Render the actual dialog using ignored artifacts and isolated preferences."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["RIGORA_PREFERENCES_PATH"] = str(Path("build/video-rig-review/ui.json").resolve())
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    from rigora.app.application import ApplicationInfo
    from rigora.application_services.video_rig import VideoAnalysis, VideoPose
    from rigora.infrastructure.preferences import PreferencesStore
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow
    from rigora.presentation.widgets.video_rig import VideoRigDialog

    app = QApplication([])
    font = Path(os.environ.get("WINDIR", "/nonexistent")) / "Fonts/segoeui.ttf"
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont("Segoe UI", 10))
    model = MainWindowViewModel(
        ApplicationInfo(), preferences=PreferencesStore(Path(os.environ["RIGORA_PREFERENCES_PATH"]))
    )
    host = MainWindow(model)
    host.confirm_discard = lambda: True
    model.new_project()
    directory = Path("build/video-rig-review")
    for name in ("human", "dog"):
        raw = json.loads((directory / f"{name}-analysis.json").read_text(encoding="utf-8"))
        raw["poses"] = tuple(
            VideoPose(pose["seconds"], tuple(tuple(point) for point in pose["points"]))
            for pose in raw["poses"]
        )
        raw["image"] = (directory / f"{name}-reference.png").read_bytes()
        raw["warnings"] = tuple(raw["warnings"])
        analysis = VideoAnalysis(**raw)
        dialog = VideoRigDialog(host)
        dialog.model.analysis = analysis
        dialog.model.path = dialog.path = directory / f"{name}.mp4"
        dialog.source_label.setText(dialog.path.name)
        dialog.name.setText("Recovered " + name)
        dialog.model.message = "Review tracked joints, then create an editable character."
        dialog.show()
        dialog.show_frame(analysis.image, analysis.reference)
        dialog.refresh()
        app.processEvents()
        dialog.grab().save(str(directory / f"{name}-window.png"))
        dialog.close()
    host.close()
    app.processEvents()


if __name__ == "__main__":
    main()
