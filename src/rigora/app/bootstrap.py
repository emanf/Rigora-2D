"""Composition roots. Qt is imported only inside the desktop function."""

from rigora.app.application import ApplicationInfo, ApplicationRuntime
from rigora.app.config import ApplicationConfig


def run_headless(config: ApplicationConfig) -> ApplicationInfo:
    """Run an application diagnostic without importing or initializing Qt."""
    with ApplicationRuntime(config) as runtime:
        return runtime.info


def run_desktop(config: ApplicationConfig) -> int:
    """Own a desktop event loop and release application resources on every exit."""
    from PySide6.QtWidgets import QApplication

    from rigora.presentation.garbage_collection import GuiGarbageCollector
    from rigora.presentation.viewmodels.main_window import MainWindowViewModel
    from rigora.presentation.views.main_window import MainWindow

    if QApplication.instance() is not None:
        raise RuntimeError("Rigora desktop startup requires ownership of the Qt application.")
    with ApplicationRuntime(config) as runtime:
        import sys

        if sys.platform == "win32":
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Rigora.Desktop")
        application = QApplication([runtime.info.name])
        collector = GuiGarbageCollector(application)
        application.setApplicationName(runtime.info.name)
        application.setApplicationVersion(runtime.info.version)
        application.setOrganizationName("Rigora")
        application.setQuitOnLastWindowClosed(True)
        viewmodel = MainWindowViewModel(runtime.info, plugins=runtime.plugins)
        window = MainWindow(viewmodel)
        application.aboutToQuit.connect(runtime.shutdown)
        try:
            window.show()
            return application.exec()
        finally:
            window.close()
            collector.close()
