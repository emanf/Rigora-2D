"""Transient animation selection, clipboard and preview tools over shared editing services."""

import json
from collections.abc import Callable, Iterable
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from rigora.application_services.animation_editing import AnimationEditingService, KeyRef
from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Keyframe, Track
from rigora.domain.project import ProjectError
from rigora.engine.state import ScenePose
from rigora.presentation.viewmodels.playback import PlaybackViewModel


class AnimationEditorViewModel(QObject):
    """Keep GUI state out of persisted curves and route every authoring edit through commands."""

    changed = Signal()
    document_changed = Signal()
    previews_changed = Signal()
    focus_changed = Signal()
    owner_selected = Signal(str)
    key_preview_changed = Signal()
    auto_key_changed = Signal(bool)

    def __init__(self, parent: QObject, playback: PlaybackViewModel) -> None:
        """Own transient key selection, snapping and animator visualization preferences."""
        super().__init__(parent)
        self.playback = playback
        self.document: DocumentService | None = None
        self.service: AnimationEditingService | None = None
        self.selected: tuple[KeyRef, ...] = ()
        self.error = ""
        self.snap = True
        self.onion = False
        self.trails = False
        self.compare: float | None = None
        self.focused_owners: tuple[str, ...] = ()
        self.composer_owners: frozenset[str] | None = None
        self.auto_key = False
        self.preview_pose: ScenePose | None = None
        self._preview_document: DocumentService | None = None
        self._preview_source: object = None
        self._preview_edits: dict[KeyRef, dict[str, Any]] = {}

    def focus_owners(self, owners: Iterable[str]) -> None:
        """Follow stage selection without changing authored channels or the current key
        selection.
        """
        focused = tuple(dict.fromkeys(owners))
        if focused != self.focused_owners:
            self.focused_owners = focused
            self.focus_changed.emit()

    def bind(self, document: DocumentService | None) -> None:
        """Discard cross-document selections and remove keys invalidated by undo or clip changes."""
        if document is not self.document or (
            document and document.project is not self._preview_source
        ):
            self.clear_key_preview()
        if document is not self.document:
            self.selected, self.compare = (), None
            self.composer_owners = None
            self.error = ""
        self.document = document
        self.service = AnimationEditingService(document) if document else None
        known = {(t.id, k.id) for t, k in self.key_records()}
        self.selected = tuple(ref for ref in self.selected if ref in known)
        self.changed.emit()

    def key_records(self) -> tuple[tuple[Track, Keyframe], ...]:
        """Resolve current key records using stable identities rather than tree item positions."""
        try:
            timeline = self.service.timeline if self.service else None
            return tuple((t, k) for t in timeline.tracks for k in t.keyframes) if timeline else ()
        except ProjectError:
            return ()

    def select(self, refs: Iterable[KeyRef]) -> None:
        """Publish a validated selection shared by the dope sheet and curve editor."""
        known = {(t.id, k.id) for t, k in self.key_records()}
        self.selected = tuple(dict.fromkeys(ref for ref in refs if ref in known))
        self.changed.emit()

    def run(
        self, operation: Callable[[AnimationEditingService], Any], *, snap: bool | None = None
    ) -> None:
        """Pause transport, apply one validated operation, then refresh all document adapters."""
        if self.service is None:
            return
        self.clear_key_preview()
        self.playback.pause(snap=snap)
        try:
            operation(self.service)
            self.error = ""
            self.document_changed.emit()
        except (ProjectError, OSError, ValueError, KeyError, TypeError) as error:
            self.error = str(error)
        self.changed.emit()

    def delete(self) -> None:
        """Remove the common selection atomically, respecting track and owner locking."""
        self.run(lambda s: s.edit_keys(dict.fromkeys(self.selected, {}), delete=True))

    def set_auto_key(self, enabled: bool) -> None:
        """Publish explicit recording intent without adding authoring data or history."""
        if self.auto_key == enabled:
            return
        self.auto_key = enabled
        self.auto_key_changed.emit(enabled)

    def preview_keys(self, edits: dict[KeyRef, dict[str, Any]], frame: float) -> None:
        """Reuse a validated scratch timeline for live drags and looping graph previews."""
        if self.document is None:
            return
        if self.playback.session and self.playback.session.playback.is_playing:
            self.playback.pause()
        try:
            if self.document.project is not self._preview_source or edits != self._preview_edits:
                scratch = self.document.fork()
                AnimationEditingService(scratch).edit_keys(edits)
                self._preview_document = scratch
                self._preview_source = self.document.project
                self._preview_edits = edits
            if self._preview_document:
                self.preview_pose = self._preview_document.animation.evaluate(frame)
                self.key_preview_changed.emit()
        except (ProjectError, ValueError, TypeError) as error:
            self.error = str(error)
            self.clear_key_preview()

    def clear_key_preview(self) -> None:
        """Release transient evaluation and restore the saved pose without moving the playhead."""
        active = self.preview_pose is not None
        self.preview_pose, self._preview_document, self._preview_source = None, None, None
        self._preview_edits = {}
        if active:
            self.key_preview_changed.emit()

    def preview_scene(self, scratch: DocumentService, frame: float) -> None:
        """Display an isolated scene evaluation without changing authoring data or playhead.

        The caller owns scratch construction and frame scheduling. The normal preview
        invalidation path releases it when the source document or project changes.
        """
        if self.document is None:
            return
        pose = scratch.animation.evaluate(frame)
        self.preview_snapshot(scratch, pose)

    def preview_snapshot(self, scratch: DocumentService, pose: ScenePose) -> None:
        """Display a caller-owned evaluated pose through the ordinary stale-preview guards."""
        if self.document is None:
            return
        self._preview_document = scratch
        self._preview_source = self.document.project
        self._preview_edits = {}
        self.preview_pose = pose
        self.key_preview_changed.emit()

    def cut(self) -> None:
        """Copy the complete selected keys before atomically removing them from the timeline."""
        self.copy()
        if not self.error:
            self.delete()

    def copy(self) -> None:
        """Write portable key JSON to the system clipboard without modifying the document."""
        if self.service:
            try:
                text = json.dumps(self.service.copy_keys(self.selected), allow_nan=False)
                QApplication.clipboard().setText(text)
                self.error = ""
            except ProjectError as error:
                self.error = str(error)
            self.changed.emit()

    def paste(self, *, duplicate: bool = False) -> None:
        """Paste at the playhead, or duplicate after the selected time span without collisions."""

        def operation(service: AnimationEditingService) -> None:
            """Decode bounded clipboard data before invoking the common paste command."""
            if duplicate:
                data = service.copy_keys(self.selected)
                channels = {
                    (t.owner_id, t.property_path)
                    for t, k in self.key_records()
                    if (t.id, k.id) in self.selected
                }
                end = max(
                    k.frame
                    for t, k in self.key_records()
                    if (t.owner_id, t.property_path) in channels
                )
                frame = end + 1
            else:
                text = QApplication.clipboard().text()
                if len(text) > 4 * 1024 * 1024:
                    raise ProjectError("The key clipboard exceeds the 4 MiB limit.")
                data = json.loads(text)
                frame = self.playback.session.pose.frame if self.playback.session else 0
            self.selected = service.paste_keys(data, frame)

        self.run(operation)

    def visualization(self, *, onion: bool, trails: bool, compare: bool) -> None:
        """Set preview overlays and optionally retain a comparison frame without adding history."""
        self.onion, self.trails = onion, trails
        if not compare:
            self.compare = None
        elif self.compare is None and self.playback.session:
            self.compare = self.playback.session.pose.frame
        self.previews_changed.emit()
