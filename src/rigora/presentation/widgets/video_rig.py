"""Preview-led local video-to-rig workspace with editable tracking review."""

import math
from bisect import bisect_right
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.video_rig import VideoPose, correct_pose, segments
from rigora.domain.project import ProjectError
from rigora.infrastructure.video_keying import KeyingSettings, border_color
from rigora.infrastructure.video_models import MODELS
from rigora.infrastructure.video_rig import ordered_images
from rigora.presentation.themes import palette_colors, transparency_brush
from rigora.presentation.viewmodels.video_rig import VideoRigViewModel
from rigora.presentation.widgets.file_dialogs import choose_open_file, choose_open_files
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow

HUMAN_JOINTS = (
    "Nose",
    "Left eye",
    "Right eye",
    "Left ear",
    "Right ear",
    "Left shoulder",
    "Right shoulder",
    "Left elbow",
    "Right elbow",
    "Left wrist",
    "Right wrist",
    "Left hip",
    "Right hip",
    "Left knee",
    "Right knee",
    "Left ankle",
    "Right ankle",
)
ANIMAL_JOINTS = (
    "Left eye",
    "Right eye",
    "Nose",
    "Neck",
    "Tail root",
    "Left shoulder",
    "Left elbow",
    "Left front paw",
    "Right shoulder",
    "Right elbow",
    "Right front paw",
    "Left hip",
    "Left knee",
    "Left rear paw",
    "Right hip",
    "Right knee",
    "Right rear paw",
)


class PosePreview(QWidget):
    """Paint a fitted source frame and observed skeleton; drag joints to correct this sample."""

    joint_moved = Signal(int, float, float)
    resized = Signal()
    region_changed = Signal(object)
    view_changed = Signal()
    color_picked = Signal(object)

    def __init__(self, parent: QWidget) -> None:
        """Create a dormant neutral viewport with no camera, player or decoder ownership."""
        super().__init__(parent)
        self.setMinimumSize(360, 300)
        self.setMouseTracking(True)
        self.image = QPixmap()
        self.pose: VideoPose | None = None
        self.previous_pose: VideoPose | None = None
        self.show_previous = False
        self.show_labels = False
        self.zoom = 1.0
        self.pan = QPointF()
        self.pan_start: QPointF | None = None
        self.picking_key = False
        self.profile, self.threshold = "Human", 0.35
        self.show_bones = True
        self.dragging: int | None = None
        self.drawing_region = False
        self.region_start: QPointF | None = None
        self.region: QRectF | None = None
        self.bounds = QRectF()
        self.setAccessibleName(
            "Video tracking preview; drag joints to correct the displayed sample"
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Notify floating transport placement after splitter or window resizing."""
        super().resizeEvent(event)
        self.update_bounds()
        self.view_changed.emit()
        self.resized.emit()

    def update_bounds(self) -> None:
        """Use one image transform for painting, picking, region selection and correction."""
        if self.image.isNull():
            self.bounds = QRectF()
            return
        ratio = (
            min(self.width() / self.image.width(), self.height() / self.image.height()) * self.zoom
        )
        width, height = self.image.width() * ratio, self.image.height() * ratio
        self.bounds = QRectF(
            (self.width() - width) / 2 + self.pan.x(),
            (self.height() - height) / 2 + self.pan.y(),
            width,
            height,
        )

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        """Zoom around the pointer or viewport center without changing source coordinates."""
        self.update_bounds()
        anchor = anchor if anchor is not None else QPointF(self.rect().center())
        old = self.zoom
        self.zoom = min(16.0, max(0.1, old * factor))
        center = QPointF(self.rect().center())
        self.pan = anchor - center - (anchor - center - self.pan) * (self.zoom / old)
        self.update_bounds()
        self.update()
        self.view_changed.emit()

    def fit(self) -> None:
        """Restore a centered complete image after zooming or panning."""
        self.zoom, self.pan = 1.0, QPointF()
        self.update_bounds()
        self.update()
        self.view_changed.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        """Zoom without scrolling the option cards or modifying any pose data."""
        self.zoom_by(1.2 ** (event.angleDelta().y() / 120), event.position())
        event.accept()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Display source pixels without stretching and confidence-coded joint overlays."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), transparency_brush(self.palette()))
        if self.image.isNull():
            painter.setPen(QColor(palette_colors(self.palette())["preview_ink"]))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Your artwork, ready for a rig\n\nChoose a video or images to get started",
            )
            return
        self.update_bounds()
        painter.drawPixmap(self.bounds, self.image, QRectF(self.image.rect()))
        if self.region:
            painter.setPen(QPen(QColor("#eeeeee"), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(
                QRectF(
                    self.bounds.left() + self.region.left() * self.bounds.width(),
                    self.bounds.top() + self.region.top() * self.bounds.height(),
                    self.region.width() * self.bounds.width(),
                    self.region.height() * self.bounds.height(),
                )
            )
        if not self.pose or not self.show_bones:
            return
        ratio = self.bounds.width() / self.image.width()

        def location(x: float, y: float) -> QPointF:
            """Map detector coordinates onto the fitted review image."""
            return QPointF(self.bounds.left() + x * ratio, self.bounds.top() + y * ratio)

        if self.show_previous and self.previous_pose:
            painter.setPen(QPen(QColor(220, 70, 70, 100), 2))
            painter.setBrush(QColor(220, 70, 70, 100))
            for _, a, b in segments(self.profile, self.previous_pose.points).values():
                if min(a[2], b[2]) >= self.threshold:
                    painter.drawLine(location(*a[:2]), location(*b[:2]))
            for x, y, score in self.previous_pose.points:
                if score >= self.threshold:
                    painter.drawEllipse(location(x, y), 3, 3)
        painter.setPen(QPen(QColor("#101010"), 5))
        for _, a, b in segments(self.profile, self.pose.points).values():
            if min(a[2], b[2]) >= self.threshold:
                painter.drawLine(location(*a[:2]), location(*b[:2]))
        painter.setPen(QPen(QColor("#ededed"), 2))
        for _, a, b in segments(self.profile, self.pose.points).values():
            if min(a[2], b[2]) >= self.threshold:
                painter.drawLine(location(*a[:2]), location(*b[:2]))
        names = HUMAN_JOINTS if self.profile == "Human" else ANIMAL_JOINTS
        for index, (x, y, score) in enumerate(self.pose.points):
            if score <= 0:
                continue
            painter.setPen(QPen(QColor("#111111"), 1.5))
            painter.setBrush(QColor("#eeeeee" if score >= self.threshold else "#c46a6a"))
            painter.drawEllipse(location(x, y), 4.5, 4.5)
            if self.show_labels:
                point = location(x, y) + QPointF(8, -8)
                metrics = painter.fontMetrics()
                label = QRectF(
                    point.x(),
                    point.y() - metrics.height(),
                    metrics.horizontalAdvance(names[index]) + 10,
                    metrics.height() + 4,
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(20, 20, 20, 210))
                painter.drawRoundedRect(label, 3, 3)
                painter.setPen(QColor("#eeeeee"))
                painter.drawText(label, Qt.AlignmentFlag.AlignCenter, names[index])

    def hit(self, point: QPointF) -> int | None:
        """Pick the nearest observed joint within a generous screen-space target."""
        if not self.pose or self.image.isNull() or not self.show_bones:
            return None
        self.update_bounds()
        ratio = self.bounds.width() / self.image.width()
        distances = [
            math.hypot(
                point.x() - self.bounds.left() - x * ratio,
                point.y() - self.bounds.top() - y * ratio,
            )
            if score > 0
            else math.inf
            for x, y, score in self.pose.points
        ]
        nearest = min(range(17), key=lambda i: distances[i])
        return nearest if distances[nearest] <= 12 else None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Begin a correction without changing any project until Create is pressed."""
        self.update_bounds()
        if event.button() == Qt.MouseButton.MiddleButton:
            self.pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.picking_key and self.bounds.contains(event.position()):
            ratio = self.image.width() / self.bounds.width()
            point = (event.position() - self.bounds.topLeft()) * ratio
            self.color_picked.emit(self.image.toImage().pixelColor(int(point.x()), int(point.y())))
            self.picking_key = False
            event.accept()
            return
        if self.drawing_region and self.bounds.contains(event.position()):
            self.region_start = event.position()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = self.hit(event.position())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Correct this sample in source coordinates while keeping the pointer in image bounds."""
        if self.pan_start is not None:
            self.pan += event.position() - self.pan_start
            self.pan_start = event.position()
            self.update_bounds()
            self.update()
            return
        if self.region_start and self.bounds.width() > 0:
            selected = (
                QRectF(self.region_start, event.position()).normalized().intersected(self.bounds)
            )
            self.region = QRectF(
                (selected.left() - self.bounds.left()) / self.bounds.width(),
                (selected.top() - self.bounds.top()) / self.bounds.height(),
                selected.width() / self.bounds.width(),
                selected.height() / self.bounds.height(),
            )
            self.update()
            return
        if self.dragging is not None and self.bounds.width() > 0:
            ratio = self.image.width() / self.bounds.width()
            x = min(
                self.image.width() - 1, max(0, (event.position().x() - self.bounds.left()) * ratio)
            )
            y = min(
                self.image.height() - 1, max(0, (event.position().y() - self.bounds.top()) * ratio)
            )
            self.joint_moved.emit(self.dragging, x, y)
        hovered = self.hit(event.position())
        names = HUMAN_JOINTS if self.profile == "Human" else ANIMAL_JOINTS
        self.setToolTip(names[hovered] if hovered is not None else "Wheel: zoom · Middle drag: pan")
        self.setCursor(
            Qt.CursorShape.CrossCursor
            if self.picking_key
            else Qt.CursorShape.SizeAllCursor
            if self.dragging is not None or hovered is not None
            else Qt.CursorShape.ArrowCursor
        )
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Finish the sample correction; the reviewed result remains unpublished."""
        self.dragging = None
        self.pan_start = None
        if self.region_start and self.region:
            self.region_changed.emit(
                (self.region.left(), self.region.top(), self.region.right(), self.region.bottom())
            )
        self.region_start, self.drawing_region = None, False
        super().mouseReleaseEvent(event)


class VideoRigDialog(CustomDialog):
    """Modern source/analyze/review/create workspace with one preview and compact option cards."""

    def __init__(self, host: "MainWindow") -> None:
        """Build neutral cards and floating preview transport without starting inference."""
        super().__init__(host, "Media to Rig")
        self.host = host
        self.model = VideoRigViewModel(host.viewmodel)
        self.current_index = -1
        self.path: Path | None = None
        self.region: tuple[float, float, float, float] | None = None
        self.frame_png = b""
        self.play_origin = (0.0, 0.0)
        self.sections: dict[str, tuple[QToolButton, QWidget]] = {}
        self.review_started = False
        self.key_color: tuple[float, float, float] | None = None
        self.resize(1120, 780)
        self.setMinimumSize(920, 620)
        self.setStyleSheet(
            "QFrame#VideoCard {background:#202020;border:1px solid #383838;border-radius:10px;}"
            "QLabel#VideoHeading {font-size:15px;font-weight:600;color:#eeeeee;}"
            "QLabel#VideoMuted {color:#aaaaaa;}"
            "QFrame#VideoTransport {background:#242424;border:1px solid #494949;"
            "border-radius:12px;}"
            "QPushButton#VideoCreate {background:#e3e3e3;color:#171717;border:0;"
            "border-radius:7px;padding:10px 18px;font-weight:600;}"
            "QPushButton#VideoCreate:hover {background:#ffffff;}"
            "QPushButton#VideoCreate:disabled {background:#333333;color:#888888;}"
            "QProgressBar#VideoProgress {border:0;background:#272727;}"
            "QProgressBar#VideoProgress::chunk {background:#d2d2d2;}"
        )
        box = QVBoxLayout(self.content)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(14)
        heading = QHBoxLayout()
        title = QLabel("Turn images and movement into editable rigs")
        title.setObjectName("VideoHeading")
        heading.addWidget(title, 1)
        self.stage = QLabel("01  SOURCE   /   02  ANALYZE   /   03  REVIEW")
        self.stage.setObjectName("VideoMuted")
        heading.addWidget(self.stage)
        box.addLayout(heading)
        split = QSplitter(Qt.Orientation.Horizontal)
        box.addWidget(split, 1)
        left = QWidget()
        layout = QVBoxLayout(left)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.preview = PosePreview(left)
        layout.addWidget(self.preview, 1)
        self.progress = QProgressBar()
        self.progress.setObjectName("VideoProgress")
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.setAccessibleName("Video conversion progress")
        layout.addWidget(self.progress)
        self.scrub = QSlider(Qt.Orientation.Horizontal)
        self.scrub.setAccessibleName("Review video pose")
        self.scrub.setEnabled(False)
        self.scrub.valueChanged.connect(self.model.request_frame)
        layout.addWidget(self.scrub)
        self.caption = QLabel("Local processing · Editable bones and keyframes · No upload")
        self.caption.setObjectName("VideoMuted")
        self.caption.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self.caption)
        split.addWidget(left)
        self.transport = QFrame(self.preview)
        self.transport.setObjectName("VideoTransport")
        controls = QHBoxLayout(self.transport)
        controls.setContentsMargins(8, 5, 8, 5)
        controls.setSpacing(6)
        self.play = self.icon_button("play_arrow", "Play or pause review", self.toggle_play)
        controls.addWidget(self.play)
        self.repeat = self.icon_button("repeat", "Loop review", lambda: None)
        self.repeat.setCheckable(True)
        self.repeat.setChecked(True)
        controls.addWidget(self.repeat)
        self.length_lock = self.icon_button(
            "lock_open", "Freeze all bone lengths while correcting poses", self.toggle_length_lock
        )
        self.length_lock.setCheckable(True)
        controls.addWidget(self.length_lock)
        self.timecode = QLabel("00:00.00")
        self.timecode.setMinimumWidth(72)
        controls.addWidget(self.timecode)
        self.overlay = self.icon_button("account_tree", "Show tracking joints", self.toggle_overlay)
        self.overlay.setCheckable(True)
        self.overlay.setChecked(True)
        controls.addWidget(self.overlay)
        self.labels = self.icon_button("label", "Show joint names", self.toggle_labels)
        self.labels.setCheckable(True)
        controls.addWidget(self.labels)
        self.previous = self.icon_button(
            "history", "Previous frame rig · Read-only red overlay", self.toggle_previous
        )
        self.previous.setCheckable(True)
        controls.addWidget(self.previous)
        self.transport.setFixedSize(334, 44)
        self.transport.raise_()
        self.view_controls = QFrame(self.preview)
        self.view_controls.setObjectName("VideoTransport")
        view_box = QHBoxLayout(self.view_controls)
        view_box.setContentsMargins(6, 4, 6, 4)
        view_box.setSpacing(3)
        view_box.addWidget(
            self.icon_button("remove", "Zoom out", lambda: self.preview.zoom_by(1 / 1.25))
        )
        self.zoom_percent = QLabel("Fit")
        self.zoom_percent.setMinimumWidth(48)
        self.zoom_percent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view_box.addWidget(self.zoom_percent)
        view_box.addWidget(self.icon_button("add", "Zoom in", lambda: self.preview.zoom_by(1.25)))
        view_box.addWidget(self.icon_button("fit_screen", "Fit preview", self.preview.fit))
        self.view_controls.setFixedSize(170, 42)
        self.preview.view_changed.connect(self.update_zoom)
        self.preview.resized.connect(self.position_transport)
        self.clock = QTimer(self)
        self.clock.setInterval(67)
        self.clock.timeout.connect(self.advance)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(390)
        sidebar = QWidget()
        cards = QVBoxLayout(sidebar)
        cards.setContentsMargins(12, 0, 0, 0)
        cards.setSpacing(12)
        scroll.setWidget(sidebar)
        split.addWidget(scroll)
        split.setSizes([730, 330])
        source = self.card(
            cards,
            "Source media",
            "Use a video, one image or an image sequence. Processing stays local.",
        )
        self.source_label = QLabel("No media selected")
        self.source_label.setWordWrap(True)
        source.addWidget(self.source_label)
        self.browse = QPushButton(host.icons.icon("video_file"), "Choose video…")
        self.browse.clicked.connect(self.choose_video)
        browse_row = QHBoxLayout()
        browse_row.addWidget(self.browse)
        self.browse_images = QPushButton(host.icons.icon("photo_library"), "Choose images…")
        self.browse_images.clicked.connect(self.choose_images)
        browse_row.addWidget(self.browse_images)
        source.addLayout(browse_row)
        area = QHBoxLayout()
        self.choose_region = QPushButton(host.icons.icon("crop_free"), "Choose subject area")
        self.choose_region.setCheckable(True)
        self.choose_region.setToolTip(
            "Draw around a missed character, then choose Human or Quadruped."
        )
        self.choose_region.toggled.connect(
            lambda value: setattr(self.preview, "drawing_region", value)
        )
        area.addWidget(self.choose_region, 1)
        clear_region = QPushButton(host.icons.icon("close"), "")
        clear_region.setToolTip("Clear subject area; use automatic detection")
        clear_region.setAccessibleName("Clear subject area")
        clear_region.clicked.connect(self.clear_region)
        area.addWidget(clear_region)
        source.addLayout(area)
        self.source_controls = []
        self.profile = QComboBox()
        self.profile.addItems(["Auto", "Human", "Quadruped"])
        self.profile.setAccessibleName("Video subject type")
        source.addWidget(self.labelled("Subject type", self.profile))
        timing = QHBoxLayout()
        self.start = self.number(0, 3480, 0, "Start time in seconds")
        self.duration = self.number(0.1, 120, 10, "Clip duration in seconds")
        self.start_field = self.labelled("Start · seconds", self.start)
        self.duration_field = self.labelled("Length · seconds", self.duration)
        timing.addWidget(self.start_field)
        timing.addWidget(self.duration_field)
        source.addLayout(timing)
        settings = QHBoxLayout()
        self.sample_fps = QSpinBox()
        self.sample_fps.setRange(1, 30)
        self.sample_fps.setValue(15)
        self.subject = QSpinBox()
        self.subject.setRange(1, 20)
        self.subject.setValue(1)
        self.subject.setToolTip("Subjects are ordered by their detected size when tracking begins.")
        self.sample_fps.setToolTip(
            "Video samples per second, or the playback frame rate of selected images."
        )
        settings.addWidget(self.labelled("Frames / second", self.sample_fps))
        settings.addWidget(self.labelled("Subject · largest first", self.subject))
        source.addLayout(settings)
        self.source_controls = [
            self.profile,
            self.start,
            self.duration,
            self.sample_fps,
            self.subject,
        ]
        self.analyze = QPushButton(host.icons.icon("auto_fix_high"), "Analyze media")
        self.analyze.clicked.connect(self.analyze_video)
        source.addWidget(self.analyze)
        motion = self.card(
            cards,
            "Refine motion",
            "Scrub the clip. Drag joints or use the fields below to correct a sample.",
        )
        fields = QHBoxLayout()
        self.confidence = self.number(0.05, 0.95, 0.35, "Minimum tracking confidence")
        self.smoothing = self.number(0, 0.9, 0.25, "Motion smoothing")
        self.confidence.setSingleStep(0.05)
        self.smoothing.setSingleStep(0.05)
        self.confidence.valueChanged.connect(self.update_overlay)
        fields.addWidget(self.labelled("Confidence", self.confidence))
        fields.addWidget(self.labelled("Smoothing", self.smoothing))
        motion.addLayout(fields)
        self.joint = QComboBox()
        self.joint.addItems(HUMAN_JOINTS)
        self.joint.setAccessibleName("Joint to correct")
        self.joint.currentIndexChanged.connect(self.joint_selected)
        motion.addWidget(self.joint)
        coordinates = QHBoxLayout()
        self.joint_x = self.number(0, 1920, 0, "Joint X")
        self.joint_y = self.number(0, 1080, 0, "Joint Y")
        coordinates.addWidget(self.labelled("X", self.joint_x))
        coordinates.addWidget(self.labelled("Y", self.joint_y))
        apply_joint = QPushButton(host.icons.icon("check"), "")
        apply_joint.setToolTip("Set this joint on the displayed sample")
        apply_joint.setAccessibleName("Apply joint correction")
        apply_joint.clicked.connect(
            lambda: self.correct_joint(
                self.joint.currentIndex(), self.joint_x.value(), self.joint_y.value()
            )
        )
        coordinates.addWidget(apply_joint, 0, Qt.AlignmentFlag.AlignBottom)
        motion.addLayout(coordinates)
        self.reference = QPushButton(
            host.icons.icon("center_focus_strong"), "Use this pose as the reference"
        )
        self.reference.clicked.connect(self.set_reference)
        motion.addWidget(self.reference)
        result = self.card(
            cards,
            "Character output",
            "Reference cutouts are editable raster artwork. "
            "Hidden parts and clothing layers need author cleanup.",
        )
        self.name = QLineEdit("Media character")
        self.name.setMaxLength(180)
        self.name.setAccessibleName("New character name")
        result.addWidget(self.name)
        self.output_mode = QComboBox()
        self.output_mode.addItems(["Rig + reference artwork", "Rig only · No artwork"])
        self.output_mode.setAccessibleName("Video conversion output")
        self.output_mode.currentIndexChanged.connect(self.refresh)
        result.addWidget(self.labelled("Create", self.output_mode))
        self.keying_options = QWidget()
        keying_box = QVBoxLayout(self.keying_options)
        keying_box.setContentsMargins(0, 0, 0, 0)
        keying_box.setSpacing(8)
        self.key_method = QComboBox()
        self.key_method.addItems(["Auto", "Chroma", "Difference"])
        keying_box.addWidget(self.labelled("Background key · Built in", self.key_method))
        colors = QHBoxLayout()
        self.key_color_button = QPushButton("Auto · Sample border color")
        self.key_color_button.clicked.connect(self.choose_key_color)
        colors.addWidget(self.key_color_button, 1)
        colors.addWidget(
            self.icon_button(
                "colorize", "Pick background color from source preview", self.pick_key_color
            )
        )
        colors.addWidget(
            self.icon_button(
                "restart_alt", "Use automatic border color", lambda: self.set_key_color(None)
            )
        )
        keying_box.addLayout(colors)
        tuning = QHBoxLayout()
        self.key_tolerance = self.number(0, 0.99, 0.1, "Key tolerance")
        self.key_softness = self.number(0, 1, 0.1, "Key edge softness")
        tuning.addWidget(self.labelled("Tolerance", self.key_tolerance))
        tuning.addWidget(self.labelled("Soft edge", self.key_softness))
        keying_box.addLayout(tuning)
        self.key_despill = self.number(0, 1, 1, "Chroma despill strength")
        keying_box.addWidget(self.labelled("Despill · Chroma screens", self.key_despill))
        advanced = QToolButton()
        advanced.setText("Matte cleanup")
        advanced.setCheckable(True)
        advanced.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        advanced.setIcon(host.icons.icon("chevron_right"))
        keying_box.addWidget(advanced)
        advanced_panel = QWidget()
        advanced_panel.setVisible(False)
        advanced_box = QVBoxLayout(advanced_panel)
        advanced_box.setContentsMargins(0, 0, 0, 0)
        self.key_filters: dict[str, QDoubleSpinBox] = {}
        controls_list = (
            ("balance", "Key balance", 0, 1, 0.5),
            ("despill_balance", "Despill balance", 0, 1, 0.5),
            ("pre_blur", "Chroma blur · px", 0, 16, 0),
            ("matte_blur", "Matte blur · px", 0, 16, 0),
            ("grow", "Grow / shrink · px", -16, 16, 0),
            ("feather", "Feather · px", -16, 16, 0),
        )
        for index in range(0, len(controls_list), 2):
            row = QHBoxLayout()
            for key, field_title, low, high, default in controls_list[index : index + 2]:
                field = self.number(low, high, default, field_title)
                if key not in ("balance", "despill_balance"):
                    field.setDecimals(0)
                self.key_filters[key] = field
                row.addWidget(self.labelled(field_title, field))
            advanced_box.addLayout(row)
        advanced.toggled.connect(advanced_panel.setVisible)
        advanced.toggled.connect(
            lambda value: advanced.setIcon(
                host.icons.icon("expand_more" if value else "chevron_right")
            )
        )
        keying_box.addWidget(advanced_panel)
        key_hint = QLabel(
            "Source transparency is preserved. Solid backgrounds key best. "
            "Matching foreground colors also become "
            "transparent; preview before creating."
        )
        key_hint.setObjectName("VideoMuted")
        key_hint.setWordWrap(True)
        keying_box.addWidget(key_hint)
        result.addWidget(self.keying_options)
        self.cutout_preview = QPushButton(
            host.icons.icon("content_cut"), "Preview reference cutout"
        )
        self.cutout_preview.clicked.connect(self.show_cutout)
        result.addWidget(self.cutout_preview)
        self.quality = QLabel("Analysis results will appear here.")
        self.quality.setWordWrap(True)
        self.quality.setObjectName("VideoMuted")
        result.addWidget(self.quality)
        models = self.card(
            cards,
            "Local models",
            "RTMLib · RTMPose · ViTPose\nInstall once; analysis then works offline.",
        )
        self.install = QPushButton(host.icons.icon("download"), "Install / repair models")
        self.install.clicked.connect(self.model.install)
        models.addWidget(self.install)
        cards.addStretch(1)
        bottom = QHBoxLayout()
        self.status = QLabel(self.model.message)
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.cancel_job = QPushButton("Cancel operation")
        self.cancel_job.clicked.connect(lambda: self.model.cancel.set())
        bottom.addWidget(self.cancel_job)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        close.setDefault(True)
        bottom.addWidget(close)
        self.create_button = QPushButton(
            host.icons.icon("add", color="#171717"), "Create character"
        )
        self.create_button.setObjectName("VideoCreate")
        self.create_button.setAutoDefault(False)
        self.create_button.clicked.connect(self.create_character)
        bottom.addWidget(self.create_button)
        box.addLayout(bottom)
        self.model.changed.connect(self.refresh)
        self.model.frame_ready.connect(self.show_frame)
        self.model.created.connect(self.created)
        self.preview.joint_moved.connect(self.correct_joint)
        self.preview.region_changed.connect(self.region_selected)
        self.preview.color_picked.connect(self.set_key_color)
        self.finished.connect(lambda _: self.cleanup())
        self.refresh()

    def icon_button(self, icon: str, tooltip: str, callback: Callable[[], None]) -> QToolButton:
        """Build a consistent, accessible Material-icon preview control."""
        button = QToolButton()
        button.setIcon(self.host.icons.icon(icon))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(32, 32)
        button.clicked.connect(callback)
        return button

    @staticmethod
    def number(low: float, high: float, value: float, name: str) -> QDoubleSpinBox:
        """Create a labelled numeric input with useful fractional precision."""
        field = QDoubleSpinBox()
        field.setRange(low, high)
        field.setDecimals(2)
        field.setValue(value)
        field.setMinimumWidth(0)
        field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        field.setAccessibleName(name)
        return field

    @staticmethod
    def labelled(title: str, field: QWidget) -> QWidget:
        """Keep field labels above compact controls instead of a long form table."""
        widget = QWidget()
        box = QVBoxLayout(widget)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(5)
        label = QLabel(title)
        label.setObjectName("VideoMuted")
        label.setBuddy(field)
        box.addWidget(label)
        box.addWidget(field)
        return widget

    def card(self, parent: QVBoxLayout, title: str, description: str) -> QVBoxLayout:
        """Create a collapsible neutral card with one shared sidebar scroll surface."""
        card = QFrame()
        card.setObjectName("VideoCard")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(8, 7, 8, 7)
        outer.setSpacing(0)
        heading = QToolButton()
        heading.setText(title)
        heading.setCheckable(True)
        heading.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        heading.setStyleSheet("QToolButton {border:0;font-size:14px;font-weight:600;padding:6px;}")
        outer.addWidget(heading)
        content = QWidget()
        outer.addWidget(content)
        box = QVBoxLayout(content)
        box.setContentsMargins(14, 13, 14, 14)
        box.setSpacing(10)
        self.sections[title] = (heading, content)

        def toggle(expanded: bool) -> None:
            """Keep the expansion indicator and full-height card contents in sync."""
            content.setVisible(expanded)
            heading.setIcon(self.host.icons.icon("expand_more" if expanded else "chevron_right"))

        heading.toggled.connect(toggle)
        expanded = (
            title == "Source media"
            or title == "Local models"
            and not all((self.model.directory / (key + ".onnx")).is_file() for key in MODELS)
        )
        heading.setChecked(expanded)
        toggle(expanded)
        label = QLabel(description)
        label.setWordWrap(True)
        label.setObjectName("VideoMuted")
        box.addWidget(label)
        parent.addWidget(card)
        return box

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Anchor preview transport at its bottom center when the workspace resizes."""
        super().resizeEvent(event)
        if hasattr(self, "transport"):
            QTimer.singleShot(0, self.position_transport)

    def position_transport(self) -> None:
        """Keep the floating transport stationary relative to the fitted preview viewport."""
        self.transport.move(
            max(0, (self.preview.width() - self.transport.width()) // 2),
            max(0, self.preview.height() - 62),
        )
        self.view_controls.move(max(8, self.preview.width() - 182), 10)

    def update_zoom(self) -> None:
        """Display pixel magnification rather than a value tied to the window's fit size."""
        self.preview.update_bounds()
        ratio = (
            self.preview.bounds.width() / self.preview.image.width()
            if not self.preview.image.isNull()
            else 0
        )
        self.zoom_percent.setText(f"{ratio:.0%}" if ratio else "Fit")

    def toggle_labels(self) -> None:
        """Toggle anatomical names without modifying selection or tracked points."""
        self.preview.show_labels = self.labels.isChecked()
        self.preview.update()

    def toggle_previous(self) -> None:
        """Show the preceding sampled pose as an unpickable translucent red reference."""
        self.preview.show_previous = self.previous.isChecked()
        self.preview.update()

    def refresh_length_lock(self) -> None:
        """Reflect one global length guard in the preview playback controls."""
        analysis = self.model.analysis
        roles = (
            frozenset(segments(analysis.profile, analysis.poses[analysis.reference].points))
            if analysis
            else frozenset()
        )
        locked = bool(roles and analysis and analysis.locked_lengths == roles)
        self.length_lock.setChecked(locked)
        self.length_lock.setIcon(self.host.icons.icon("lock" if locked else "lock_open"))
        self.length_lock.setToolTip(
            "All bone lengths frozen · Click to unlock"
            if locked
            else "Freeze all bone lengths while correcting poses"
        )

    def toggle_length_lock(self) -> None:
        """Toggle all observed bones together with one playback-area button."""
        self.set_all_length_locks(self.length_lock.isChecked())

    def set_all_length_locks(self, enabled: bool) -> None:
        """Protect or release all observed bone lengths without changing any existing frame."""
        analysis = self.model.analysis
        if analysis and not self.model.busy:
            roles = frozenset(segments(analysis.profile, analysis.poses[analysis.reference].points))
            self.model.analysis = replace(
                analysis, locked_lengths=roles if enabled else frozenset()
            )
            self.refresh_length_lock()

    def keying_settings(self) -> KeyingSettings:
        """Capture immutable controls before handing keying to the worker."""
        return KeyingSettings(
            self.key_method.currentText(),
            self.key_color,
            self.key_tolerance.value(),
            self.key_softness.value(),
            self.key_despill.value(),
            balance=self.key_filters["balance"].value(),
            despill_balance=self.key_filters["despill_balance"].value(),
            pre_blur=int(self.key_filters["pre_blur"].value()),
            matte_blur=int(self.key_filters["matte_blur"].value()),
            grow=int(self.key_filters["grow"].value()),
            feather=int(self.key_filters["feather"].value()),
        )

    def set_key_color(self, color: QColor | None) -> None:
        """Use a picked sRGB key or restore automatic perimeter sampling."""
        self.key_color = (
            (color.redF(), color.greenF(), color.blueF()) if color is not None else None
        )
        self.key_color_button.setText(
            color.name().upper() if color is not None else "Auto · Sample border color"
        )
        self.key_color_button.setStyleSheet(
            f"border-left:12px solid {color.name()};" if color is not None else ""
        )
        self.preview.picking_key = False
        self.preview.setCursor(Qt.CursorShape.ArrowCursor)

    def pick_key_color(self) -> None:
        """Sample original pixels so transparent preview RGB cannot contaminate the key."""
        if analysis := self.model.analysis:
            self.show_frame(analysis.image, analysis.reference)
        self.preview.picking_key = True
        self.preview.setCursor(Qt.CursorShape.CrossCursor)
        self.status.setText("Click the background in the source preview to choose its key color.")

    def choose_key_color(self) -> None:
        """Host Qt's color controls inside the shared custom dialog frame."""
        color = self.key_color
        if color is None and self.model.analysis:
            color = border_color(self.model.analysis.image)
        dialog = CustomDialog(self, "Background key color")
        box = QVBoxLayout(dialog.content)
        picker = QColorDialog(QColor.fromRgbF(*(color or (1.0, 1.0, 1.0))))
        picker.setWindowFlags(Qt.WindowType.Widget)
        picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        picker.setOption(QColorDialog.ColorDialogOption.NoButtons)
        box.addWidget(picker)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setAutoDefault(False)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        if dialog.exec():
            self.set_key_color(picker.currentColor())
        dialog.deleteLater()

    def choose_video(self) -> None:
        """Use the native OS picker and decode the initial source frame asynchronously."""
        path, _ = choose_open_file(
            self,
            "Media to Rig · Video",
            "",
            "Video (*.mp4 *.mov *.mkv *.avi *.webm *.m4v);;All files (*)",
        )
        if not path:
            return
        self.path = Path(path)
        self.source_label.setText(self.path.name)
        self.source_label.setToolTip(str(self.path))
        self.name.setText(self.path.stem[:180])
        self.model.analysis = None
        self.preview.pose = None
        self.preview.image = QPixmap()
        self.preview.fit()
        self.review_started = False
        self.clear_region()
        self.model.open_source(self.path)
        self.refresh()

    def choose_images(self) -> None:
        """Choose explicit images through the OS picker and order numbered filenames naturally."""
        paths = choose_open_files(
            self,
            "Media to Rig · Images",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff);;All files (*)",
        )
        if not paths:
            return
        if len(paths) > 3600:
            self.status.setText("Choose at most 3600 images.")
            return
        images = ordered_images([Path(path) for path in paths])
        self.path = images[0]
        self.source_label.setText(
            self.path.name if len(images) == 1 else f"{len(images)} images · Natural filename order"
        )
        self.source_label.setToolTip("\n".join(path.name for path in images[:20]))
        self.name.setText(self.path.stem[:180])
        self.preview.pose, self.preview.previous_pose = None, None
        self.preview.image = QPixmap()
        self.preview.fit()
        self.review_started = False
        self.clear_region()
        self.model.open_images(images)
        self.refresh()

    def analyze_video(self) -> None:
        """Capture source controls before starting the owned, cancellable analysis job."""
        if self.path:
            if self.region and self.profile.currentText() == "Auto":
                self.status.setText("Choose Human or Quadruped for the selected subject area.")
                return
            self.clock.stop()
            self.model.analyze(
                self.path,
                profile=self.profile.currentText(),
                start=self.start.value(),
                duration=self.duration.value(),
                sample_fps=self.sample_fps.value(),
                subject=self.subject.value() - 1,
                region=self.region,
            )

    def region_selected(self, region: tuple[float, float, float, float]) -> None:
        """Retain an explicit subject seed without changing inferred anatomy silently."""
        self.region = region
        self.choose_region.setChecked(False)
        self.status.setText("Subject area selected. Choose Human or Quadruped, then analyze.")

    def clear_region(self) -> None:
        """Restore detector-based acquisition without changing existing observations."""
        self.region, self.preview.region = None, None
        self.choose_region.setChecked(False)
        self.preview.update()

    def show_frame(self, png: bytes, index: int) -> None:
        """Display the decoded source and matching sample together; stale decodes are discarded."""
        self.frame_png = png
        analysis = self.model.analysis
        if not analysis:
            self.preview.image.loadFromData(png)
            self.preview.pose = None
            self.preview.previous_pose = None
            self.preview.update()
            self.update_zoom()
            return
        self.current_index = index
        self.preview.image.loadFromData(png)
        self.preview.profile = analysis.profile
        self.preview.pose = analysis.poses[index]
        self.preview.previous_pose = analysis.poses[index - 1] if index > 0 else None
        self.scrub.blockSignals(True)
        self.scrub.setRange(0, len(analysis.poses) - 1)
        self.scrub.setValue(index)
        self.scrub.blockSignals(False)
        seconds = analysis.poses[index].seconds
        self.timecode.setText(
            f"{int(seconds // 60):02}:{seconds % 60:05.2f}"
            if len(analysis.poses) > 1
            else "Still image"
        )
        self.caption.setText(
            "Drag joints to correct this frame · Pale joints: reliable · Muted red: low confidence"
        )
        names = HUMAN_JOINTS if analysis.profile == "Human" else ANIMAL_JOINTS
        self.refresh_length_lock()
        if self.joint.itemText(0) != names[0] or self.joint.itemText(3) != names[3]:
            self.joint.clear()
            self.joint.addItems(names)
        self.joint_selected()
        self.update_overlay()
        self.update_zoom()

    def joint_selected(self) -> None:
        """Expose the selected sample's coordinates, including currently missing joints."""
        if self.preview.pose and 0 <= self.joint.currentIndex() < 17:
            x, y, _ = self.preview.pose.points[self.joint.currentIndex()]
            self.joint_x.setValue(x)
            self.joint_y.setValue(y)

    def correct_joint(self, joint: int, x: float, y: float) -> None:
        """Correct one reviewed sample with full confidence while retaining the original timing."""
        analysis = self.model.analysis
        if not analysis or self.model.busy or self.current_index < 0:
            return
        poses = list(analysis.poses)
        try:
            poses[self.current_index] = correct_pose(
                analysis.profile, poses[self.current_index], joint, x, y, analysis.locked_lengths
            )
        except ProjectError as error:
            self.status.setText(str(error))
            return
        self.model.analysis = replace(analysis, poses=tuple(poses))
        self.preview.pose = poses[self.current_index]
        self.joint.setCurrentIndex(joint)
        self.joint_selected()
        self.update_overlay()

    def set_reference(self) -> None:
        """Choose rest bone proportions and reference artwork from the displayed video sample."""
        analysis = self.model.analysis
        if analysis and self.current_index >= 0:
            self.model.analysis = replace(
                analysis, reference=self.current_index, image=self.frame_png
            )
            self.model.message = (
                f"Reference set at {analysis.poses[self.current_index].seconds:.2f}s."
            )
            self.refresh()

    def update_overlay(self) -> None:
        """Apply confidence review immediately without re-running native inference."""
        self.preview.threshold = self.confidence.value()
        self.preview.update()

    def toggle_overlay(self) -> None:
        """Show or hide observed joints without changing any conversion settings."""
        self.preview.show_bones = self.overlay.isChecked()
        self.preview.update()

    def toggle_play(self) -> None:
        """Toggle bounded scrub playback; decoding never queues every overdue frame."""
        if self.clock.isActive():
            self.clock.stop()
        elif self.model.analysis and len(self.model.analysis.poses) > 1 and not self.model.busy:
            self.play_origin = (
                perf_counter(),
                self.model.analysis.poses[max(0, self.current_index)].seconds,
            )
            self.clock.start()
        self.play.setIcon(self.host.icons.icon("pause" if self.clock.isActive() else "play_arrow"))

    def advance(self) -> None:
        """Advance by source timestamps, coalescing frames when decoding falls behind."""
        analysis = self.model.analysis
        if not analysis or len(analysis.poses) < 2 or self.model.busy:
            self.clock.stop()
            return
        elapsed = perf_counter() - self.play_origin[0] + self.play_origin[1]
        duration = analysis.poses[-1].seconds + (
            analysis.poses[-1].seconds - analysis.poses[-2].seconds
        )
        if elapsed >= duration:
            if self.repeat.isChecked():
                elapsed %= duration
                self.play_origin = (perf_counter(), elapsed)
            else:
                self.toggle_play()
                return
        target = max(0, bisect_right([pose.seconds for pose in analysis.poses], elapsed) - 1)
        if target != self.current_index:
            self.model.request_frame(target)

    def show_cutout(self) -> None:
        """Preview extracted reference pixels before deciding whether to include them."""
        analysis = self.model.analysis
        if not analysis or self.model.busy:
            return
        self.clock.stop()
        settings = self.keying_settings()
        self.model.message = "Keying reference artwork…"

        def ready(png: bytes) -> None:
            """Preview the mask while keeping original pixels for subsequent reference selection."""
            self.show_frame(png, analysis.reference)
            self.frame_png = analysis.image

        self.model.run(lambda: self.model.key_reference(analysis, settings), ready)

    def create_character(self) -> None:
        """Publish the reviewed conversion through the shared application service."""
        self.clock.stop()
        self.model.create(
            self.name.text().strip() or "Video character",
            self.confidence.value(),
            self.smoothing.value(),
            self.output_mode.currentIndex() == 0,
            self.keying_settings(),
        )

    def created(self, result: object) -> None:
        """Keep the result visible and selectable without automatically changing editors."""
        self.host.statusBar().showMessage(
            "Media rig created"
            + (
                " · Editable animation is on the scene timeline"
                if self.model.output and self.model.output.get("clip_id")
                else " · Still pose ready to animate"
            ),
            7000,
        )
        self.refresh()

    def refresh(self) -> None:
        """Reflect progress and model readiness without resetting review controls."""
        busy, analysis = self.model.busy, self.model.analysis
        ready = all((self.model.directory / (key + ".onnx")).is_file() for key in MODELS)
        self.progress.setRange(0, 0 if busy and not self.model.progress else 1000)
        self.progress.setValue(round(self.model.progress * 1000))
        current_stage = 1 if busy else 2 if analysis else 0
        stages = []
        for index, label in enumerate(("01 SOURCE", "02 ANALYZE", "03 REVIEW")):
            tone = "#ededed" if index == current_stage else "#858585"
            stages.append(f'<span style="color:{tone}">{label}</span>')
        self.stage.setText("  /  ".join(stages))
        self.status.setText(self.model.error or self.model.message)
        self.browse.setEnabled(not busy)
        self.browse_images.setEnabled(not busy)
        self.start_field.setVisible(not self.model.images)
        self.duration_field.setVisible(not self.model.images)
        self.choose_region.setEnabled(not busy and not self.preview.image.isNull())
        self.analyze.setEnabled(bool(self.path) and ready and not busy)
        self.analyze.setToolTip(
            "Install local models first" if not ready else "Analyze the selected clip range"
        )
        self.install.setEnabled(not busy)
        self.cancel_job.setVisible(busy)
        self.create_button.setEnabled(bool(analysis) and not busy)
        artwork = self.output_mode.currentIndex() == 0
        self.output_mode.setEnabled(not busy)
        self.keying_options.setVisible(artwork)
        self.keying_options.setEnabled(not busy)
        self.cutout_preview.setVisible(artwork)
        self.cutout_preview.setEnabled(bool(analysis) and not busy and artwork)
        self.create_button.setText("Create character" if artwork else "Create rig only")
        self.length_lock.setEnabled(bool(analysis) and not busy)
        self.refresh_length_lock()
        self.reference.setEnabled(bool(analysis) and not busy)
        self.scrub.setEnabled(bool(analysis) and not busy)
        self.play.setEnabled(bool(analysis and len(analysis.poses) > 1) and not busy)
        self.previous.setEnabled(bool(analysis and len(analysis.poses) > 1))
        for field in self.source_controls:
            field.setEnabled(not busy)
        if analysis:
            if not self.review_started:
                self.review_started = True
                for title in ("Source media", "Local models"):
                    self.sections[title][0].setChecked(False)
                for title in ("Refine motion", "Character output"):
                    self.sections[title][0].setChecked(True)
            valid = sum(
                sum(p[2] >= self.confidence.value() for p in pose.points) >= 10
                for pose in analysis.poses
            )
            self.quality.setText(
                f"{analysis.profile} · {len(analysis.poses)} poses\n"
                f"{valid / len(analysis.poses):.0%} of samples have 10+ reliable joints.\n\n"
                + "\n".join(analysis.warnings)
            )
            if self.model.output and self.model.output.get("skipped_bones"):
                self.quality.setText(
                    self.quality.text()
                    + "\n\nOmitted unreliable bones: "
                    + ", ".join(self.model.output["skipped_bones"])
                )
        else:
            self.quality.setText("Analysis results will appear here.")
        self.position_transport()

    def cleanup(self) -> None:
        """Stop review and reject late workers without blocking window closure."""
        self.clock.stop()
        self.model.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Cancel owned workers even if the dialog was closed before ever becoming visible."""
        self.cleanup()
        super().closeEvent(event)
