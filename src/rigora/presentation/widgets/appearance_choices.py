"""Saved object looks shared between composition and scene animation workspaces."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSignalBlocker, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from rigora.application_services.characters import CharacterService
from rigora.domain.project import ProjectError
from rigora.presentation.icons import IconProvider
from rigora.presentation.widgets.action_buttons import compact_button
from rigora.presentation.widgets.creator_cards import configure_cards
from rigora.presentation.widgets.item_view_state import ItemViewState

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


def skin_preview(icons: IconProvider, variant: dict[str, Any]) -> QIcon:
    """Render saved palette swatches without evaluating or changing the character."""
    colors: dict[tuple[str, str], dict[str, float]] = {}
    for owner, path, value in variant.get("values", ()):
        if ".palette." in path and path.rsplit(".", 1)[-1] in ("r", "g", "b"):
            prefix, channel = path.rsplit(".", 1)
            colors.setdefault((owner, prefix), {})[channel] = value
    palette = list(
        dict.fromkeys(
            tuple(round(p[c]) for c in ("r", "g", "b"))
            for p in colors.values()
            if set(p) == {"r", "g", "b"}
        )
    )[:9]
    if not palette:
        return icons.icon("palette")
    image = QPixmap(76, 76)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    for i, color in enumerate(palette):
        painter.setBrush(QColor(*color))
        painter.drawRoundedRect(3 + (i % 3) * 24, 3 + (i // 3) * 24, 21, 21, 4, 4)
    painter.end()
    return QIcon(image)


class AppearanceChoices(QGroupBox):
    """Choose saved skins or clothing, optionally defining presets from selected parts."""

    def __init__(
        self, host: "MainWindow", kind: str, owner: Callable[[], str], *, editable: bool = False
    ) -> None:
        """Use existing appearance/visibility channels, with explicit keying at the playhead."""
        super().__init__("Skin sheets" if kind == "skins" else "Clothing / dress")
        self.host, self.kind, self.owner = host, kind, owner
        self.editable = editable
        self.source: object = None
        self.descriptor_key: object = None
        self.descriptor_groups: tuple[dict[str, Any], ...] = ()
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        form = QFormLayout()
        self.group_form = form
        box.addLayout(form)
        self.group = QComboBox()
        self.group.setAccessibleName(f"{kind} group")
        self.variant = QComboBox()
        self.variant.setAccessibleName(f"{kind} choice")
        form.addRow("Group", self.group)
        self.variant.hide()
        self.cards = QListWidget()
        self.cards.setAccessibleName("Saved skin cards" if kind == "skins" else "Clothing cards")
        configure_cards(self.cards)
        self.cards.itemClicked.connect(self.choose_card)
        box.addWidget(self.cards)
        self.group.currentIndexChanged.connect(self.populate)
        self.variant.activated.connect(self.apply)
        self.key = QCheckBox("Key choice at playhead")
        self.key.setChecked(True)
        box.addWidget(self.key)
        self.default_button = compact_button(
            host.icons, "Use default", "restart_alt", self.use_default
        )
        box.addWidget(self.default_button)
        if editable:
            self.name = QLineEdit()
            self.name.setPlaceholderText("Group or skin name")
            box.addWidget(self.name)
            row = QHBoxLayout()
            box.addLayout(row)
            for title, icon, callback in (
                ("New group", "create_new_folder", self.new_group),
                ("Save selected look", "save", self.save),
                ("Set selected as default", "check", self.set_default),
            ):
                button = compact_button(host.icons, title, icon, callback)
                row.addWidget(button)
            row.addStretch()
        self.note = QLabel()
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        box.addWidget(self.note)
        host.viewmodel.changed.connect(self.refresh)
        host.viewmodel.scene.changed.connect(self.refresh)
        host.viewmodel.playback.changed.connect(self.refresh_value)

    def groups(self) -> tuple[dict[str, Any], ...]:
        """Read the active owner's authored options without creating appearance stages."""
        document = self.host.viewmodel.documents
        key = self.owner()
        if not document.project or not key:
            return ()
        signature = id(document.project), key, document.animation_context
        if signature == self.descriptor_key:
            return self.descriptor_groups
        characters = CharacterService(document)
        record = characters.records().get(key)
        self.descriptor_groups = characters.appearance_groups(key, self.kind) if record else ()
        self.descriptor_key = signature
        return self.descriptor_groups

    def refresh(self) -> None:
        """Rebuild choices only when their document revision or owner changes."""
        document = self.host.viewmodel.documents
        source = (id(document.project), self.owner(), document.animation_context)
        if source == self.source:
            self.refresh_value()
            return
        self.source = source
        selected = self.group.currentData()
        with QSignalBlocker(self.group):
            self.group.clear()
            for group in self.groups():
                self.group.addItem(group["name"], group["id"])
            self.group.setCurrentIndex(max(0, self.group.findData(selected)))
        self.setEnabled(bool(self.owner()))
        self.populate()

    def populate(self) -> None:
        """List a group's options and its explicitly chosen default."""
        state = ItemViewState.capture(self.cards)
        selected = self.variant.currentData()
        group = next((g for g in self.groups() if g["id"] == self.group.currentData()), None)
        with QSignalBlocker(self.variant):
            self.variant.clear()
            if group:
                if self.kind == "outfits":
                    self.variant.addItem(
                        "None" + (" · default" if not group.get("default") else ""), None
                    )
                for variant in group["variants"]:
                    suffix = " · default" if variant["id"] == group.get("default") else ""
                    self.variant.addItem(variant["name"] + suffix, variant["id"])
                target = selected or group.get("selected") or group.get("default")
                self.variant.setCurrentIndex(max(0, self.variant.findData(target)))
        self.note.setText(
            ""
            if group
            else "Save a named look from the selected parts."
            if self.editable
            else "No saved options yet. Define them in Object Editor."
        )
        with QSignalBlocker(self.cards):
            self.cards.clear()
            for i in range(self.variant.count()):
                identity = self.variant.itemData(i)
                saved = (
                    next((v for v in group["variants"] if v["id"] == identity), None)
                    if group
                    else None
                )
                icon = self.look_icon(saved) if saved else self.host.icons.icon("visibility_off")
                card = QListWidgetItem(
                    icon,
                    self.variant.itemText(i),
                )
                card.setData(Qt.ItemDataRole.UserRole, self.variant.itemData(i))
                self.cards.addItem(card)
            self.cards.setCurrentRow(self.variant.currentIndex())
        self.group_form.setRowVisible(self.group, self.group.count() > 0)
        self.cards.setVisible(self.cards.count() > 0)
        self.key.setVisible(group is not None)
        self.default_button.setVisible(group is not None)
        state.restore(self.cards)
        self.refresh_value()

    def look_icon(self, variant: dict[str, Any]) -> QIcon:
        """Preview saved skin paints or an outfit's actual source thumbnail in its card."""
        if self.kind == "outfits":
            scene = CharacterService(self.host.viewmodel.documents).scene
            mesh = next((m for m in scene.meshes if m.id in variant.get("meshes", ())), None)
            return (
                self.host.asset_icon(mesh.asset_id) if mesh else self.host.icons.icon("checkroom")
            )
        return skin_preview(self.host.icons, variant)

    def choose_card(self, item: QListWidgetItem) -> None:
        """Capture a saved-look click without deleting its item during Qt's signal delivery."""
        self.variant.setCurrentIndex(self.variant.findData(item.data(Qt.ItemDataRole.UserRole)))
        document = self.host.viewmodel.documents
        context = document.animation_context
        choice = self.owner(), self.group.currentData(), self.variant.currentData()

        def commit() -> None:
            """Ignore a queued choice if another document, context or card is now active."""
            if (
                self.host.viewmodel.documents is document
                and document.animation_context == context
                and choice == (self.owner(), self.group.currentData(), self.variant.currentData())
            ):
                self.apply()

        QTimer.singleShot(0, self, commit)

    def refresh_value(self) -> None:
        """Follow evaluated choices when scrubbing; inspection never writes timeline keys."""
        if not self.isVisible() or not self.host.viewmodel.documents.project:
            return
        group = next((g for g in self.groups() if g["id"] == self.group.currentData()), None)
        if not group:
            return
        pose = self.host.viewmodel.documents.animation.pose
        service = CharacterService(self.host.viewmodel.documents)
        selected = None
        if self.kind == "outfits":
            for variant in group["variants"]:
                if service.variant_visible(variant, pose):
                    selected = variant["id"]
                    break
        else:
            looks = {
                d.id: pose.meshes[d.owner_id].appearance
                for d in service.scene.deformers
                if d.kind == "appearance" and d.owner_id in pose.meshes
            }
            for variant in group["variants"]:
                values = {(k, p): v for k, p, v in variant["values"]}
                try:
                    current = {}
                    for identity, path in values:
                        value: Any = looks[identity]
                        for part in path.removeprefix("parameters.").split("."):
                            value = (
                                value[int(part)]
                                if isinstance(value, (list, tuple))
                                else value[part]
                            )
                        current[identity, path] = float(value)
                except (KeyError, IndexError, TypeError, ValueError):
                    continue
                if values and all(abs(current[k] - v) < 1e-5 for k, v in values.items()):
                    selected = variant["id"]
                    break
        with QSignalBlocker(self.variant):
            self.variant.setCurrentIndex(self.variant.findData(selected))
        with QSignalBlocker(self.cards):
            self.cards.setCurrentRow(self.variant.currentIndex())

    def run(self, action: Callable[[CharacterService], object]) -> None:
        """Publish a complete choice as one Undo operation in the active document."""
        self.host.viewmodel.playback.pause()
        try:
            action(CharacterService(self.host.viewmodel.documents))
            self.note.clear()
            self.host.viewmodel.changed.emit()
        except (ProjectError, ValueError) as error:
            self.note.setText(str(error))

    def apply(self) -> None:
        """Switch the selected option in the currently active scene or object timeline."""
        owner, group, variant = self.owner(), self.group.currentData(), self.variant.currentData()
        if not group:
            return
        if self.kind == "skins" and variant:
            self.run(lambda s: s.apply_skin(owner, group, variant, auto_key=self.key.isChecked()))
        elif self.kind == "outfits":
            self.run(
                lambda s: s.show_variant(
                    owner, group, variant, variant is not None, auto_key=self.key.isChecked()
                )
            )

    def new_group(self) -> None:
        """Define a named group without creating artwork or a skeleton."""
        self.run(lambda s: s.skin_group(self.owner(), self.name.text()))
        self.group.setCurrentIndex(self.group.count() - 1)

    def use_default(self) -> None:
        """Apply or key the saved group default, including no clothing."""
        group = next((g for g in self.groups() if g["id"] == self.group.currentData()), None)
        if group:
            self.variant.setCurrentIndex(self.variant.findData(group.get("default")))
            self.apply()

    def save(self) -> None:
        """Save current selected parts' evaluated paints and tint as a reusable skin."""
        self.run(
            lambda s: s.save_skin(
                self.owner(),
                self.group.currentData(),
                self.host.character_panel.scope(),
                self.name.text(),
            )
        )

    def set_default(self) -> None:
        """Mark a saved option as this group's default."""
        owner, group, variant = self.owner(), self.group.currentData(), self.variant.currentData()
        self.run(lambda s: s.appearance_default(owner, self.kind, group, variant))
