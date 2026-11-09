"""Vector face thumbnails and an isolated, evaluated portrait for the facial workspace."""

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBitmap, QColor, QIcon, QImage, QPainter, QPaintEvent, QPixmap, QRegion
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import EXPRESSIONS
from rigora.domain.geometry import Matrix, inverse, transform_point
from rigora.domain.mesh_geometry import barycentric
from rigora.domain.project import ProjectError
from rigora.engine.state import MeshPose, ScenePose
from rigora.presentation.artwork import ArtworkCache, decode_artwork, draw_mesh
from rigora.presentation.themes import palette_colors, transparency_brush


def face_icon(expression: str = "Neutral", mouth: str = "") -> QIcon:
    """Compose thumbnails from the same replaceable vectors used by the facial rig."""
    angle, default = EXPRESSIONS[expression]
    pixmap = QPixmap(128, 112)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.fillRect(pixmap.rect(), transparency_brush(QApplication.palette(), 8))
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#686868"))
    painter.drawEllipse(QRectF(19, 4, 90, 104))
    for name, rect, rotation in (
        ("eye", QRectF(34, 37, 22, 16), 0),
        ("eye", QRectF(72, 37, 22, 16), 0),
        ("pupil", QRectF(34, 37, 22, 16), 0),
        ("pupil", QRectF(72, 37, 22, 16), 0),
        ("brow", QRectF(32, 24, 26, 20), angle),
        ("brow", QRectF(70, 24, 26, 20), -angle),
        (mouth or default, QRectF(44, 68, 40, 28), 0),
    ):
        from rigora.infrastructure.illustration import face_component

        renderer = QSvgRenderer(QByteArray(face_component(name)))
        painter.save()
        painter.translate(rect.center())
        painter.rotate(rotation)
        renderer.render(
            painter, QRectF(-rect.width() / 2, -rect.height() / 2, rect.width(), rect.height())
        )
        painter.restore()
    painter.end()
    return QIcon(pixmap)


class FacePreview(QWidget):
    """Paint the selected face's actual meshes without sharing viewport interaction state.

    Bounds include hidden speech variants so mouth switching cannot shift the portrait.
    Creator artwork is cropped to its head-sized mouth canvas; unrelated scene art is excluded.
    """

    def __init__(self) -> None:
        """Own a bounded artwork cache and an immutable pose supplied by the dialog."""
        super().__init__()
        self.setMinimumSize(300, 180)
        self.setAccessibleName("Live face preview")
        self.document: DocumentService | None = None
        self.pose: ScenePose | None = None
        self.root = ""
        self.cache = ArtworkCache()
        self.bounds = QRectF()
        self.owners: set[str] = set()
        self.caption = "Example face · choose a face or create one to start"
        self.backing = True
        self.frame_identity: tuple[str, str] | None = None
        self.to_portrait: Matrix = (1, 0, 0, 1, 0, 0)
        self.error = ""

    def sizeHint(self) -> QSize:
        """Favor a large portrait while leaving room for the audio lane below it."""
        return QSize(520, 440)

    def display(
        self, document: DocumentService, pose: ScenePose, root: str, *, example: bool = False
    ) -> None:
        """Resolve a face subtree and fixed portrait bounds from evaluated world geometry."""
        if document is not self.document:
            self.cache.clear()
        self.document, self.pose, self.root = document, pose, root
        try:
            self.to_portrait = (
                inverse(pose.nodes[root].world_matrix) if root in pose.nodes else (1, 0, 0, 1, 0, 0)
            )
        except ProjectError:
            self.to_portrait = (1, 0, 0, 1, 0, 0)
        group = next((g for g in document.scene.groups if g.id == root), None)
        descriptor = group.extra.get("face", {}) if group else {}
        self.backing = descriptor.get("kind") != "character-mouth"
        self.caption = (
            "Example face · preview only" if example else f"{group.name if group else 'Face'}"
        )
        self.owners = {root}
        for _ in range(len(pose.nodes)):
            children = {n.id for n in pose.nodes.values() if n.parent_id in self.owners}
            if children <= self.owners:
                break
            self.owners.update(children)
        anchors = set(descriptor.get("mouths", {}).values())
        for _ in range(len(pose.nodes)):
            children = {n.id for n in pose.nodes.values() if n.parent_id in anchors}
            if children <= anchors:
                break
            anchors.update(children)
        if self.backing:
            anchors.update(descriptor.get("eyes", ()))
            anchors.update(descriptor.get("brows", ()))
        points = [
            transform_point(
                self.to_portrait, *transform_point(pose.nodes[m.object_id or ""].world_matrix, *p)
            )
            for m in pose.meshes.values()
            if m.object_id in anchors
            for p in m.positions
        ]
        identity = (document.scene.id, root)
        if points and identity != self.frame_identity:
            if not self.backing:
                head_points = [
                    point
                    for mesh in pose.meshes.values()
                    if mesh.object_id in self.owners
                    and pose.nodes[mesh.object_id or ""].visible
                    and pose.nodes[mesh.object_id or ""].name.split(" · ")[0] in ("Face", "Hair")
                    for point in self.painted_points(mesh, pose)
                ]
                points = head_points or points
            xs, ys = zip(*points, strict=True)
            self.bounds = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
            margin = max(self.bounds.width(), self.bounds.height()) * (
                0.3 if self.backing else 0.08
            )
            self.bounds.adjust(-margin, -margin, margin, margin)
            self.frame_identity = identity
        elif not points:
            self.bounds = QRectF()
            self.frame_identity = None
        self.update()

    def artwork(self, asset_id: str) -> QImage | QSvgRenderer | None:
        """Load a head asset once and retain original SVG geometry for native vector painting."""
        if self.document is None:
            return None
        if asset_id not in self.cache.originals:
            try:
                data = self.document.read_asset(asset_id)
                self.cache.put(asset_id, decode_artwork(data, 512), data)
            except (ProjectError, OSError, ValueError) as error:
                self.error = str(error)
                return None
        return self.cache.styled(asset_id, {})

    def painted_points(self, mesh: MeshPose, pose: ScenePose) -> list[tuple[float, float]]:
        """Map visible head bounds through UV triangles, excluding empty sprite canvas margins."""
        image = self.artwork(mesh.asset_id or "")
        if image is None:
            return []
        if isinstance(image, QSvgRenderer):
            box, bounds = image.viewBoxF(), image.boundsOnElement("")
        else:
            box = QRectF(image.rect())
            bounds = QRectF(QRegion(QBitmap.fromImage(image.createAlphaMask())).boundingRect())
        if box.isEmpty() or bounds.isEmpty():
            return []
        points = []
        for corner in (
            bounds.topLeft(),
            bounds.topRight(),
            bounds.bottomLeft(),
            bounds.bottomRight(),
        ):
            uv = (
                max(0, min(1, (corner.x() - box.left()) / box.width())),
                max(0, min(1, (corner.y() - box.top()) / box.height())),
            )
            for face in mesh.triangles:
                try:
                    weights = barycentric(uv, *(mesh.uv[i] for i in face))
                except ProjectError:
                    continue
                if min(weights) < -1e-6:
                    continue
                x = sum(w * mesh.positions[i][0] for w, i in zip(weights, face, strict=True))
                y = sum(w * mesh.positions[i][1] for w, i in zip(weights, face, strict=True))
                points.append(
                    transform_point(
                        self.to_portrait,
                        *transform_point(pose.nodes[mesh.object_id or ""].world_matrix, x, y),
                    )
                )
                break
        return points

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render native vectors through the same deformation painter as the scene preview."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), transparency_brush(self.palette()))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor(palette_colors(self.palette())["preview_ink"]))
        painter.drawText(
            self.rect().adjusted(18, 12, -18, -12),
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
            self.caption,
        )
        if not self.pose or not self.document or self.bounds.isEmpty():
            return
        area = QRectF(self.rect()).adjusted(28, 46, -28, -26)
        scale = min(area.width() / self.bounds.width(), area.height() / self.bounds.height())
        offset = area.center() - self.bounds.center() * scale
        painter.setClipRect(area)

        def screen(point: tuple[float, float]) -> QPointF:
            """Map evaluated world geometry into the portrait's fixed fit rectangle."""
            return QPointF(*transform_point(self.to_portrait, *point)) * scale + offset

        if self.backing:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#686868"))
            painter.drawEllipse(
                QRectF(
                    QPointF(self.bounds.left(), self.bounds.top()) * scale + offset,
                    QPointF(self.bounds.right(), self.bounds.bottom()) * scale + offset,
                )
            )
        ordered = {key: i for i, key in enumerate(self.pose.render_order)}
        for mesh in sorted(
            self.pose.meshes.values(), key=lambda m: ordered.get(m.object_id or "", 0)
        ):
            node = self.pose.nodes.get(mesh.object_id or "")
            if not node or node.id not in self.owners or not node.visible or not mesh.asset_id:
                continue
            points = tuple(screen(transform_point(node.world_matrix, *p)) for p in mesh.positions)
            if not points:
                continue
            xs, ys = [p.x() for p in points], [p.y() for p in points]
            bounds = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
            if not bounds.intersects(area):
                continue
            if self.artwork(mesh.asset_id) is None:
                continue
            image = self.cache.styled(mesh.asset_id, mesh.appearance)
            if image is not None:
                painter.setOpacity(node.opacity)
                draw_mesh(painter, mesh, points, image)
        painter.setClipping(False)
        painter.setOpacity(1)
        if self.error:
            painter.setPen(QColor(palette_colors(self.palette())["preview_ink"]))
            painter.drawText(
                self.rect().adjusted(18, 0, -18, -6),
                Qt.AlignmentFlag.AlignBottom | Qt.TextFlag.TextWordWrap,
                self.error,
            )
        painter.end()
