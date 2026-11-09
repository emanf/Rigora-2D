"""Camera controls and live output preview backed by the shared scene services."""

from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.cameras import CameraService
from rigora.application_services.rendering import camera_background_svg
from rigora.domain.project import ProjectError
from rigora.engine.camera_actions import lens_svg
from rigora.engine.cameras import active_camera, camera_size, camera_view
from rigora.presentation.menu_labels import menu_text
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.file_dialogs import choose_open_file
from rigora.presentation.widgets.viewport import Viewport
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class CameraSettingsDialog(CustomDialog):
    """Edit frame and background settings without writing on Cancel or importing eagerly."""

    def __init__(self, workspace: "CameraWorkspace", key: str) -> None:
        """Capture document/scene identity so an open dialog cannot edit a different scene."""
        super().__init__(workspace.window, "Camera settings")
        self.workspace, self.key = workspace, key
        self.document = workspace.window.viewmodel.documents
        self.scene_id = self.document.scene.id
        camera = CameraService(self.document).camera(key)
        self.pending_image: Path | None = None
        self.resize(460, 510)
        box = QVBoxLayout(self.content)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        box.addLayout(form)
        self.name = QLineEdit(camera.name)
        self.name.setAccessibleName("Camera name")
        form.addRow("Name", self.name)
        self.enabled = QCheckBox("Available for camera cuts")
        self.enabled.setChecked(camera.enabled)
        form.addRow("Enabled", self.enabled)
        self.match = QCheckBox("Use scene resolution")
        self.match.setChecked(camera.match_scene)
        form.addRow("Frame", self.match)
        self.frame_width = numeric(self, "Camera frame width", minimum=1, maximum=16384)
        self.frame_height = numeric(self, "Camera frame height", minimum=1, maximum=16384)
        self.frame_width.setDecimals(0)
        self.frame_height.setDecimals(0)
        width, height = camera_size(camera, self.document.scene.settings)
        self.frame_width.setValue(width)
        self.frame_height.setValue(height)
        form.addRow("Width", self.frame_width)
        form.addRow("Height", self.frame_height)
        self.match.toggled.connect(self.match_changed)
        self.frame_width.setEnabled(not camera.match_scene)
        self.frame_height.setEnabled(not camera.match_scene)
        self.background = QComboBox()
        for label, value in (
            ("Transparent", "transparent"),
            ("Solid color", "color"),
            ("Image", "image"),
        ):
            self.background.addItem(label, value)
        self.background.setCurrentIndex(self.background.findData(camera.background_mode))
        form.addRow("Background", self.background)
        color_row = QHBoxLayout()
        self.color = QLineEdit(camera.background_color)
        self.color.setAccessibleName("Camera background color in hexadecimal")
        color_row.addWidget(self.color)
        pick = QPushButton("Choose…")
        pick.clicked.connect(self.pick_color)
        color_row.addWidget(pick)
        form.addRow("Color", color_row)
        self.image = QComboBox()
        self.image.addItem("No image", None)
        assert self.document.project is not None
        for asset in self.document.project.assets:
            if asset.kind in ("raster", "vector"):
                self.image.addItem(asset.name, asset.id)
        self.image.setCurrentIndex(max(0, self.image.findData(camera.asset_id)))
        image_row = QHBoxLayout()
        image_row.addWidget(self.image, 1)
        imported = QPushButton("Import…")
        imported.clicked.connect(self.import_image)
        image_row.addWidget(imported)
        form.addRow("Image", image_row)
        self.fit = QComboBox()
        for label, value in (
            ("Cover frame", "cover"),
            ("Fit inside frame", "contain"),
            ("Stretch to frame", "stretch"),
        ):
            self.fit.addItem(label, value)
        self.fit.setCurrentIndex(self.fit.findData(camera.background_fit))
        form.addRow("Image fit", self.fit)
        self.opacity = numeric(self, "Camera background opacity", minimum=0, maximum=100)
        self.opacity.setValue(camera.background_opacity * 100)
        self.opacity.setSuffix(" %")
        form.addRow("Background opacity", self.opacity)
        help_text = QLabel(
            "Select the camera frame to move, rotate or scale it. "
            "Turn on Auto key to animate. Camera cuts are stepped keys in the timeline."
        )
        help_text.setWordWrap(True)
        box.addWidget(help_text)
        self.error = QLabel()
        self.error.setWordWrap(True)
        box.addWidget(self.error)
        box.addStretch()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply
        )
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        box.addWidget(buttons)
        self.background.currentIndexChanged.connect(self.mode_changed)
        self.mode_changed()

    def match_changed(self, checked: bool) -> None:
        """Keep custom frame dimensions editable only when scene matching is disabled."""
        self.frame_width.setEnabled(not checked)
        self.frame_height.setEnabled(not checked)

    def mode_changed(self) -> None:
        """Show only background controls meaningful for the selected render mode."""
        mode = self.background.currentData()
        self.color.setEnabled(mode != "transparent")
        self.image.setEnabled(mode == "image")
        self.fit.setEnabled(mode == "image")
        self.opacity.setEnabled(mode != "transparent")

    def pick_color(self) -> None:
        """Embed Qt's color chooser in the shared neutral custom window frame."""
        dialog = CustomDialog(self, "Camera background color")
        box = QVBoxLayout(dialog.content)
        raw = self.color.text()
        color = QColor(raw[:7])
        if len(raw) == 9:
            with suppress(ValueError):
                color.setAlpha(int(raw[7:9], 16))
        picker = QColorDialog(color)
        picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        picker.setOption(QColorDialog.ColorDialogOption.NoButtons)
        picker.setOption(QColorDialog.ColorDialogOption.ShowAlphaChannel)
        picker.setWindowFlags(Qt.WindowType.Widget)
        box.addWidget(picker)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        box.addWidget(buttons)
        if dialog.exec():
            chosen = picker.currentColor()
            self.color.setText(chosen.name() + f"{chosen.alpha():02x}")

    def import_image(self) -> None:
        """Use the native file picker and defer the packaged import until Apply."""
        path, _ = choose_open_file(
            self,
            "Camera background image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.svg *.bmp *.gif)",
        )
        if path:
            self.pending_image = Path(path)
            self.image.addItem(self.pending_image.name, "pending")
            self.image.setCurrentIndex(self.image.count() - 1)
            self.background.setCurrentIndex(self.background.findData("image"))

    def apply(self) -> None:
        """Validate and commit the image and camera together as a single undoable action."""
        try:
            if (
                self.workspace.window.viewmodel.documents is not self.document
                or self.document.scene.id != self.scene_id
            ):
                raise ProjectError("Return to the original scene to apply these camera settings.")
            service = CameraService(self.document)
            asset = self.image.currentData()
            with self.document.command_group("Edit camera settings"):
                if asset == "pending" and self.pending_image:
                    asset = service.register_image_bytes(
                        self.pending_image.name, self.document._read_asset_file(self.pending_image)
                    )
                service.update(
                    self.key,
                    name=self.name.text().strip(),
                    enabled=self.enabled.isChecked(),
                    width=self.frame_width.value(),
                    height=self.frame_height.value(),
                    match_scene=self.match.isChecked(),
                    background_mode=self.background.currentData(),
                    background_color=self.color.text().strip(),
                    asset_id=asset,
                    background_fit=self.fit.currentData(),
                    background_opacity=self.opacity.value() / 100,
                )
            self.workspace.window.viewmodel.changed.emit()
            self.accept()
        except (ProjectError, OSError) as error:
            self.error.setText(str(error))


class CameraPreview(CustomDialog):
    """Read-only live camera output sharing original vector artwork with the scene viewport."""

    def __init__(self, window: "MainWindow") -> None:
        """Create a lightweight second renderer; no export or simulation runs per paint."""
        super().__init__(window, "Camera preview")
        self.resize(800, 510)
        box = QVBoxLayout(self.content)
        self.caption = QLabel()
        box.addWidget(self.caption)
        self.viewport = Viewport(self, icons=window.icons)
        self.viewport.camera_frame_only = True
        self.viewport.show_cameras = False
        self.viewport.grid_visible = False
        self.viewport.show_bones = False
        self.viewport.node_labels = False
        self.viewport.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.viewport.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        box.addWidget(self.viewport, 1)
        self.setToolTip("Live output · uses the active camera and timeline cuts")

    def resizeEvent(self, event: object) -> None:
        """Keep the complete camera frame visible when resizing the preview window."""
        super().resizeEvent(event)  # type: ignore[arg-type]
        self.viewport.fit_canvas()


class CameraWorkspace(QObject):
    """Route scene camera actions and refresh output without adding a second authoring model."""

    def __init__(self, window: "MainWindow") -> None:
        """Attach camera actions and reuse pose notifications for animated backgrounds/cuts."""
        super().__init__(window)
        self.window = window
        self.preview: CameraPreview | None = None
        self.dialogs: list[CameraSettingsDialog] = []
        self._background_key: tuple[object, ...] | None = None
        self._background: tuple[str, QSvgRenderer] | None = None
        self._active_signature: tuple[str, str | None] | None = None
        self.popup = QMenu(window.camera_button)
        self.popup.aboutToShow.connect(self.populate)
        window.camera_button.setMenu(self.popup)
        window.camera_button.setPopupMode(window.camera_button.ToolButtonPopupMode.InstantPopup)
        window.viewport.pose_changed.connect(self.refresh)

    def populate(self) -> None:
        """Refresh menu state just before opening, preserving scene ownership."""
        self.popup.clear()
        self.menu(self.popup)

    def selected(self) -> str | None:
        """Prefer an explicitly selected camera, otherwise target the current output camera."""
        doc = self.window.viewmodel.documents
        if not doc.project:
            return None
        cameras = {c.id for c in doc.scene.cameras}
        return next((k for k in self.window.viewmodel.scene.selected if k in cameras), None) or (
            current.id if (current := CameraService(doc).current()) else None
        )

    def menu(self, menu: QMenu) -> None:
        """Expose creation, transform keys, defaults and keyed camera switching consistently."""
        doc = self.window.viewmodel.documents
        if not doc.project or self.window.object_edit.active:
            return
        menu.addAction(self.window.icons.icon("add"), "Add camera", self.add)
        menu.addAction(self.window.icons.icon("videocam"), "Camera preview", self.show_preview)
        key = self.selected()
        if key:
            menu.addAction("Camera settings…", lambda: self.settings(key))
            menu.addAction("Duplicate camera", lambda: self.run(lambda s: s.duplicate(key)))
            menu.addAction("Set as default camera", lambda: self.run(lambda s: s.activate(key)))
            menu.addAction("Key camera transform", lambda: self.key_transform(key))
        cuts = menu.addMenu("Switch camera at playhead")
        frame = doc.animation.pose.frame
        current = CameraService(doc).current()
        for camera in doc.scene.cameras:
            action = cuts.addAction(
                menu_text(camera.name),
                partial(self.cut, camera.id, frame),
            )
            action.setCheckable(True)
            action.setChecked(current is not None and current.id == camera.id)
            action.setEnabled(camera.enabled)
        menu.addSeparator()

    def cut(self, key: str, frame: float) -> None:
        """Record a menu-selected exclusive cut through the shared application service."""
        self.run(lambda service: service.activate(key, frame=frame))

    def run(self, operation: Callable[[CameraService], object]) -> None:
        """Publish camera commands through the ordinary scene view model and history."""
        self.window.viewmodel.scene.run(lambda source: operation(CameraService(source.document)))

    def add(self) -> None:
        """Create and select a camera without stealing focus into Object Editor."""
        result: list[str] = []
        self.run(lambda s: result.append(s.add()))
        if result:
            self.window.scene_workspace.select_entries((result[0],))

    def settings(self, key: str) -> None:
        """Open scene-bound nonmodal settings using the shared custom title bar."""
        dialog = CameraSettingsDialog(self, key)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.dialogs.append(dialog)
        dialog.finished.connect(lambda: self.dialogs.remove(dialog))
        dialog.show()

    def key_transform(self, key: str) -> None:
        """Capture one combined camera Transform row at the displayed playhead."""
        self.run(
            lambda s: AnimationEditingService(s.document).add_channels(
                (
                    (key, "transform." + path)
                    for path in ("x", "y", "rotation", "scale_x", "scale_y")
                ),
                frame=s.document.animation.pose.frame,
            )
        )

    def show_preview(self) -> None:
        """Show one reusable live output window and refresh it from the current pose."""
        if self.preview is None:
            self.preview = CameraPreview(self.window)
        self.preview.show()
        self.refresh()

    def refresh(self) -> None:
        """Update camera backgrounds only when settings change; project live poses cheaply."""
        doc, viewport = self.window.viewmodel.documents, self.window.viewport
        pose = viewport.source_pose
        if not doc.project or pose is None:
            viewport.camera_backdrop = None
            viewport.camera_lens = None
            if self.preview:
                self.preview.hide()
            return
        camera = active_camera(pose)
        signature = (doc.context_key, camera.id if camera else None)
        if signature != self._active_signature:
            self._active_signature = signature
            for entry in pose.cameras:
                item = self.window.scene_workspace.items.get(entry.id)
                if item:
                    item.setIcon(
                        0,
                        self.window.icons.icon(
                            "videocam" if camera and camera.id == entry.id else "videocam_off"
                        ),
                    )
        size = (
            camera_size(camera, doc.scene.settings)
            if camera
            else (doc.scene.settings.width, doc.scene.settings.height)
        )
        key = (
            (
                doc.session_id,
                camera.id,
                camera.background_mode,
                camera.background_color,
                camera.asset_id,
                camera.background_fit,
                camera.background_opacity,
                size,
            )
            if camera
            else None
        )
        if key != self._background_key:
            self._background_key, self._background = key, None
            if camera and camera.background_mode != "transparent":
                try:
                    svg = (
                        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '
                        + f'{size[0]:g} {size[1]:g}">'
                        + camera_background_svg(doc, camera, *size)
                        + "</svg>"
                    )
                    self._background = (camera.id, QSvgRenderer(QByteArray(svg.encode())))
                except ProjectError as error:
                    self.window.statusBar().showMessage(str(error), 5000)
        viewport.camera_backdrop = self._background if not self.window.object_edit.active else None
        overlay = (
            lens_svg(
                dict(camera.extra.get("lens_effects", {})),
                pose.frame / doc.scene.settings.fps,
                size[0],
                size[1],
                speeds=dict(camera.extra.get("lens_speeds", {})),
            )
            if camera
            else ""
        )
        lens = None
        if overlay and camera:
            svg = (
                f'<svg xmlns="http://www.w3.org/2000/svg" '
                f'viewBox="0 0 {size[0]:g} {size[1]:g}">{overlay}</svg>'
            )
            lens = camera.id, QSvgRenderer(QByteArray(svg.encode()))
        viewport.camera_lens = lens if not self.window.object_edit.active else None
        if self.preview and self.preview.isVisible():
            preview = self.preview.viewport
            preview.theme = viewport.theme
            preview.has_project = True
            preview.settings = replace(doc.scene.settings, width=int(size[0]), height=int(size[1]))
            preview.artwork = viewport.artwork
            preview.camera_backdrop = self._background
            preview.camera_lens = lens
            preview.scene_hint = ""
            try:
                preview.set_pose(camera_view(pose, camera))
                preview.fit_canvas()
                self.preview.caption.setText(
                    f"{camera.name if camera else 'Scene'} · {int(size[0])} × {int(size[1])}"
                    f" · Frame {pose.frame:g}"
                )
            except ProjectError as error:
                self.preview.caption.setText(str(error))
