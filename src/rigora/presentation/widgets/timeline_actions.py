"""Card-based editing of scene motion spans and saved appearance choices."""

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.characters import CharacterService
from rigora.domain.project import ProjectError
from rigora.presentation.widgets.appearance_choices import skin_preview
from rigora.presentation.widgets.clip_editor import numeric
from rigora.presentation.widgets.creator_cards import configure_cards
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.widgets.timeline import Timeline


ACTION_LABELS = {
    "motion": "Animation",
    "skins": "Skin",
    "outfits": "Clothing",
    "views": "View",
    "attachment": "Attachment",
}
ACTION_LABELS.update(camera_cut="Cut", camera_motion="Animation", camera_effect="Effect")
ACTION_ICONS = {
    "attachment": "link",
    "motion": "directions_run",
    "skins": "palette",
    "outfits": "dry_cleaning",
    "views": "360",
    "camera_cut": "videocam",
    "camera_motion": "camera_enhance",
    "camera_effect": "auto_awesome",
}


class SceneActionEditor(CustomDialog):
    """Edit one owner's action through canonical services, without nested option trees."""

    def __init__(
        self,
        timeline: "Timeline",
        owner: str,
        kind: str,
        frame: float,
        *,
        segment: str = "",
        refs: tuple[tuple[str, str], ...] = (),
    ) -> None:
        """Capture source context and stable identities; merely opening never edits the project."""
        service = timeline.editor.service
        assert service is not None
        self.timeline, self.owner, self.kind = timeline, owner, kind
        self.document = service.document
        self.context = self.document.animation_context
        self.scene_id = service.scene.id
        self.clip_id = service.clip.id if service.clip else None
        self.segment, self.refs = segment, refs
        self.original_frame = frame
        self.groups: dict[str, Any] = {}
        self.motions = {c.id: c for c in CharacterService(self.document).motions(owner)}
        record = CharacterService(self.document).record(owner)
        super().__init__(timeline, f"{record.name} · {ACTION_LABELS[kind]}")
        self.resize(610, 540)
        box = QVBoxLayout(self.content)
        caption = QLabel(f"{record.name} / {ACTION_LABELS[kind]}")
        caption.setStyleSheet("font-weight:600; font-size:15px; padding:4px 0;")
        box.addWidget(caption)
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        box.addLayout(form)
        self.at_frame = numeric(self, "Action start frame", minimum=0, maximum=1e7)
        self.at_frame.setValue(frame)
        self.at_frame.setSuffix(" fr")
        form.addRow("Start" if kind == "motion" else "Frame", self.at_frame)
        self.group = QComboBox()
        self.group.setAccessibleName("Saved appearance group")
        if kind in ("skins", "outfits"):
            self.groups = {g["id"]: g for g in record.extra.get(kind, ()) if g["variants"]}
            for key, group in self.groups.items():
                self.group.addItem(group["name"], key)
            form.addRow("Collection", self.group)
        self.end = numeric(self, "Animation end frame", minimum=1, maximum=1e7)
        self.end.setSuffix(" fr")
        self.speed = numeric(self, "Animation source speed", minimum=0.01, maximum=100)
        self.speed.setSuffix(" ×")
        self.speed.setValue(1)
        self.repeat = QCheckBox("Loop source animation")
        self.shown = QCheckBox("Show this clothing item")
        self.shown.setChecked(True)
        if kind == "motion":
            form.addRow("End", self.end)
            form.addRow("Speed", self.speed)
            form.addRow("", self.repeat)
            self.layer_order = numeric(self, "Layer order", minimum=0, maximum=100)
            self.layer_order.setDecimals(0)
            self.layer_weight = numeric(self, "Layer weight", minimum=0, maximum=1)
            self.layer_weight.setValue(1)
            self.layer_blend = QComboBox()
            self.layer_blend.addItem("Override", "override")
            self.layer_blend.addItem("Additive · relative to rest", "additive")
            self.fade_in = numeric(self, "Fade in frames", minimum=0, maximum=1e7)
            self.fade_out = numeric(self, "Fade out frames", minimum=0, maximum=1e7)
            fades = QHBoxLayout()
            fades.addWidget(self.fade_in)
            fades.addWidget(self.fade_out)
            form.addRow("Layer order", self.layer_order)
            form.addRow("Weight", self.layer_weight)
            form.addRow("Blend", self.layer_blend)
            form.addRow("Fade in / out", fades)
            flags = QHBoxLayout()
            self.layer_mute, self.layer_solo = QCheckBox("Mute"), QCheckBox("Solo")
            flags.addWidget(self.layer_mute)
            flags.addWidget(self.layer_solo)
            form.addRow("", flags)
            self.body_mask = QListWidget()
            self.body_mask.setMaximumHeight(88)
            self.body_mask.setAccessibleName("Body mask; no checks means all parts")
            members = CharacterService(self.document).members(owner)
            from rigora.domain.entities import Bone, Group, SceneObject, nested_records

            self.mask_records = {
                r.id: r
                for r in nested_records(self.document.scene)
                if r.id in members and isinstance(r, (Bone, Group, SceneObject))
            }
            for part in self.mask_records.values():
                row = QListWidgetItem(part.name)
                row.setData(Qt.ItemDataRole.UserRole, part.id)
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(Qt.CheckState.Unchecked)
                self.body_mask.addItem(row)
            form.addRow("Body mask\nNone checked = all", self.body_mask)
        elif kind == "outfits":
            form.addRow("", self.shown)
        if kind != "motion":
            self.end.hide()
            self.speed.hide()
            self.repeat.hide()
        if kind != "outfits":
            self.shown.hide()
        self.cards = QListWidget()
        self.cards.setAccessibleName(f"Saved {ACTION_LABELS[kind].lower()} choices")
        configure_cards(self.cards, compact=True)
        if kind == "motion" and not segment:
            self.cards.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        box.addWidget(self.cards, 1)
        self.note = QLabel(
            "Drag the span to move it; drag a running icon to trim. Speed changes source playback."
            if kind == "motion"
            else "This choice holds until the next key. "
            "Saved choices are authored in Object Editor."
        )
        self.note.setWordWrap(True)
        self.note.setObjectName("Muted")
        box.addWidget(self.note)
        footer = QHBoxLayout()
        box.addLayout(footer)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer.addWidget(close)
        self.remove = QPushButton("Remove action")
        self.remove.setEnabled(bool(segment or refs))
        self.remove.clicked.connect(self.delete)
        footer.addWidget(self.remove)
        footer.addStretch()
        self.apply_button = QPushButton("Apply changes" if segment or refs else "Insert action")
        self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.apply_button)
        self.group.currentIndexChanged.connect(self.populate)
        self.cards.currentItemChanged.connect(self.choice_changed)
        self.populate()
        if segment:
            window = (
                next(
                    (
                        t.extra["motion_window"]
                        for t in service.timeline.tracks
                        if t.extra.get("motion_window", {}).get("id") == segment
                    ),
                    None,
                )
                if service.timeline
                else None
            )
            if window:
                self.select_choice(window["source"])
                self.end.setValue(window["end"])
                self.speed.setValue(window["speed"])
                self.repeat.setChecked(window["repeat"])
                self.layer_order.setValue(window.get("layer", 0))
                self.layer_weight.setValue(window.get("weight", 1))
                self.layer_blend.setCurrentIndex(
                    max(0, self.layer_blend.findData(window.get("blend", "override")))
                )
                self.fade_in.setValue(window.get("fade_in", 0))
                self.fade_out.setValue(window.get("fade_out", 0))
                self.layer_mute.setChecked(window.get("muted", False))
                self.layer_solo.setChecked(window.get("solo", False))
                for index in range(self.body_mask.count()):
                    row = self.body_mask.item(index)
                    if row.data(Qt.ItemDataRole.UserRole) in window.get("mask", ()):
                        row.setCheckState(Qt.CheckState.Checked)
        elif refs and service.timeline and kind != "views":
            track = next((t for t in service.timeline.tracks if t.id == refs[0][0]), None)
            if track:
                self.group.setCurrentIndex(
                    max(0, self.group.findData(track.extra.get("appearance_group")))
                )
                inspected_key = next((k for k in track.keyframes if (track.id, k.id) in refs), None)
                choice = inspected_key.extra.get("appearance_choice", {}) if inspected_key else {}
                if choice:
                    self.select_choice(choice.get("id"))
                    self.shown.setChecked(choice.get("visible", True))

    def populate(self) -> None:
        """Show a flat grid for one collection; cards do not apply until explicitly confirmed."""
        self.cards.clear()
        if self.kind == "motion":
            options: list[tuple[str | None, str]] = [(c.id, c.name) for c in self.motions.values()]
        elif self.kind == "views":
            from rigora.domain.object_views import VIEW_SLOTS

            options = [(name, name) for name in VIEW_SLOTS]
        else:
            group = self.groups.get(self.group.currentData(), {})
            options = [(v["id"], v["name"]) for v in group.get("variants", ())]
            if self.kind == "outfits" and group:
                options.insert(0, (None, "None"))
        for key, name in options:
            card = QListWidgetItem(self.choice_icon(key), name)
            card.setData(Qt.ItemDataRole.UserRole, key)
            card.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            card.setToolTip(name)
            self.cards.addItem(card)
        self.cards.setCurrentRow(0 if options else -1)
        service = self.timeline.editor.service
        if self.refs and service and service.timeline and self.kind == "views":
            from rigora.domain.object_views import VIEW_SLOTS

            value = next(
                (
                    k.value
                    for t in service.timeline.tracks
                    for k in t.keyframes
                    if (t.id, k.id) in self.refs
                ),
                0,
            )
            self.select_choice(VIEW_SLOTS[max(0, min(len(VIEW_SLOTS) - 1, round(value)))])
        if self.refs and service and service.timeline and self.kind in ("skins", "outfits"):
            records = [
                (t, k)
                for t in service.timeline.tracks
                for k in t.keyframes
                if (t.id, k.id) in self.refs
                and t.extra.get("appearance_group") == self.group.currentData()
            ]
            selected = next(
                (
                    k.extra["appearance_choice"]
                    for _, k in records
                    if k.extra.get("appearance_choice")
                ),
                None,
            )
            if selected:
                self.select_choice(selected.get("id"))
                self.shown.setChecked(selected.get("visible", True))
            elif records:
                group = self.groups[self.group.currentData()]
                if self.kind == "outfits":
                    pose = self.document.animation.evaluate(self.original_frame)
                    characters = CharacterService(self.document)
                    self.select_choice(
                        next(
                            (
                                v["id"]
                                for v in group["variants"]
                                if characters.variant_visible(v, pose)
                            ),
                            None,
                        )
                    )
                else:
                    values = {(t.owner_id, t.property_path): k.value for t, k in records}
                    self.select_choice(
                        next(
                            (
                                v["id"]
                                for v in group["variants"]
                                if v["values"]
                                and all(
                                    values.get((owner, path)) == value
                                    for owner, path, value in v["values"]
                                )
                            ),
                            None,
                        )
                    )
        self.apply_button.setEnabled(bool(options))
        if not options:
            self.note.setText(
                f"No saved {ACTION_LABELS[self.kind].lower()} choices. "
                "Create them in Object Editor first."
            )

    def choice_icon(self, key: str | None) -> QIcon:
        """Reuse decoded artwork and saved swatches; never synchronously decode source images."""
        variant = next(
            (
                v
                for v in self.groups.get(self.group.currentData(), {}).get("variants", ())
                if v["id"] == key
            ),
            None,
        )
        if variant and self.kind == "skins":
            return skin_preview(self.timeline.icons, variant)
        if variant and self.timeline.artwork_icon:
            mesh = next(
                (m for m in self.document.scene.meshes if m.id in variant.get("meshes", ())), None
            )
            if mesh:
                return self.timeline.artwork_icon(mesh.asset_id)
        return self.timeline.icons.icon(
            "visibility_off" if key is None else ACTION_ICONS[self.kind], 40
        )

    def refresh_icons(self) -> None:
        """Replace newly decoded thumbnails in place without resetting selection or scrolling."""
        if (
            self.kind == "outfits"
            and self.isVisible()
            and self.document.project
            and self.document.scene.id == self.scene_id
        ):
            for i in range(self.cards.count()):
                card = self.cards.item(i)
                if card:
                    card.setIcon(self.choice_icon(card.data(Qt.ItemDataRole.UserRole)))

    def select_choice(self, key: str | None) -> None:
        """Restore a saved identity without depending on translated or duplicated labels."""
        for i in range(self.cards.count()):
            item = self.cards.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == key:
                self.cards.setCurrentRow(i)
                return

    def choice_changed(
        self, current: QListWidgetItem | None, previous: QListWidgetItem | None
    ) -> None:
        """Give newly inserted motions their source duration and loop setting."""
        if current is not None and self.kind == "motion" and not self.segment:
            clip = self.motions[current.data(Qt.ItemDataRole.UserRole)]
            self.end.setValue(self.at_frame.value() + clip.out_frame - clip.in_frame)
            self.repeat.setChecked(clip.loop)
        if self.kind == "outfits":
            self.shown.setEnabled(
                current is not None and current.data(Qt.ItemDataRole.UserRole) is not None
            )

    def validate_context(self, service: AnimationEditingService) -> None:
        """Reject pending edits after switching document, scene, object, or active clip."""
        if (
            service.document is not self.document
            or service.scene.id != self.scene_id
            or service.document.animation_context != self.context
            or (service.clip.id if service.clip else None) != self.clip_id
        ):
            raise ProjectError(
                "The timeline changed. Close this editor and select the action again."
            )
        if self.segment and not any(
            t.extra.get("motion_window", {}).get("id") == self.segment
            for t in (service.timeline.tracks if service.timeline else ())
        ):
            raise ProjectError(
                "This animation action was removed. Select an existing action again."
            )

    def apply(self) -> None:
        """Publish a replacement choice or motion timing as one reversible operation."""
        item = self.cards.currentItem()
        if item is None and self.cards.count():
            self.cards.setCurrentRow(0)
            item = self.cards.currentItem()
        if item is None:
            self.note.setText(
                "Create and save a choice in Object Editor before inserting this action."
            )
            return
        choice = item.data(Qt.ItemDataRole.UserRole)
        group_id = self.group.currentData()
        frame, end, speed = self.at_frame.value(), self.end.value(), self.speed.value()
        repeat, shown = self.repeat.isChecked(), self.shown.isChecked()
        refs = self.group_refs(group_id)
        result = self.segment
        sources = [i.data(Qt.ItemDataRole.UserRole) for i in self.cards.selectedItems()] or [choice]
        layer_settings = {}
        if self.kind == "motion":
            mask = {
                self.body_mask.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.body_mask.count())
                if self.body_mask.item(i).checkState() == Qt.CheckState.Checked
            }
            while mask:
                expanded = mask | {
                    r.id
                    for r in self.mask_records.values()
                    if getattr(r, "parent_id", None) in mask
                }
                if expanded == mask:
                    break
                mask = expanded
            layer_settings = dict(
                layer=int(self.layer_order.value()),
                weight=self.layer_weight.value(),
                blend=self.layer_blend.currentData(),
                fade_in=self.fade_in.value(),
                fade_out=self.fade_out.value(),
                muted=self.layer_mute.isChecked(),
                solo=self.layer_solo.isChecked(),
                mask=sorted(mask),
            )

        def commit(service: AnimationEditingService) -> None:
            """Keep source presets intact and place only scene-local evaluated overrides."""
            nonlocal result
            self.validate_context(service)
            characters = CharacterService(service.document)
            with service.document.command_group("Edit scene action"):
                if self.kind == "motion":
                    if end <= frame:
                        raise ProjectError("Animation end must be after its start.")
                    window = (
                        next(
                            (
                                t.extra["motion_window"]
                                for t in service.timeline.tracks
                                if t.extra.get("motion_window", {}).get("id") == self.segment
                            ),
                            None,
                        )
                        if service.timeline
                        else None
                    )
                    if window and window["source"] == choice:
                        characters.edit_segment(
                            self.segment,
                            start=frame,
                            end=end,
                            speed=speed,
                            repeat=repeat,
                            **layer_settings,
                        )
                    else:
                        if self.segment:
                            characters.remove_segment(self.segment)
                        cursor = frame
                        for index, identity in enumerate(sources if not self.segment else [choice]):
                            source = self.motions[identity]
                            duration = (
                                end - frame
                                if index == 0
                                else (source.out_frame - source.in_frame) / speed
                            )
                            result = characters.place_motion(
                                self.owner,
                                identity,
                                cursor,
                                duration / service.scene.settings.fps,
                                speed=speed,
                                repeat=repeat,
                            )
                            characters.edit_segment(result, **layer_settings)
                            cursor += duration
                else:
                    if frame != self.original_frame and refs:
                        service.edit_keys({ref: {"frame": frame} for ref in refs})
                    if self.kind == "views":
                        from rigora.application_services.object_views import ObjectViewsService

                        ObjectViewsService(service.document).key_view(self.owner, choice, frame)
                    elif self.kind == "skins":
                        characters.apply_skin(
                            self.owner, group_id, choice, auto_key=True, frame=frame
                        )
                    else:
                        characters.show_variant(
                            self.owner,
                            group_id,
                            choice,
                            shown if choice else False,
                            auto_key=True,
                            frame=frame,
                        )

        self.timeline.editor.run(commit)
        if self.timeline.editor.error:
            self.note.setText(self.timeline.editor.error)
            return
        self.segment = result
        service = self.timeline.editor.service
        assert service is not None
        if result and service.timeline:
            window = next(
                t.extra["motion_window"]
                for t in service.timeline.tracks
                if t.extra.get("motion_window", {}).get("id") == result
            )
            self.cards.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            self.cards.clearSelection()
            self.select_choice(window["source"])
            self.at_frame.setValue(window["start"])
            self.end.setValue(window["end"])
        self.clip_id = service.clip.id if service.clip else None
        self.original_frame = frame
        self.refs = (
            tuple(
                (t.id, k.id)
                for t in service.timeline.tracks
                for k in t.keyframes
                if (
                    t.extra.get("appearance_owner") == self.owner
                    and t.extra.get("appearance_kind") == self.kind
                    or self.kind == "views"
                    and t.owner_id == self.owner
                    and t.property_path == "object.view"
                )
                and k.frame == frame
            )
            if service.timeline
            else ()
        )
        self.remove.setEnabled(True)
        self.apply_button.setText("Apply changes")
        self.note.setText("Action saved. You can keep editing or close this window.")
        self.timeline.pages.setCurrentIndex(0)

    def group_refs(self, group: str) -> tuple[tuple[str, str], ...]:
        """Limit a collection edit to its own scalar members at the inspected frame."""
        service = self.timeline.editor.service
        ids = (
            {
                t.id
                for t in service.timeline.tracks
                if t.extra.get("appearance_group") == group
                or self.kind == "views"
                and t.owner_id == self.owner
                and t.property_path == "object.view"
            }
            if service and service.timeline
            else set()
        )
        return tuple(ref for ref in self.refs if ref[0] in ids)

    def delete(self) -> None:
        """Remove the selected span or collection choice, retaining its saved definition."""

        def commit(service: AnimationEditingService) -> None:
            """Validate the source before deleting only the inspected action."""
            self.validate_context(service)
            if self.kind == "motion":
                CharacterService(service.document).remove_segment(self.segment)
            else:
                service.edit_keys(
                    {ref: {} for ref in self.group_refs(self.group.currentData())}, delete=True
                )

        self.timeline.editor.run(commit)
        if self.timeline.editor.error:
            self.note.setText(self.timeline.editor.error)
        else:
            self.close()
