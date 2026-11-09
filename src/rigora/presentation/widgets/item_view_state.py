"""Retain user navigation when immutable document revisions rebuild item views."""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QItemSelectionModel, QSignalBlocker, Qt
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem

ItemView = QListWidget | QTreeWidget
Item = QListWidgetItem | QTreeWidgetItem


def entries(view: ItemView, role: int) -> Iterator[tuple[Any, Item]]:
    """Use stable entity/option identities, with name paths for synthetic section rows."""

    def branch(item: QTreeWidgetItem, path: tuple[str, ...]) -> Iterator[tuple[Any, Item]]:
        path = (*path, item.text(0))
        identity = item.data(0, role)
        if identity is None:
            identity = item.data(0, Qt.ItemDataRole.UserRole + 5)
        yield identity if identity is not None else path, item
        for index in range(item.childCount()):
            child = item.child(index)
            if child is not None:
                yield from branch(child, path)

    if isinstance(view, QTreeWidget):
        for index in range(view.topLevelItemCount()):
            item = view.topLevelItem(index)
            if item is not None:
                yield from branch(item, ())
    else:
        for index in range(view.count()):
            card = view.item(index)
            if card is not None:
                identity = card.data(role)
                yield identity if identity is not None else (card.text(),), card


@dataclass
class ItemViewState:
    """A transient snapshot of disclosure, current row, selection and scroll offsets."""

    expanded: dict[Any, bool]
    selected: set[Any]
    current: Any
    horizontal: int
    vertical: int
    role: int

    @classmethod
    def capture(cls, view: ItemView, role: int = Qt.ItemDataRole.UserRole) -> "ItemViewState":
        """Capture view state before rows are removed; no project data is read or modified."""
        rows = tuple(entries(view, role))
        return cls(
            {key: row.isExpanded() for key, row in rows if isinstance(row, QTreeWidgetItem)},
            {key for key, row in rows if row.isSelected()},
            next((key for key, row in rows if row is view.currentItem()), None),
            view.horizontalScrollBar().value(),
            view.verticalScrollBar().value(),
            role,
        )

    def restore(self, view: ItemView, *, selection: bool = False) -> None:
        """Restore surviving rows; preserve model selection unless explicitly requested."""
        with QSignalBlocker(view):
            for key, row in entries(view, self.role):
                if isinstance(row, QTreeWidgetItem) and key in self.expanded:
                    row.setExpanded(self.expanded[key])
                if selection:
                    row.setSelected(key in self.selected)
                if key == self.current and row.isSelected():
                    if isinstance(view, QTreeWidget) and isinstance(row, QTreeWidgetItem):
                        view.setCurrentItem(row, 0, QItemSelectionModel.SelectionFlag.NoUpdate)
                    elif isinstance(view, QListWidget) and isinstance(row, QListWidgetItem):
                        view.setCurrentItem(row, QItemSelectionModel.SelectionFlag.NoUpdate)
            view.doItemsLayout()
            view.horizontalScrollBar().setValue(self.horizontal)
            view.verticalScrollBar().setValue(self.vertical)
