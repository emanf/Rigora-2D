"""Source-format badges shared by content, project assets and creator cards."""

from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QListView,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionButton,
    QStyleOptionViewItem,
)

from rigora.presentation.themes import palette_colors, transparency_brush

FORMAT_ROLE = int(Qt.ItemDataRole.UserRole) + 24
CARD_SIZE = 128
CARD_IMAGE_SIZE = 82
CARD_GAP = 8
CARD_CELL = CARD_SIZE + CARD_GAP


def configure_card_grid(view: QListView) -> None:
    """Use fixed square cards and equal cell pitch without stretching artwork on resize."""
    view.setViewMode(QListView.ViewMode.IconMode)
    view.setProperty("cardGrid", True)
    view.setMovement(QListView.Movement.Static)
    view.setResizeMode(QListView.ResizeMode.Adjust)
    view.setUniformItemSizes(True)
    view.setWordWrap(True)
    view.setSpacing(0)
    view.setGridSize(QSize(CARD_CELL, CARD_CELL))
    view.setIconSize(QSize(CARD_IMAGE_SIZE, CARD_IMAGE_SIZE))
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setItemDelegate(AssetCardDelegate(view))


def label_format(item: QListWidgetItem, label: str) -> None:
    """Attach cheap display metadata without decoding an image or changing drag identities."""
    item.setData(FORMAT_ROLE, label)
    item.setData(Qt.ItemDataRole.AccessibleDescriptionRole, f"{label} source asset")


class AssetCardDelegate(QStyledItemDelegate):
    """Paint square visual cards with real source artwork and independent include controls."""

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """Reserve identical bounds regardless of thumbnail aspect ratio or caption length."""
        return QSize(CARD_SIZE, CARD_SIZE)

    @staticmethod
    def image_rect(rect: QRect) -> QRect:
        """Return the fixed image well shared by every square card."""
        return QRect(
            rect.left() + (CARD_SIZE - CARD_IMAGE_SIZE) // 2,
            rect.top() + 8,
            CARD_IMAGE_SIZE,
            CARD_IMAGE_SIZE,
        )

    @staticmethod
    def check_rect(rect: QRect) -> QRect:
        """Keep the inclusion target large and separate from the preview selection area."""
        return QRect(rect.right() - 28, rect.top() + 7, 22, 22)

    def editorEvent(
        self,
        event: QEvent,
        model: QAbstractItemModel,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> bool:
        """Toggle checks only at the painted target or with the standard Space key."""
        if (
            not index.flags() & Qt.ItemFlag.ItemIsUserCheckable
            or not index.flags() & Qt.ItemFlag.ItemIsEnabled
        ):
            return False
        if isinstance(event, QMouseEvent):
            if event.button() != Qt.MouseButton.LeftButton or not self.check_rect(
                option.rect
            ).contains(event.position().toPoint()):
                return False
            if event.type() != QEvent.Type.MouseButtonRelease:
                return True
        elif isinstance(event, QKeyEvent):
            if event.type() != QEvent.Type.KeyPress or event.key() not in (
                Qt.Key.Key_Space,
                Qt.Key.Key_Select,
            ):
                return False
        else:
            return False
        checked = index.data(Qt.ItemDataRole.CheckStateRole) in (Qt.CheckState.Checked, 2)
        return model.setData(index, 0 if checked else 2, Qt.ItemDataRole.CheckStateRole)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Draw a neutral square well, source preview and two-line caption."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRect(option.rect.topLeft(), QSize(CARD_SIZE, CARD_SIZE))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        colors = palette_colors(option.palette)
        painter.setPen(
            QColor(colors["text"] if selected else colors["muted"] if hovered else colors["border"])
        )
        painter.setBrush(
            QColor(
                colors["selected"] if selected else colors["hover"] if hovered else colors["raised"]
            )
        )
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
        well = self.image_rect(rect)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(transparency_brush(option.palette, 8))
        painter.drawRoundedRect(QRectF(well), 4, 4)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(well), 4, 4)
        painter.setClipPath(clip)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(painter, well.adjusted(3, 3, -3, -3))
        painter.setClipping(False)
        painter.setPen(QColor(colors["text"]))
        painter.setFont(option.font)
        text = option.fontMetrics.elidedText(
            str(index.data(Qt.ItemDataRole.DisplayRole) or ""),
            Qt.TextElideMode.ElideRight,
            max(1, (rect.width() - 12) * 2),
        )
        painter.drawText(
            QRect(rect.left() + 6, well.bottom() + 6, rect.width() - 12, 30),
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            text,
        )
        state = index.data(Qt.ItemDataRole.CheckStateRole)
        if state is not None:
            check = QStyleOptionButton()
            check.rect = self.check_rect(option.rect)
            check.state = QStyle.StateFlag.State_Enabled | (
                QStyle.StateFlag.State_On
                if state == Qt.CheckState.Checked or state == 2
                else QStyle.StateFlag.State_Off
            )
            style = option.widget.style() if option.widget else QApplication.style()
            style.drawPrimitive(
                QStyle.PrimitiveElement.PE_IndicatorCheckBox, check, painter, option.widget
            )
        painter.restore()
        self.paint_badge(painter, option, index)

    def paint_badge(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
        *,
        compact: bool = False,
    ) -> None:
        """Overlay a small format label; compact list badges use subdued translucent ink."""
        label = index.data(FORMAT_ROLE)
        if not isinstance(label, str) or not label:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = option.font
        font.setPixelSize(8 if compact else 10)
        font.setBold(not compact)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(label[:12]) + (6 if compact else 10)
        rect = QRectF(option.rect.left() + 4, option.rect.top() + 3, width, 12 if compact else 17)
        colors = palette_colors(option.palette)
        border, surface, text = (QColor(colors[key]) for key in ("border", "panel", "text"))
        border.setAlpha(110 if compact else 255)
        surface.setAlpha(175 if compact else 255)
        text.setAlpha(180 if compact else 255)
        painter.setPen(border)
        painter.setBrush(surface)
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(text)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label[:12])
        painter.restore()


class ProjectAssetDelegate(AssetCardDelegate):
    """Compact horizontal source cards with square checkerboard thumbnail wells."""

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        """Use a single consistent row height without constraining the source-name column."""
        return QSize(100, 44)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        """Keep native focus/selection and draw only visible thumbnails at bounded sizes."""
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        icon, text = QIcon(styled.icon), styled.text
        styled.icon, styled.text = QIcon(), ""
        style = styled.widget.style() if styled.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        painter.save()
        thumb = QRect(option.rect.left() + 5, option.rect.center().y() - 18, 36, 36)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(thumb), 3, 3)
        painter.setClipPath(clip)
        painter.fillRect(thumb, transparency_brush(option.palette, 6))
        icon.paint(painter, thumb.adjusted(2, 2, -2, -2))
        painter.restore()
        painter.save()
        painter.setFont(option.font)
        color = (
            QPalette.ColorRole.HighlightedText
            if option.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        )
        painter.setPen(option.palette.color(color))
        text_rect = option.rect.adjusted(49, 0, -7, 0)
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            option.fontMetrics.elidedText(
                text, Qt.TextElideMode.ElideRight, max(0, text_rect.width())
            ),
        )
        painter.restore()
        self.paint_badge(painter, option, index, compact=True)
