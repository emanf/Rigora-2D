"""Anatomical mapping and correction controls for non-destructive motion transfer."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from rigora.application_services.documents import DocumentService
from rigora.application_services.retargeting import PROFILES, RetargetService, suggest_mapping
from rigora.domain.entities import Skeleton
from rigora.domain.project import ProjectError
from rigora.presentation.widgets.file_dialogs import choose_open_file
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class RetargetDialog(CustomDialog):
    """Map source bones explicitly and preview a scratch clip before publishing one command."""

    def __init__(self, window: "MainWindow") -> None:
        """Capture a document revision and expose profiles, omissions and per-bone corrections."""
        super().__init__(window, "Retarget motion")
        self.host = window
        self.document = window.viewmodel.documents
        self.revision = self.document.project
        self.source = self.document
        self.scratch: DocumentService | None = None
        self.resize(820, 650)
        box = QVBoxLayout(self.content)
        info = QLabel(
            "Transfer a clip into a new editable clip. Unmapped bones keep their rest pose. "
            "Source timing is preserved in seconds; mapped target controls use baked FK."
        )
        info.setWordWrap(True)
        box.addWidget(info)
        row = QHBoxLayout()
        self.source_label = QLabel("Source: current project")
        row.addWidget(self.source_label, 1)
        button = QPushButton(window.icons.icon("folder_open"), "Open source project…")
        button.clicked.connect(self.open_source)
        row.addWidget(button)
        box.addLayout(row)
        form = QFormLayout()
        self.clip, self.src, self.dst, self.profile = (QComboBox() for _ in range(4))
        self.profile.addItems(list(PROFILES))
        for label, widget in (
            ("Source clip", self.clip),
            ("Source skeleton", self.src),
            ("Target skeleton", self.dst),
            ("Mapping profile", self.profile),
        ):
            widget.setAccessibleName(label)
            form.addRow(label, widget)
        box.addLayout(form)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Source bone", "Target bone", "Rotation offset °", "Rotation gain"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        box.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        box.addWidget(self.status)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setAccessibleName("Retarget preview time")
        self.slider.valueChanged.connect(self.show_preview)
        box.addWidget(self.slider)
        commands = QHBoxLayout()
        for title, icon, callback in (
            ("Auto map", "auto_fix_high", self.populate),
            ("Preview", "play_arrow", self.preview),
            ("Create clip", "add", self.apply),
        ):
            button = QPushButton(window.icons.icon(icon), title)
            button.setProperty("materialIcon", icon)
            button.clicked.connect(callback)
            commands.addWidget(button)
        box.addLayout(commands)
        self.fill_sources()
        for widget in (self.src, self.dst, self.profile):
            widget.currentIndexChanged.connect(self.populate)
        self.finished.connect(lambda _: window.viewmodel.animation_editor.clear_key_preview())
        self.populate()

    def fill_sources(self) -> None:
        """Rebuild source choices from a loaded project's immutable scene records."""
        self.clip.clear()
        self.src.clear()
        if self.source.project:
            scene = self.source.scene
            for clip in scene.clips:
                self.clip.addItem(clip.name, clip.id)
            for rig in scene.skeletons:
                self.src.addItem(rig.name, rig.id)
        self.dst.clear()
        if self.document.project:
            for rig in self.document.scene.skeletons:
                self.dst.addItem(rig.name, rig.id)
        if self.dst.count() > 1 and self.source is self.document:
            self.dst.setCurrentIndex(1)

    def open_source(self) -> None:
        """Load a read-only source document without replacing the target project tab."""
        path, _ = choose_open_file(self, "Source project", "", "Rigora projects (*.rigora)")
        if path:
            try:
                source = self.document.fork()
                source.open(Path(path))
                self.source = source
                self.source_label.setText(f"Source: {Path(path).name}")
                self.fill_sources()
                self.populate()
            except (ProjectError, OSError) as error:
                self.status.setText(str(error))

    def skeletons(self) -> tuple[Skeleton, Skeleton]:
        """Resolve current choices and reject stale or absent project content."""
        if (
            self.document.project is not self.revision
            or self.host.viewmodel.documents is not self.document
        ):
            raise ProjectError("Project changed. Reopen retargeting to refresh the mappings.")
        if not self.source.project or not self.document.project:
            raise ProjectError("Open projects with source and target skeletons first.")
        try:
            return (
                next(r for r in self.source.scene.skeletons if r.id == self.src.currentData()),
                next(r for r in self.document.scene.skeletons if r.id == self.dst.currentData()),
            )
        except StopIteration as error:
            raise ProjectError("Create or choose source and target skeletons first.") from error

    def populate(self) -> None:
        """Suggest unique anatomical matches while leaving every target and correction editable."""
        self.scratch = None
        try:
            source, target = self.skeletons()
            mapping = suggest_mapping(source, target, self.profile.currentText())
            self.table.setRowCount(len(source.bones))
            for row, bone in enumerate(source.bones):
                item = QTableWidgetItem(bone.name)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, 0, item)
                combo = QComboBox()
                combo.addItem("Skip / missing", "")
                for other in target.bones:
                    combo.addItem(other.name, other.id)
                combo.setCurrentIndex(max(0, combo.findData(mapping.get(bone.id, ""))))
                self.table.setCellWidget(row, 1, combo)
                for column, initial in ((2, 0), (3, 1)):
                    field = QDoubleSpinBox()
                    field.setRange(-3600 if column == 2 else -10, 3600 if column == 2 else 10)
                    field.setDecimals(3)
                    field.setValue(initial)
                    self.table.setCellWidget(row, column, field)
            self.status.setText(
                f"Matched {len(mapping)} of {len(source.bones)} source bones. "
                "Check left/right limbs and adjust rest-angle corrections below."
            )
        except ProjectError as error:
            self.table.setRowCount(0)
            self.status.setText(str(error))

    def transfer(self, document: DocumentService) -> None:
        """Apply the explicit table to the canonical service on a scratch or real document."""
        source, target = self.skeletons()
        mapping, offsets, gains = {}, {}, {}
        for row, bone in enumerate(source.bones):
            combo = self.table.cellWidget(row, 1)
            offset, gain = self.table.cellWidget(row, 2), self.table.cellWidget(row, 3)
            assert (
                isinstance(combo, QComboBox)
                and isinstance(offset, QDoubleSpinBox)
                and isinstance(gain, QDoubleSpinBox)
            )
            if key := combo.currentData():
                mapping[bone.id], offsets[key], gains[key] = key, offset.value(), gain.value()
        result = RetargetService(document).apply(
            self.source,
            str(self.clip.currentData()),
            source.id,
            target.id,
            mapping,
            profile=self.profile.currentText(),
            rotation_offsets=offsets,
            rotation_gains=gains,
        )
        self.status.setText(
            f"{len(result.mapped)} mapped bones; {result.samples} sampled poses. "
            f"Skipped: {', '.join(result.missing) or 'none'}."
        )

    def preview(self) -> None:
        """Build one isolated clip and scrub its evaluated pose without modifying history."""
        try:
            self.host.viewmodel.playback.pause()
            scratch = self.document.fork()
            self.transfer(scratch)
            self.scratch = scratch
            self.show_preview()
        except (ProjectError, ValueError, TypeError) as error:
            self.status.setText(str(error))

    def show_preview(self) -> None:
        """Display the scratch pose at the normalized preview slider time."""
        if self.scratch:
            span = self.scratch.animation.playback.range
            frame = span.start + (span.end - span.start) * self.slider.value() / 1000
            editor = self.host.viewmodel.animation_editor
            editor.preview_pose = self.scratch.animation.evaluate(frame)
            editor.key_preview_changed.emit()

    def apply(self) -> None:
        """Publish one undoable target clip and restore the ordinary timeline and viewport."""
        editor = self.host.viewmodel.animation_editor
        editor.run(lambda _: self.transfer(self.document))
        if editor.error:
            self.status.setText(editor.error)
        else:
            self.accept()
