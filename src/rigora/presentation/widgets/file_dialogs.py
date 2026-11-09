"""Use platform file pickers while keeping selection contracts shared by all dialogs."""

from PySide6.QtWidgets import QFileDialog, QWidget


def choose_open_file(parent: QWidget, title: str, directory: str, filters: str) -> tuple[str, str]:
    """Ask the OS for one existing file; cancellation returns an empty path and filter."""
    return QFileDialog.getOpenFileName(parent, title, directory, filters)


def choose_save_file(parent: QWidget, title: str, directory: str, filters: str) -> tuple[str, str]:
    """Collect a native save path; the document workflow owns overwrite confirmation."""
    return QFileDialog.getSaveFileName(
        parent, title, directory, filters, options=QFileDialog.Option.DontConfirmOverwrite
    )


def choose_open_files(parent: QWidget, title: str, directory: str, filters: str) -> list[str]:
    """Ask the OS for multiple files without scanning or decoding previews in Rigora.

    Qt selects the platform dialog on Windows, macOS and supported Linux desktops.
    Thumbnail availability follows the OS and installed preview providers. Qt falls
    back to its own browser when the current platform has no native dialog helper.
    """
    paths, _ = QFileDialog.getOpenFileNames(parent, title, directory, filters)
    return paths
