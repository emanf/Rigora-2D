"""Custom-chrome media import and render-queue controls for the canonical services."""

import math
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from rigora.application_services.output import FORMAT_NOTES, FORMATS, VIDEO_OPTIONS, OutputSettings
from rigora.application_services.rig_export import RIG_FORMATS
from rigora.domain.project import ProjectError
from rigora.presentation.widgets.file_dialogs import (
    choose_open_file,
    choose_open_files,
    choose_save_file,
)
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


def integer_field(value: int, maximum: int = 4096) -> QSpinBox:
    """Create a bounded editable integer setting with a useful default."""
    field = QSpinBox()
    field.setRange(1, maximum)
    field.setValue(value)
    return field


def frame_field(value: float, maximum: float = 1_000_000) -> QDoubleSpinBox:
    """Create a fractional-frame control that remains usable at long timeline positions."""
    field = QDoubleSpinBox()
    field.setRange(0, maximum)
    field.setDecimals(3)
    field.setValue(value)
    return field


class OutputDialog(CustomDialog):
    """Configure final output and inspect/cancel jobs while the editor remains usable."""

    def __init__(self, window: "MainWindow") -> None:
        """Bind reusable settings and queue history to the window's output ViewModel."""
        super().__init__(window, "Render & export")
        self.host, self.model = window, window.viewmodel.output
        self.resize(980, 820)
        self.setMinimumSize(780, 680)
        layout = QVBoxLayout(self.content)
        top = QLabel(
            "Render the camera view. Original vectors and live deformation are evaluated "
            "at the output resolution."
        )
        top.setWordWrap(True)
        layout.addWidget(top)
        form = QFormLayout()
        self.format = QComboBox()
        for key, (label, _) in FORMATS.items():
            self.format.addItem(label, key)
        self.format.setCurrentIndex(self.format.findData("png"))
        form.addRow("Format", self.format)
        self.path = QLineEdit(str(Path.cwd() / "output.png"))
        self.path.setAccessibleName("Export destination")
        browse = QPushButton(self.icons.icon("folder_open"), "Browse…")
        browse.setProperty("materialIcon", "folder_open")
        browse.clicked.connect(self.browse)
        row = QHBoxLayout()
        row.addWidget(self.path, 1)
        row.addWidget(browse)
        form.addRow("Destination", row)
        self.start, self.end = frame_field(0), frame_field(0)
        self.fps = frame_field(24, 240)
        self.fps.setMinimum(1)
        self.output_width, self.output_height = integer_field(1920), integer_field(1080)
        timing = QHBoxLayout()
        for label, field in (("From", self.start), ("To", self.end), ("FPS", self.fps)):
            field.setAccessibleName("Export " + label)
            timing.addWidget(QLabel(label))
            timing.addWidget(field)
        form.addRow("Sample range", timing)
        size = QHBoxLayout()
        for label, size_field in (("Width", self.output_width), ("Height", self.output_height)):
            size_field.setAccessibleName("Export " + label)
            size.addWidget(QLabel(label))
            size.addWidget(size_field)
        form.addRow("Resolution", size)
        self.transparent = QCheckBox("Transparent")
        self.transparent.setChecked(True)
        self.background = QLineEdit("#000000")
        self.background.setAccessibleName("Export background color")
        background_row = QHBoxLayout()
        background_row.addWidget(self.transparent)
        background_row.addWidget(self.background)
        form.addRow("Background", background_row)
        self.background.setEnabled(False)
        self.transparent.toggled.connect(lambda checked: self.background.setEnabled(not checked))
        self.loop, self.bones = QCheckBox("Loop animation"), QCheckBox("Include bones")
        self.loop.setChecked(True)
        toggles = QHBoxLayout()
        self.audio = QCheckBox("Include clip audio")
        self.audio.setChecked(True)
        self.audio.setToolTip("Include attached clip audio in videos and editable rig packages.")
        toggles.addWidget(self.loop)
        toggles.addWidget(self.bones)
        toggles.addWidget(self.audio)
        form.addRow("Options", toggles)
        self.columns = integer_field(8, 64)
        form.addRow("Atlas columns", self.columns)
        saved_encoder = str(window.viewmodel.preferences.data.get("video_encoder_path", ""))
        self.encoder = QLineEdit(
            saved_encoder if Path(saved_encoder).is_file() else shutil.which("ffmpeg") or ""
        )
        self.encoder.setAccessibleName("Approved FFmpeg executable")
        encoder_row = QHBoxLayout()
        encoder_row.addWidget(self.encoder, 1)
        select_encoder = QPushButton(self.icons.icon("folder_open"), "Choose…")
        select_encoder.setProperty("materialIcon", "folder_open")
        select_encoder.clicked.connect(self.choose_encoder)
        encoder_row.addWidget(select_encoder)
        installed_encoder = QPushButton("Use installed")
        installed_encoder.setToolTip("Use FFmpeg from this computer's PATH; nothing is downloaded.")
        installed_encoder.clicked.connect(self.use_installed_encoder)
        encoder_row.addWidget(installed_encoder)
        self.encoder_row = form.rowCount()
        form.addRow("FFmpeg executable", encoder_row)
        self.form = form
        layout.addLayout(form)
        self.overwrite = QCheckBox("Replace existing output files")
        self.overwrite.setToolTip(
            "Explicit approval applies only to the files generated by this job."
        )
        layout.addWidget(self.overwrite)
        self.format_note = QLabel()
        self.format_note.setWordWrap(True)
        self.format_note.setObjectName("Muted")
        layout.addWidget(self.format_note)
        self.check_progress = QProgressBar()
        self.check_progress.setFixedHeight(3)
        self.check_progress.setTextVisible(False)
        self.check_progress.setRange(0, 0)
        self.check_progress.hide()
        layout.addWidget(self.check_progress)
        self.check_report = QPlainTextEdit()
        self.check_report.setReadOnly(True)
        self.check_report.setAccessibleName("Export preflight report")
        self.check_report.setMaximumHeight(130)
        self.check_report.hide()
        layout.addWidget(self.check_report)
        self.jobs = QTreeWidget()
        self.jobs.setHeaderLabels(["Job", "Status", "Progress", "Destination"])
        self.jobs.setRootIsDecorated(False)
        self.jobs.setMinimumHeight(160)
        self.jobs.setColumnWidth(0, 240)
        self.jobs.setColumnWidth(1, 110)
        self.jobs.setColumnWidth(2, 100)
        self.jobs.setAccessibleName("Render queue")
        layout.addWidget(self.jobs, 1)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.message)
        buttons = QHBoxLayout()
        self.cancel_button = QPushButton(self.icons.icon("cancel"), "Cancel selected job")
        self.cancel_button.setProperty("materialIcon", "cancel")
        self.cancel_button.clicked.connect(self.cancel_job)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        self.check_button = QPushButton(self.icons.icon("fact_check"), "Check export")
        self.check_button.setProperty("materialIcon", "fact_check")
        self.check_button.clicked.connect(lambda: self.enqueue(check_only=True))
        buttons.addWidget(self.check_button)
        self.queue_button = QPushButton(self.icons.icon("add_to_queue"), "Add to queue")
        self.queue_button.setProperty("materialIcon", "add_to_queue")
        self.queue_button.clicked.connect(self.enqueue)
        buttons.addWidget(self.queue_button)
        layout.addLayout(buttons)
        self.jobs.currentItemChanged.connect(self.refresh)
        self.model.changed.connect(self.refresh)
        self.format.currentIndexChanged.connect(self.update_format)
        self.reset_range()
        self.update_format()
        self.refresh()

    def reset_range(self) -> None:
        """Initialize output dimensions/range from the currently selected project and clip."""
        doc = self.host.viewmodel.documents
        if doc.project:
            scene = doc.scene
            self.output_width.setValue(scene.settings.width)
            self.output_height.setValue(scene.settings.height)
            self.fps.setValue(scene.settings.fps)
            self.start.setValue(doc.animation.evaluator.range.start)
            self.end.setValue(
                doc.animation.evaluator.range.end if scene.clips else doc.animation.pose.frame
            )

    def update_format(self) -> None:
        """Match file extension and expose only the selected exporter's settings."""
        kind = str(self.format.currentData())
        self.path.setText(str(Path(self.path.text()).with_suffix(FORMATS[kind][1])))
        self.form.setRowVisible(self.columns, kind in ("spritesheet", "godot", "unity", "unreal"))
        self.form.setRowVisible(self.encoder_row, kind in VIDEO_OPTIONS)
        self.encoder.setEnabled(kind in VIDEO_OPTIONS)
        self.audio.setEnabled(kind in VIDEO_OPTIONS or kind in RIG_FORMATS)
        self.bones.setEnabled(kind not in RIG_FORMATS)
        self.transparent.setEnabled(kind not in ("mp4", "svg", "runtime-json", *RIG_FORMATS))
        if kind == "mp4":
            self.transparent.setChecked(False)
        elif kind in (
            "svg",
            "runtime-json",
            "webm",
            "webm-vp8",
            "mov",
            "ffv1",
            "apng",
            *RIG_FORMATS,
        ):
            self.transparent.setChecked(True)
        self.format_note.setText(FORMAT_NOTES.get(kind, "Jobs stage privately before publication."))

    def browse(self) -> None:
        """Choose an output destination with the native OS file picker."""
        key = str(self.format.currentData())
        filename, _ = choose_save_file(
            self, "Export destination", self.path.text(), f"{FORMATS[key][0]} (*{FORMATS[key][1]})"
        )
        if filename:
            self.path.setText(filename)

    def choose_encoder(self) -> None:
        """Collect host approval for one local encoder executable without downloading binaries."""
        filename, _ = choose_open_file(
            self, "Choose FFmpeg executable", self.encoder.text(), "Executable (*)"
        )
        if filename:
            self.encoder.setText(filename)

    def use_installed_encoder(self) -> None:
        """Let the owner explicitly select a local PATH encoder without opening a file picker."""
        binary = shutil.which("ffmpeg")
        if binary:
            self.encoder.setText(binary)
        else:
            self.message.setText("FFmpeg was not found on PATH. Choose its installed executable.")

    def enqueue(self, check_only: bool = False) -> None:
        """Translate output FPS into scene-frame sample positions and submit a bounded snapshot."""
        if check_only and self.model.check_job is not None:
            self.model.check_cancel.set()
            return
        doc = self.host.viewmodel.documents
        if doc.project is None:
            self.message.setText("Create or open a project before exporting.")
            return
        try:
            first, last = self.start.value(), self.end.value()
            step = doc.scene.settings.fps / self.fps.value()
            count = math.floor((last - first) / step + 1e-8) + 1
            if not 1 <= count <= 600:
                raise ProjectError("Choose an increasing range containing 1–600 output frames.")
            settings = OutputSettings(
                format=str(self.format.currentData()),
                frames=tuple(first + i * step for i in range(count)),
                width=self.output_width.value(),
                height=self.output_height.value(),
                fps=self.fps.value(),
                sequence=count > 1,
                bones=self.bones.isChecked(),
                background=None if self.transparent.isChecked() else self.background.text(),
                loop=self.loop.isChecked(),
                columns=self.columns.value(),
                include_audio=self.audio.isChecked(),
            )
        except ProjectError as error:
            self.message.setText(str(error))
            return
        encoder = (
            Path(self.encoder.text())
            if settings.format in VIDEO_OPTIONS and self.encoder.text()
            else None
        )
        if check_only:
            self.model.preflight(doc, settings, encoder)
            return
        key = self.model.submit(
            doc, Path(self.path.text()).absolute(), settings, self.overwrite.isChecked(), encoder
        )
        if key and encoder:
            self.host.viewmodel.preferences.data["video_encoder_path"] = str(encoder)
        self.refresh()

    def cancel_job(self) -> None:
        """Cancel only the selected queued/rendering job, retaining already completed files."""
        row = self.jobs.currentItem()
        if row:
            self.model.cancel(str(row.data(0, Qt.ItemDataRole.UserRole)))

    def refresh(self, *args: Any) -> None:
        """Refresh lightweight progress rows without stealing selection or rebuilding settings."""
        checking = self.model.check_job is not None
        self.check_button.setText("Cancel check" if checking else "Check export")
        self.check_progress.setVisible(checking)
        result = self.model.check_result
        self.check_report.setVisible(result is not None)
        if result:
            metrics = result["metrics"]
            self.check_report.setPlainText(
                f"{result['format'].upper()} · "
                f"{'Ready' if result['ready'] else 'Needs attention'} · {result['coverage']}\n"
                f"{metrics['evaluated']} samples · {metrics['triangles']} peak triangles · "
                f"{metrics['source_bytes'] / 1048576:.1f} MiB sources\n"
                + "\n".join(f"{f['severity'].upper()}: {f['message']}" for f in result["findings"])
            )
        current = self.jobs.currentItem()
        selected = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        states = self.model.states()
        self.jobs.blockSignals(True)
        self.jobs.clear()
        for job in states:
            row = QTreeWidgetItem(
                [
                    job["project_name"] + " · " + job["format"].upper(),
                    job["status"].capitalize(),
                    f"{job['completed']} / {job['total']}",
                    self.model.paths.get(job["job_id"], ""),
                ]
            )
            row.setData(0, Qt.ItemDataRole.UserRole, job["job_id"])
            row.setToolTip(1, job["error"])
            row.setToolTip(0, job["project_name"] + "\n" + job["job_id"])
            row.setToolTip(3, self.model.paths.get(job["job_id"], ""))
            self.jobs.addTopLevelItem(row)
            if job["job_id"] == selected:
                self.jobs.setCurrentItem(row)
        self.jobs.blockSignals(False)
        active = next((j for j in states if j["job_id"] == selected), None)
        self.cancel_button.setEnabled(bool(active and active["can_cancel"]))
        error = self.model.error or (active["error"] if active else "")
        if not error and active and active.get("result"):
            error = "; ".join(active["result"].get("warnings", [])) or "Export completed."
        self.message.setText(error)


class MediaImportDialog(CustomDialog):
    """Import source media to the asset library with optional explicit scene placement."""

    def __init__(self, window: "MainWindow") -> None:
        """Expose sequence order, sprite geometry and layered-art compatibility choices."""
        super().__init__(window, "Add assets")
        self.host, self.model = window, window.viewmodel.media
        self.resize(750, 610)
        layout = QVBoxLayout(self.content)
        self.kind = QComboBox()
        for name, key in (
            ("Files · images / layered artwork / WAV", "assets_import"),
            ("Image sequence", "sequence_import"),
            ("Sprite sheet", "spritesheet_import"),
            ("Adobe PSD / Illustrator AI / OpenRaster", "layered_import"),
            ("PCM WAV audio", "audio_import"),
        ):
            self.kind.addItem(name, key)
        layout.addWidget(self.kind)
        self.paths = QPlainTextEdit()
        self.paths.setPlaceholderText("One file path per line. Sequence order follows this list.")
        self.paths.setAccessibleName("Media source paths in sequence order")
        self.paths.setMaximumHeight(160)
        layout.addWidget(self.paths)
        choose = QPushButton(self.icons.icon("folder_open"), "Choose source files…")
        choose.setProperty("materialIcon", "folder_open")
        choose.clicked.connect(self.browse)
        layout.addWidget(choose)
        self.form = QFormLayout()
        self.fps = frame_field(24, 240)
        self.fps.setMinimum(0.1)
        self.cell_width, self.cell_height = integer_field(128, 8192), integer_field(128, 8192)
        self.margin, self.spacing = integer_field(0, 8192), integer_field(0, 8192)
        self.margin.setMinimum(0)
        self.spacing.setMinimum(0)
        self.margin.setValue(0)
        self.spacing.setValue(0)
        self.count = integer_field(1, 256)
        self.count.setRange(0, 256)
        self.count.setSpecialValueText("All cells")
        self.count.setValue(0)
        for title, field in (
            ("Sequence FPS", self.fps),
            ("Cell width", self.cell_width),
            ("Cell height", self.cell_height),
            ("Margin", self.margin),
            ("Spacing", self.spacing),
            ("Frame count", self.count),
        ):
            field.setAccessibleName(title)
            self.form.addRow(title, field)
        layout.addLayout(self.form)
        self.place = QCheckBox("Also place the imported media in the scene")
        layout.addWidget(self.place)
        self.approximate = QCheckBox(
            "Accept pixel approximations · AI artboards flatten; PSD effects may differ"
        )
        layout.addWidget(self.approximate)
        self.message = QLabel(
            "Sources stay embedded. Double-click imported sequences or layered artwork "
            "in Project assets to place another instance. Use Animation → Face & lip-sync "
            "to attach WAV audio, hear playback and create mouth keys. Illustrator AI requires "
            "PDF compatibility and the approximation option; SVG preserves vectors."
        )
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        layout.addStretch()
        self.import_button = QPushButton(self.icons.icon("file_download"), "Import to project")
        self.import_button.setProperty("materialIcon", "file_download")
        self.import_button.clicked.connect(self.submit)
        layout.addWidget(self.import_button)
        self.kind.currentIndexChanged.connect(self.update_kind)
        self.model.changed.connect(self.refresh)
        self.model.imported.connect(self.completed)
        self.update_kind()

    def update_kind(self) -> None:
        """Show only settings that affect the selected source-media decoder."""
        kind = self.kind.currentData()
        self.form.setRowVisible(self.fps, kind in ("sequence_import", "spritesheet_import"))
        for field in (self.cell_width, self.cell_height, self.margin, self.spacing, self.count):
            self.form.setRowVisible(field, kind == "spritesheet_import")
        self.approximate.setVisible(kind in ("layered_import", "assets_import"))
        self.place.setVisible(kind != "audio_import")

    def browse(self) -> None:
        """Collect source files through the native OS file picker."""
        kind = str(self.kind.currentData())
        filters = {
            "assets_import": (
                "Project assets (*.png *.jpg *.jpeg *.svg *.bmp *.tif *.tiff "
                "*.gif *.webp *.psd *.psb *.ai *.ora *.wav)"
            ),
            "sequence_import": "Images (*.png *.jpg *.jpeg *.svg *.bmp *.tiff *.webp)",
            "spritesheet_import": "Raster sheets (*.png *.jpg *.jpeg *.bmp *.tiff *.webp)",
            "layered_import": "Adobe and layered artwork (*.ora *.psd *.psb *.ai)",
            "audio_import": "PCM audio (*.wav)",
        }
        if kind in ("sequence_import", "assets_import"):
            files = choose_open_files(
                self,
                "Choose project assets" if kind == "assets_import" else "Choose sequence frames",
                "",
                filters[kind],
            )
        else:
            filename, _ = choose_open_file(self, "Choose source media", "", filters[kind])
            files = [filename] if filename else []
        if files:
            self.paths.setPlainText("\n".join(sorted(files)))

    def submit(self) -> None:
        """Send explicit file order and settings to the import ViewModel's scratch worker."""
        files = [
            Path(line.strip()).absolute()
            for line in self.paths.toPlainText().splitlines()
            if line.strip()
        ]
        if not files:
            self.message.setText("Choose source files first.")
            return
        kind = str(self.kind.currentData())
        arguments: dict[str, Any] = {"path": str(files[0])}
        if kind not in ("sequence_import", "assets_import") and len(files) != 1:
            self.message.setText("This import type accepts one source file.")
            return
        if kind == "assets_import":
            arguments = {
                "paths": [str(p) for p in files],
                "place": self.place.isChecked(),
                "allow_unsupported": self.approximate.isChecked(),
            }
        elif kind == "sequence_import":
            arguments = {
                "paths": [str(p) for p in files],
                "fps": self.fps.value(),
                "place": self.place.isChecked(),
            }
        elif kind == "spritesheet_import":
            arguments.update(
                frame_width=self.cell_width.value(),
                frame_height=self.cell_height.value(),
                fps=self.fps.value(),
                margin=self.margin.value(),
                spacing=self.spacing.value(),
                count=self.count.value() or None,
                place=self.place.isChecked(),
            )
        elif kind == "layered_import":
            arguments.update(
                allow_unsupported=self.approximate.isChecked(), place=self.place.isChecked()
            )
        self.model.submit(
            kind, arguments, Path.cwd(), tuple(dict.fromkeys(p.parent for p in files))
        )

    def refresh(self) -> None:
        """Display progress/errors and prevent duplicate submissions while decoding."""
        self.import_button.setEnabled(not self.model.busy)
        if self.model.busy:
            self.message.setText(
                "Reading and validating source media… The editor remains available."
            )
        elif self.model.error:
            self.message.setText(self.model.error)

    def completed(self, data: dict[str, Any]) -> None:
        """Report the completed import and any explicitly accepted compatibility differences."""
        if "files" in data:
            lines = [f"Added {data['imported']} files · {data['failed']} failed"]
            lines.extend(f"{row['name']}: {row.get('error', 'Added')}" for row in data["files"])
            self.message.setText("\n".join(lines))
        else:
            self.message.setText(
                "Imported to Project assets. " + "; ".join(data.get("warnings", []))
            )
