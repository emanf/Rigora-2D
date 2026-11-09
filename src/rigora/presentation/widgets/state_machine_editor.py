"""State/condition tables and live input previews over original Object actions."""

import json
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QElapsedTimer, QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QHideEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rigora.application_services.characters import CharacterService
from rigora.application_services.state_machines import StateMachinePreview, StateMachineService
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.state import ScenePose
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class StateMachineEditor(CustomDialog):
    """Save a small Object-owned state machine and inspect live input-driven action transitions."""

    def __init__(self, host: "MainWindow") -> None:
        """Keep graph authoring separate from transient playback, source keys and the playhead."""
        super().__init__(host, "Animation state machine")
        self.host, self.document = host, host.viewmodel.documents
        self.scene_id, self.context = self.document.scene.id, self.document.animation_context
        self.clip_id = self.document.selected_clip_id
        self.machine: StateMachinePreview | None = None
        self.source = self.document.project
        self.last_pose: Any = None
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.clock = QElapsedTimer()
        self.resize(860, 780)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        box.addLayout(form)
        self.owner, self.input_name = QComboBox(), QComboBox()
        chars = CharacterService(self.document)
        for key in chars.scene_objects():
            self.owner.addItem(chars.record(key).name, key)
        if self.context:
            self.owner.setCurrentIndex(max(0, self.owner.findData(self.context)))
        self.initial = QLineEdit()
        self.defaults = QLineEdit('{"speed": 0}')
        self.defaults.setAccessibleName("Initial parameters as a JSON object")
        form.addRow("Object", self.owner)
        form.addRow("Initial state", self.initial)
        form.addRow("Parameter defaults · JSON", self.defaults)
        self.states = QTableWidget(0, 4)
        self.states.setHorizontalHeaderLabels(("State", "Source action", "Speed ×", "Loop"))
        self.states.horizontalHeader().setStretchLastSection(True)
        box.addWidget(QLabel("States"))
        box.addWidget(self.states, 1)
        state_buttons = QHBoxLayout()
        box.addLayout(state_buttons)
        for label, callback in (("Add state", self.add_state), ("Remove state", self.remove_state)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            state_buttons.addWidget(button)
        self.transitions = QTableWidget(0, 6)
        self.transitions.setHorizontalHeaderLabels(
            ("From · * = any", "To", "Parameter", "Compare", "Value · JSON", "Blend fr")
        )
        self.transitions.horizontalHeader().setStretchLastSection(True)
        box.addWidget(QLabel("Transitions · first matching condition wins"))
        box.addWidget(self.transitions, 1)
        transition_buttons = QHBoxLayout()
        box.addLayout(transition_buttons)
        for label, callback in (
            ("Add transition", self.add_transition),
            ("Remove transition", self.remove_transition),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            transition_buttons.addWidget(button)
        preview = QHBoxLayout()
        box.addLayout(preview)
        self.input_value = QLineEdit("0")
        preview.addWidget(self.input_name)
        preview.addWidget(self.input_value)
        for label, callback in (
            ("Set input", self.set_input),
            ("Start / reset preview", self.start_preview),
            ("Stop preview", self.stop_preview),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            preview.addWidget(button)
        self.note = QLabel(
            "Save the machine, then preview its parameter-driven crossfades. "
            "Source actions remain editable; preview inputs do not alter their keys."
        )
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        row = QHBoxLayout()
        box.addLayout(row)
        for label, footer_callback in (("Save machine", self.save), ("Close", self.close)):
            button = QPushButton(label)
            button.clicked.connect(footer_callback)
            row.addWidget(button)
        self.owner.currentIndexChanged.connect(self.load)
        self.load()

    def check(self) -> None:
        """Reject another document, scene, view/context or action selected during this session."""
        if (
            self.host.viewmodel.documents is not self.document
            or self.document.scene.id != self.scene_id
            or self.document.animation_context != self.context
            or self.document.selected_clip_id != self.clip_id
        ):
            raise ProjectError("Reopen State machine in the active workspace.")

    def add_state(
        self, name: str = "", clip: str = "", speed: float = 1, loop: bool = True
    ) -> None:
        """Append one editable source-action row without saving it yet."""
        if isinstance(name, bool):
            name = ""
        if not self.owner.currentData() or self.states.rowCount() >= 32:
            return
        row = self.states.rowCount()
        self.states.insertRow(row)
        self.states.setItem(row, 0, QTableWidgetItem(name or f"State {row + 1}"))
        source = QComboBox()
        for action in CharacterService(self.document).motions(self.owner.currentData()):
            source.addItem(action.name, action.id)
        source.setCurrentIndex(max(0, source.findData(clip)))
        self.states.setCellWidget(row, 1, source)
        self.states.setItem(row, 2, QTableWidgetItem(str(speed)))
        item = QTableWidgetItem()
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if loop else Qt.CheckState.Unchecked)
        self.states.setItem(row, 3, item)

    def remove_state(self) -> None:
        """Remove the selected unsaved state row; Save validates any dependent conditions."""
        if self.states.currentRow() >= 0:
            self.states.removeRow(self.states.currentRow())

    def add_transition(self, data: dict[str, Any] | None = None) -> None:
        """Append one ordered numeric/boolean comparison row."""
        if self.transitions.rowCount() >= 128:
            return
        if not isinstance(data, dict):
            data = {
                "from": "*",
                "to": self.initial.text(),
                "parameter": "speed",
                "operator": ">",
                "value": 0,
                "blend": 6,
            }
        row = self.transitions.rowCount()
        self.transitions.insertRow(row)
        for col, key in enumerate(("from", "to", "parameter", "operator", "value", "blend")):
            value = json.dumps(data[key]) if key == "value" else str(data[key])
            self.transitions.setItem(row, col, QTableWidgetItem(value))

    def remove_transition(self) -> None:
        """Remove the selected unsaved condition row."""
        if self.transitions.currentRow() >= 0:
            self.transitions.removeRow(self.transitions.currentRow())

    def load(self) -> None:
        """Restore saved graph tables, or seed states from the Object's existing source actions."""
        self.stop_preview()
        key = self.owner.currentData()
        if not key:
            return
        chars = CharacterService(self.document)
        data = json_copy(chars.record(key).extra.get("state_machine", {}))
        self.states.setRowCount(0)
        self.transitions.setRowCount(0)
        states = data.get("states") or [
            dict(name=c.name, clip=c.id, speed=1, loop=c.loop) for c in chars.motions(key)[:32]
        ]
        for state in states:
            self.add_state(
                state["name"], state["clip"], state.get("speed", 1), state.get("loop", True)
            )
        self.initial.setText(data.get("initial", states[0]["name"] if states else ""))
        self.defaults.setText(json.dumps(data.get("parameters", {"speed": 0})))
        for transition in data.get("transitions", ()):
            self.add_transition(transition)
        self.inputs(data.get("parameters", {"speed": 0}))

    def inputs(self, parameters: dict[str, Any]) -> None:
        """Refresh available live input names without touching saved defaults."""
        with QSignalBlocker(self.input_name):
            self.input_name.clear()
            self.input_name.addItems(list(parameters))

    @staticmethod
    def cell(table: QTableWidget, row: int, column: int) -> QTableWidgetItem:
        """Require complete user-editable rows before publishing a graph."""
        item = table.item(row, column)
        if item is None:
            raise ProjectError("Fill every state/transition field before saving.")
        return item

    def save(self) -> None:
        """Validate complete table contents and persist the graph as one Undo command."""
        self.stop_preview()

        def edit(_: object) -> None:
            self.check()
            try:
                parameters = json.loads(self.defaults.text())
                if not isinstance(parameters, dict):
                    raise ValueError("Parameter defaults must be a JSON object.")
                states = []
                for row in range(self.states.rowCount()):
                    source = self.states.cellWidget(row, 1)
                    assert isinstance(source, QComboBox)
                    states.append(
                        dict(
                            name=self.cell(self.states, row, 0).text(),
                            clip=source.currentData(),
                            speed=float(self.cell(self.states, row, 2).text()),
                            loop=self.cell(self.states, row, 3).checkState()
                            == Qt.CheckState.Checked,
                        )
                    )
                transitions = []
                for row in range(self.transitions.rowCount()):
                    values = [self.cell(self.transitions, row, col).text() for col in range(6)]
                    transitions.append(
                        dict(
                            zip(
                                ("from", "to", "parameter", "operator", "value", "blend"),
                                (*values[:4], json.loads(values[4]), float(values[5])),
                                strict=True,
                            )
                        )
                    )
            except ValueError as error:
                raise ProjectError(str(error)) from error
            StateMachineService(self.document).define(
                self.owner.currentData(), states, transitions, parameters, self.initial.text()
            )
            self.inputs(parameters)

        self.host.viewmodel.scene.run(edit)
        self.note.setText(
            self.host.viewmodel.scene.error
            or "State machine saved. Set live inputs during preview."
        )

    def start_preview(self) -> None:
        """Start/reset a source-preserving runtime simulation using current saved graph defaults."""
        self.stop_preview()
        try:
            self.check()
            self.source = self.document.project
            self.machine = StateMachinePreview(self.document, self.owner.currentData())
            self.host.viewmodel.playback.pause(snap=False)
            self.clock.start()
            self.timer.start()
            self.display()
        except ProjectError as error:
            self.note.setText(str(error))

    def set_input(self) -> None:
        """Change one runtime parameter; values are numbers/booleans, never expressions."""
        try:
            if self.machine is None:
                raise ProjectError("Start the preview before setting a live input.")
            self.machine.set_parameter(
                self.input_name.currentText(), json.loads(self.input_value.text())
            )
        except (ProjectError, ValueError) as error:
            self.note.setText(str(error))

    def display(self, pose: ScenePose | None = None) -> None:
        """Publish this window's pose through the shared preview presentation route."""
        if self.machine:
            pose = pose if pose is not None else self.machine.pose()
            self.host.viewmodel.animation_editor.preview_snapshot(self.machine.snapshot, pose)
            self.last_pose = pose
            self.note.setText(f"State: {self.machine.current} · frame {self.machine.frame:g}")

    def tick(self) -> None:
        """Stop stale simulations and evaluate elapsed preview time without source mutation."""
        try:
            self.check()
            if self.document.project is not self.source or (
                self.last_pose is not None
                and self.host.viewmodel.animation_editor.preview_pose is not self.last_pose
            ):
                self.stop_preview()
                return
            if self.machine:
                pose = self.machine.advance(min(1.0, self.clock.restart() / 1000))
                self.display(pose)
        except ProjectError as error:
            self.stop_preview()
            self.note.setText(str(error))

    def stop_preview(self) -> None:
        """Restore only the display pose owned by this window, retaining source keys/playhead."""
        self.timer.stop()
        if (
            self.last_pose is not None
            and self.host.viewmodel.animation_editor.preview_pose is self.last_pose
        ):
            self.host.viewmodel.animation_editor.clear_key_preview()
        self.machine, self.last_pose = None, None

    def hideEvent(self, event: QHideEvent) -> None:
        """Release this transient simulation on Close/Escape or workspace shutdown."""
        self.stop_preview()
        super().hideEvent(event)
