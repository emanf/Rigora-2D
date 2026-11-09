"""Themed application messages and decisions with custom window chrome."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QMessageBox, QPushButton, QVBoxLayout, QWidget

from rigora.presentation.widgets.window_frame import CustomDialog


class MessageDialog(CustomDialog):
    """Embed a standard message layout while keeping window controls consistent."""

    def __init__(
        self,
        parent: QWidget,
        title: str,
        text: str,
        icon: QMessageBox.Icon,
        buttons: QMessageBox.StandardButton,
        default: QMessageBox.StandardButton,
    ) -> None:
        """Preserve standard button roles, default choice, and Escape cancellation semantics."""
        super().__init__(parent, title)
        self.setMinimumWidth(440)
        self.box = QMessageBox(icon, title, text, buttons, self.content)
        self.box.setTextFormat(Qt.TextFormat.PlainText)
        self.box.setWindowFlags(Qt.WindowType.Widget)
        self.box.setDefaultButton(default)
        self.box.buttonClicked.connect(
            lambda button: self.done(int(self.box.standardButton(button)))
        )
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(self.box)

    def showEvent(self, event: QShowEvent) -> None:
        """Keep the embedded message's default and actual keyboard focus on one safe choice."""
        super().showEvent(event)
        cancel = self.box.button(QMessageBox.StandardButton.Cancel)
        if cancel is not None:
            self.box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        button = self.box.defaultButton()
        if button is not None:
            button.setDefault(True)
            button.setFocus(Qt.FocusReason.OtherFocusReason)
            for other in self.content.findChildren(QPushButton):
                if other is not button:
                    other.setDefault(False)


def ask_question(
    parent: QWidget,
    title: str,
    text: str,
    buttons: QMessageBox.StandardButton,
    default: QMessageBox.StandardButton,
) -> QMessageBox.StandardButton:
    """Return a standard decision code; dismissing the caption is always cancellation."""
    dialog = MessageDialog(parent, title, text, QMessageBox.Icon.Question, buttons, default)
    result = dialog.exec()
    dialog.deleteLater()
    return QMessageBox.StandardButton(result) if result else QMessageBox.StandardButton.Cancel


def show_warning(parent: QWidget, title: str, text: str) -> None:
    """Display a recoverable error without altering the active document."""
    dialog = MessageDialog(
        parent,
        title,
        text,
        QMessageBox.Icon.Warning,
        QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Ok,
    )
    dialog.exec()
    dialog.deleteLater()


def show_information(parent: QWidget, title: str, text: str) -> None:
    """Display local application information using the common caption and palette."""
    dialog = MessageDialog(
        parent,
        title,
        text,
        QMessageBox.Icon.Information,
        QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Ok,
    )
    dialog.exec()
    dialog.deleteLater()
