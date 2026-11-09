"""Reusable settings and action-search dialogs; no project mutations in widgets."""

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from rigora.domain.project import Project, ProjectError, Scene, SceneSettings
from rigora.presentation.icons import IconProvider
from rigora.presentation.menu_labels import display_text
from rigora.presentation.widgets.window_frame import CustomDialog


def choose_composer_value(
    parent: QWidget, title: str, label: str, choices: list[str] | None = None
) -> tuple[str, bool]:
    """Choose a composer name/target with the shared custom caption and readable controls."""
    from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLineEdit

    dialog = CustomDialog(parent, title)
    dialog.resize(390, 180)
    box = QVBoxLayout(dialog.content)
    box.addWidget(QLabel(label))
    field: QComboBox | QLineEdit
    if choices is None:
        field = QLineEdit()
        field.setMaxLength(100)
    else:
        field = QComboBox()
        field.addItems(choices)
    box.addWidget(field)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    box.addWidget(buttons)
    accepted = dialog.exec() == CustomDialog.DialogCode.Accepted
    return (field.text() if isinstance(field, QLineEdit) else field.currentText()), accepted


class ProjectSettingsDialog(CustomDialog):
    """Reusable validated editor for project identity and first-scene canvas settings."""

    def __init__(
        self, parent: QWidget, project: Project | None = None, scene: Scene | None = None
    ) -> None:
        """Populate bounded form controls from an existing project or creation defaults."""
        super().__init__(parent)
        scene = scene or (project.scenes[0] if project else None)
        self.setWindowTitle("Project settings" if project else "New project")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        heading = QLabel("PROJECT SETTINGS" if project else "CREATE A PROJECT")
        heading.setObjectName("Eyebrow")
        layout.addWidget(heading)
        layout.addWidget(QLabel("An empty scene, ready for your next character."))
        form = QFormLayout()
        form.setSpacing(12)
        self.project_name = QLineEdit(project.name if project else "Untitled project")
        self.scene_name = QLineEdit(scene.name if scene else "Scene 01")
        self.project_name.setMaxLength(200)
        self.scene_name.setMaxLength(200)
        form.addRow("Project name", self.project_name)
        form.addRow("Scene name", self.scene_name)
        settings = scene.settings if scene else SceneSettings()
        self.initial_settings = settings
        self.fields: dict[str, QSpinBox] = {}
        for key, label, low, high in (
            ("width", "Canvas width · px", 1, 16384),
            ("height", "Canvas height · px", 1, 16384),
            ("fps", "Frame rate · fps", 1, 240),
            ("start_frame", "Start frame", 0, 10_000_000),
            ("end_frame", "End frame", 0, 10_000_000),
        ):
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setValue(getattr(settings, key))
            spin.setAccessibleName(label)
            self.fields[key] = spin
            form.addRow(label, spin)
        layout.addLayout(form)
        note = QLabel(
            "Pixels · origin at top left · X right, Y down.\nThe frame range bounds playback "
            "and timeline editing."
        )
        note.setObjectName("Muted")
        layout.addWidget(note)
        self.validation = QLabel()
        self.validation.setWordWrap(True)
        self.validation.setAccessibleName("Project validation error")
        layout.addWidget(self.validation)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            "Apply" if project else "Create project"
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.project_name.selectAll()
        self.project_name.setFocus()

    def accept(self) -> None:
        """Keep the dialog open with a validation explanation until its settings are valid."""
        try:
            name, scene_name, settings = self.values()
            Project(name=name, scenes=(Scene(name=scene_name, settings=settings),))
        except ProjectError as error:
            self.validation.setText(str(error))
            return
        super().accept()

    def values(self) -> tuple[str, str, SceneSettings]:
        """Return normalized names and validated settings while retaining optional metadata."""
        return (
            self.project_name.text().strip(),
            self.scene_name.text().strip(),
            SceneSettings(
                **{name: field.value() for name, field in self.fields.items()},
                extra=self.initial_settings.extra,
            ),
        )


class CommandPalette(CustomDialog):
    """Searchable launcher displaying context availability and shortcuts for registered actions."""

    def __init__(self, parent: QWidget, actions: Sequence[QAction], icons: IconProvider) -> None:
        """Build the search field and results list over a supplied action registry."""
        super().__init__(parent)
        self.setWindowTitle("Command palette")
        self.setMinimumSize(540, 380)
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(12, 12, 12, 12)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search actions…")
        self.search.addAction(icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setAccessibleName("Search commands")
        layout.addWidget(self.search)
        self.results = QListWidget()
        layout.addWidget(self.results)
        self.command_actions = list(actions)
        self.search.textChanged.connect(self.filter)
        self.results.itemActivated.connect(self.activate)
        self.search.returnPressed.connect(self.activate_current)
        self.filter("")

    def filter(self, text: str) -> None:
        """Show matching actions and explain why disabled results are unavailable."""
        self.results.clear()
        for index, action in enumerate(self.command_actions):
            label = display_text(action.text())
            if text.casefold() not in label.casefold():
                continue
            suffix = (
                f"    {action.shortcut().toString()}" if not action.shortcut().isEmpty() else ""
            )
            if not action.isEnabled():
                suffix = (
                    "    · Unavailable in this context"
                    if not action.property("futureFeature")
                    else "    · Not implemented yet"
                )
            item = QListWidgetItem(action.icon(), label + suffix)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(action.toolTip())
            if not action.isEnabled():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.results.addItem(item)
        self.results.setCurrentRow(0)

    def activate_current(self) -> None:
        """Invoke the selected result when Enter is pressed in the search field."""
        item = self.results.currentItem()
        if item is not None:
            self.activate(item)

    def activate(self, item: QListWidgetItem) -> None:
        """Close the palette and trigger an enabled action through its existing binding."""
        action = self.command_actions[item.data(Qt.ItemDataRole.UserRole)]
        if action.isEnabled():
            self.accept()
            action.trigger()
