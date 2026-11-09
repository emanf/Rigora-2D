"""Integrated tutorial actions and a dock using the public SDK and canonical Object transforms."""

from rigora.domain.entities import Group, SceneObject
from rigora.domain.project import ProjectError
from rigora.engine.sampling import number
from rigora.sdk import PluginContext, PluginRequest

PREFIX = "org.rigora.example.scene_tools"


def nudge(request: PluginRequest) -> dict[str, object]:
    """Move selected Object roots once; command dispatch owns Undo and presentation refresh."""
    distance = number(request.arguments.get("distance", 24), "Distance")
    if abs(distance) > 10000:
        raise ProjectError("Distance must be between -10000 and 10000 pixels.")
    characters = request.service("characters")
    keys = []
    for selected in request.state.get("selection", ()):
        root = characters.object_root(selected)
        key = root.id if root else selected
        if isinstance(characters.records().get(key), (Group, SceneObject)) and key not in keys:
            keys.append(key)
    if not keys:
        raise ProjectError("Select an Object or artwork in the Scene first.")
    scene = request.service("scene")
    scene.part_edit = scene.sprite_edit = True
    scene.transform(tuple(keys), dx=distance)
    if request.host:
        request.host.notify(f"Moved {len(keys)} Object(s) by {distance:g} pixels.")
    return {"object_ids": keys, "distance": distance}


def panel(request: PluginRequest, parent):
    """Construct Qt controls only when the desktop adopts the plugin's dock widget."""
    from PySide6.QtWidgets import QDoubleSpinBox, QLabel, QPushButton, QVBoxLayout, QWidget

    class NudgePanel(QWidget):
        """Retain the latest host request; never retain an authoring document across tabs."""

        def __init__(self):
            """Create one configurable command button under ordinary host widget ownership."""
            super().__init__(parent)
            layout = QVBoxLayout(self)
            self.message = QLabel()
            self.distance = QDoubleSpinBox()
            self.distance.setRange(-10000, 10000)
            self.distance.setValue(24)
            self.distance.setSuffix(" px")
            self.distance.setAccessibleName("Horizontal distance")
            self.button = QPushButton("Move selected Objects")
            layout.addWidget(self.message)
            layout.addWidget(self.distance)
            layout.addWidget(self.button)
            layout.addStretch()
            self.button.clicked.connect(self.apply)
            self.rigora_bind(request)

        def rigora_bind(self, current: PluginRequest) -> None:
            """Refresh selection state without editing data or capturing a stale document."""
            self.request = current
            selected = current.state.get("selection", ())
            self.message.setText(f"Selected entries: {len(selected)}")
            self.button.setEnabled(bool(current.state.get("project_id") and selected))

        def apply(self) -> None:
            """Dispatch through the host so failure rolls back and successful edits refresh."""
            try:
                self.request.run_command(PREFIX + ".nudge", {"distance": self.distance.value()})
            except ProjectError as error:
                self.message.setText(str(error))

    return NudgePanel()


def show_panel(request: PluginRequest) -> None:
    """Reveal the contributed dock when invoked from a desktop menu."""
    if request.host:
        request.host.show_panel(PREFIX + ".panel")


def register(context: PluginContext) -> None:
    """Declare controls without constructing widgets, reading files or mutating projects."""
    context.action(
        PREFIX + ".nudge",
        "Move Objects right 24 px",
        nudge,
        placements=(
            "menu:Object/Scene tools",
            "toolbar:Scene tools",
            "surface:object.actions",
            "context:scene",
        ),
        icon="arrow_forward",
        when=("project", "selection"),
    )
    context.register("panels", PREFIX + ".panel", "Scene Tools", panel)
    context.action(
        PREFIX + ".show",
        "Scene Tools panel",
        show_panel,
        placements=("menu:View/Plugin panels",),
        icon="tune",
    )
