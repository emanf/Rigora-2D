"""Scene organization views emitting validated commands rather than moving model rows directly."""

import json
from collections.abc import Sequence

from PySide6.QtCore import (
    QMimeData,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QSize,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QDrag,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from rigora.presentation.widgets.asset_cards import configure_card_grid

ASSET_MIME = "application/x-rigora-project-asset"


class NameDelegate(QStyledItemDelegate):
    """Keep inline rename fields readable inside generously sized scene rows."""

    def createEditor(
        self,
        parent: QWidget,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QWidget:
        """Use the ordinary line editor with compact padding instead of clipping its text."""
        editor = super().createEditor(parent, option, index)
        editor.setStyleSheet("padding: 1px 4px; border-radius: 0; min-height: 22px;")
        return editor


class StateIconDelegate(QStyledItemDelegate):
    """Keep visibility/lock glyphs smaller than thumbnails without shrinking their click targets."""

    def initStyleOption(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        """Apply a compact decoration size only to the state columns."""
        super().initStyleOption(option, index)
        option.decorationSize = QSize(12, 12)


class SceneTree(QTreeWidget):
    """Drag artwork and folders using stable IDs; the service owns reparenting and undo."""

    entries_moved = Signal(object, object, object)
    source_dropped = Signal(str, str, object, object)
    source_hovered = Signal(str, str)
    source_left = Signal()
    files_dropped = Signal(object, object, object)

    def __init__(self) -> None:
        """Anchor state columns to the right and reserve the remaining width for names."""
        super().__init__()
        self.session = ""
        self.setColumnCount(3)
        self.setHeaderLabels(["Scene · front to back", "View", "Lock"])
        self.setHeaderHidden(True)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(24)
        for column in (1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.setColumnWidth(column, 26)
            self.setItemDelegateForColumn(column, StateIconDelegate(self))
        self.setIconSize(QSize(20, 20))
        self.setIndentation(18)
        self.setItemDelegateForColumn(0, NameDelegate(self))
        self.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setRootIsDecorated(True)
        self.setAutoExpandDelay(500)
        self.setStyleSheet("QTreeWidget::item { min-height: 24px; padding: 1px 3px; }")

    def drawBranches(
        self, painter: QPainter, rect: QRect, index: QModelIndex | QPersistentModelIndex
    ) -> None:
        """Add continuous hierarchy guides while retaining Qt's normal disclosure arrows."""
        painter.save()
        color = self.palette().color(QPalette.ColorRole.Mid)
        painter.setPen(QPen(color, 1))
        step = self.indentation()
        x = rect.right() - step // 2
        node = index
        model = self.model()
        if model is not None:
            sibling = node.row() + 1 < model.rowCount(node.parent())
            painter.drawLine(x, rect.top(), x, rect.bottom() if sibling else rect.center().y())
            painter.drawLine(x, rect.center().y(), rect.right(), rect.center().y())
            node = node.parent()
            while node.isValid() and node != self.rootIndex():
                x -= step
                if node.row() + 1 < model.rowCount(node.parent()):
                    painter.drawLine(x, rect.top(), x, rect.bottom())
                node = node.parent()
        painter.restore()
        super().drawBranches(painter, rect, index)

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        """Move via application commands; never let Qt remove freshly rebuilt source rows."""
        items = self.selectedItems()
        keys = [
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in items
            if item.data(0, Qt.ItemDataRole.UserRole)
            and item.flags() & Qt.ItemFlag.ItemIsDragEnabled
        ]
        if not keys:
            return
        data = self.mimeData(items)
        data.setData("application/x-rigora-scene", json.dumps(keys).encode())
        data.setData("application/x-rigora-session", self.session.encode())
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept scene identities or reusable project sources, never arbitrary model data."""
        if (
            event.mimeData().hasUrls()
            or event.mimeData().hasFormat(ASSET_MIME)
            or event.mimeData().hasFormat("application/x-rigora-scene")
        ):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Keep native hover/expansion behavior for rows and accept source-image folder drops."""
        target = self.itemAt(event.position().toPoint())
        if target and not target.flags() & Qt.ItemFlag.ItemIsDropEnabled:
            self.source_left.emit()
            event.ignore()
            return
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(ASSET_MIME):
            if event.mimeData().hasFormat(ASSET_MIME):
                raw = bytes(event.mimeData().data(ASSET_MIME).data())
                session = bytes(event.mimeData().data("application/x-rigora-session").data())
                if 0 < len(raw) <= 64 and len(session) <= 64:
                    try:
                        self.source_hovered.emit(raw.decode(), session.decode())
                    except UnicodeError:
                        event.ignore()
                        return
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Clear the camera placement ghost when leaving the Scene tree."""
        self.source_left.emit()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        """Translate front-to-back row drops into a back-to-front render insertion point."""
        self.source_left.emit()
        is_asset = event.mimeData().hasFormat(ASSET_MIME)
        is_files = event.mimeData().hasUrls()
        if event.source() is not self and not is_asset and not is_files:
            event.ignore()
            return
        raw = bytes(event.mimeData().data("application/x-rigora-scene").data())
        try:
            keys = tuple(json.loads(raw)) if raw and len(raw) <= 65536 else ()
        except (ValueError, TypeError):
            event.ignore()
            return
        target = self.itemAt(event.position().toPoint())
        if target and not target.flags() & Qt.ItemFlag.ItemIsDropEnabled:
            event.ignore()
            return
        before = None
        parent = None
        if target:
            rect = self.visualItemRect(target)
            y = event.position().y()
            position = (
                QAbstractItemView.DropIndicatorPosition.AboveItem
                if y < rect.top() + 5
                else QAbstractItemView.DropIndicatorPosition.BelowItem
                if y > rect.bottom() - 5
                else QAbstractItemView.DropIndicatorPosition.OnItem
            )
            if position == QAbstractItemView.DropIndicatorPosition.OnItem:
                parent = target.data(0, Qt.ItemDataRole.UserRole)
            else:
                container = target.parent() or self.invisibleRootItem()
                parent = container.data(0, Qt.ItemDataRole.UserRole)
                index = container.indexOfChild(target)
                sibling = (
                    target
                    if position == QAbstractItemView.DropIndicatorPosition.BelowItem
                    else (container.child(index - 1) if index > 0 else None)
                )
                if target.data(0, Qt.ItemDataRole.UserRole + 1) == "Bone":
                    sibling = (
                        target
                        if position == QAbstractItemView.DropIndicatorPosition.AboveItem
                        else container.child(index + 1)
                    )
                before = sibling.data(0, Qt.ItemDataRole.UserRole) if sibling else None
        if is_files:
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if not 0 < len(paths) <= 128:
                event.ignore()
                return
            self.files_dropped.emit(paths, parent, before)
        elif is_asset:
            asset = bytes(event.mimeData().data(ASSET_MIME).data())
            session = bytes(event.mimeData().data("application/x-rigora-session").data())
            if not 0 < len(asset) <= 64 or len(session) > 64:
                event.ignore()
                return
            try:
                self.source_dropped.emit(asset.decode(), session.decode(), parent, before)
            except UnicodeError:
                event.ignore()
                return
        else:
            self.entries_moved.emit(keys, parent, before)
        event.acceptProposedAction()


class ProjectImageList(QListWidget):
    """Copy-drag reusable image identities without removing sources or serializing paths."""

    files_dropped = Signal(object)
    drag_finished = Signal()
    empty_changed = Signal(bool)

    def __init__(self) -> None:
        """Expose source thumbnails and native drag initiation for stage placement."""
        super().__init__()
        configure_card_grid(self)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self._scene_preview_active = False

    def set_empty_action(self, title: str, description: str, label: str, action: QAction) -> None:
        """Show a centered command over an empty grid without replacing its drop surface.

        The existing action owns execution, icons and enabled state. Model changes
        update visibility, so no polling or thumbnail work is needed.
        """
        self.empty_state = QWidget(self.viewport())
        self._empty_command = action
        self.empty_state.setMaximumWidth(280)
        content = QVBoxLayout(self.empty_state)
        content.setContentsMargins(16, 16, 16, 16)
        content.setSpacing(12)
        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        content.addWidget(heading)
        hint = QLabel(description)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(hint)
        self.empty_action = QPushButton(label)
        self.empty_action.setAccessibleName(label)
        self.empty_action.setMinimumHeight(36)
        self.empty_action.clicked.connect(action.trigger)
        content.addWidget(self.empty_action, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout = QVBoxLayout(self.viewport())
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.empty_state, alignment=Qt.AlignmentFlag.AlignCenter)

        action.changed.connect(self._sync_empty_action)
        for signal in (
            self.model().rowsInserted,
            self.model().rowsRemoved,
            self.model().modelReset,
        ):
            signal.connect(self._sync_empty_state)
        self._sync_empty_action()
        self._sync_empty_state()

    @Slot()
    def _sync_empty_action(self) -> None:
        """Follow shared command availability and theme icon changes until view destruction."""
        self.empty_action.setEnabled(self._empty_command.isEnabled())
        self.empty_action.setIcon(self._empty_command.icon())

    @Slot()
    def _sync_empty_state(self) -> None:
        """Keep the empty prompt separate from selectable asset rows."""
        empty = self.count() == 0
        self.empty_state.setVisible(empty)
        self.empty_changed.emit(empty)

    def set_scene_preview_active(self, active: bool) -> None:
        """Record when viewport feedback owns the current source drag."""
        self._scene_preview_active = active

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept external local sources without placing them into the scene."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        """Keep external source imports active anywhere over the asset list."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        """Forward a bounded list of local paths to the shared asynchronous importer."""
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if 0 < len(paths) <= 128:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def mimeTypes(self) -> list[str]:
        """Advertise the bounded internal project-source contract."""
        return [ASSET_MIME]

    def mimeData(self, items: Sequence[QListWidgetItem]) -> QMimeData:
        """Use the project session plus UUID to reject stale cross-project drags."""
        data = QMimeData()
        if items and items[0].data(Qt.ItemDataRole.UserRole):
            data.setData(ASSET_MIME, str(items[0].data(Qt.ItemDataRole.UserRole)).encode())
            data.setData(
                "application/x-rigora-session", str(self.property("documentSession") or "").encode()
            )
        return data

    def startDrag(self, supportedActions: Qt.DropAction) -> None:
        """Use native copy cursors without a thumbnail; the viewport owns the scene ghost."""
        if item := self.currentItem():
            drag = QDrag(self)
            drag.setMimeData(self.mimeData([item]))
            transparent = QPixmap(1, 1)
            transparent.fill(Qt.GlobalColor.transparent)
            drag.setPixmap(transparent)
            self._scene_preview_active = False
            try:
                drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)
            finally:
                self._scene_preview_active = False
                self.drag_finished.emit()
