"""Canonical document lifecycle and reversible settings edits."""

import hashlib
import mimetypes
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal
from uuid import uuid4

from rigora.application_services.animation import AnimationSession
from rigora.application_services.commands import (
    Command,
    CommandHistory,
    CompoundCommand,
    PreparedProjectChange,
    ProjectPatch,
    ScenePatch,
)
from rigora.domain.entities import ENTITY_COLLECTIONS, AnimationClip, Asset, Entity
from rigora.domain.project import Project, ProjectError, Scene, SceneSettings
from rigora.domain.validation import frozen_extra, json_copy
from rigora.engine.constraints import ConstraintSolver
from rigora.engine.deformation import DeformerSolver
from rigora.engine.sampling import TrackSampler
from rigora.engine.state import ScenePose
from rigora.infrastructure.migrations import CURRENT_VERSION
from rigora.infrastructure.project_storage import MAX_ASSET_SIZE, ProjectStorage


@dataclass(frozen=True)
class SaveRequest:
    """An immutable save revision with independent assets, safe to serialize on a worker."""

    project: Project
    manifest: dict[str, Any]
    assets: Mapping[str, bytes]
    destination: Path
    source_path: Path | None
    source_checksum: str | None
    overwrite: bool
    storage: ProjectStorage

    def write(self) -> str:
        """Publish exactly this revision through ordinary conflict/backup validation."""
        return self.storage.save(
            self.destination,
            self.project,
            self.manifest,
            expected_digest=self.source_checksum if self.destination == self.source_path else None,
            overwrite=self.overwrite,
            asset_data=self.assets,
        )


class DocumentService:
    """Own a document session, asset bytes, safe persistence, and reversible command history."""

    def __init__(
        self,
        storage: ProjectStorage | None = None,
        *,
        constraint_solvers: Mapping[str, ConstraintSolver] | None = None,
        deformer_solvers: Mapping[str, DeformerSolver] | None = None,
        track_samplers: Mapping[str, TrackSampler] | None = None,
        channel_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Create an empty session with an injectable persistence adapter."""
        self.session_id = str(uuid4())
        self.storage = storage or ProjectStorage()
        self._constraint_solvers = dict(constraint_solvers or {})
        self._deformer_solvers = dict(deformer_solvers or {})
        self._track_samplers = dict(track_samplers or {})
        self.channel_metadata = frozen_extra(channel_metadata or {})
        self.project: Project | None = None
        self.path: Path | None = None
        self.manifest: dict[str, Any] = {}
        self._checksum: str | None = None
        self._saved: Project | None = None
        self.history = CommandHistory()
        self._transaction_commands: list[Command] | None = None
        self._asset_data: dict[str, bytes] = {}
        self._asset_root: Path | None = None
        self.migration_note: str | None = None
        self.warnings: tuple[str, ...] = ()
        self._animation: AnimationSession | None = None
        self.animation_context: str | None = None
        self.animation_scope: frozenset[str] | None = None
        self.separated_animation = False
        self._animation_cursors: dict[str | None, tuple[str | None, float, bool]] = {}
        self._clip_cursors: dict[str, tuple[float, bool]] = {}
        self._context_clip_cache: tuple[object, str | None, tuple[AnimationClip, ...]] | None = None
        self._active_scene_id: str | None = None
        self._scene_cursors: dict[str, tuple[str | None, float, bool]] = {}
        self._link_objects = True

    @property
    def scene(self) -> Scene:
        """Resolve the active scene without constructing any animation runtime."""
        if self.project is None:
            raise ProjectError("Create or open a project before accessing a scene.")
        return next(
            (s for s in self.project.scenes if s.id == self._active_scene_id),
            self.project.scenes[0],
        )

    @property
    def context_key(self) -> str:
        """Identify transient editor state independently for each scene in this document."""
        return f"{self.session_id}:{self.scene.id}" if self.project else self.session_id

    def select_scene(self, scene_id: str) -> None:
        """Pause and release the previous runtime; restore only lightweight cursor state."""
        if self.project is None or not any(s.id == scene_id for s in self.project.scenes):
            raise ProjectError("Choose an existing scene.")
        if self.scene.id == scene_id and self._active_scene_id in (None, scene_id):
            return
        if self._animation is not None:
            self._animation.pause()
            self._scene_cursors[self._animation.scene.id] = (
                (
                    self._animation.evaluator.clip.id if self._animation.evaluator.clip else None,
                    self._animation.playback.frame,
                    self._animation.playback.loop,
                )
                if self.animation_context is None
                else self._animation_cursors.get(None, (None, 0, False))
            )
        self._active_scene_id = scene_id
        self._animation = None
        self.animation_context, self.animation_scope = None, None
        self.separated_animation = True
        self._animation_cursors = {None: self._scene_cursors.get(scene_id, (None, 0, False))}
        self._clip_cursors.clear()
        self._context_clip_cache = None

    def _restore_scene_selection(self) -> None:
        """Release stale runtime state when Undo removes the selected scene."""
        if (
            self.project
            and self._active_scene_id
            and not any(s.id == self._active_scene_id for s in self.project.scenes)
        ):
            self.select_scene(self.project.scenes[0].id)

    def scene_reference_pose(self) -> ScenePose:
        """Sample the paused main scene without changing Object Editor's scoped runtime.

        Callers own the immutable result; no second animation runtime is retained.
        This optional sample includes other objects only when explicitly requested.
        """
        clip, frame, _ = self._animation_cursors.get(None, (None, 0, False))
        available = tuple(
            c
            for c in self.scene.clips
            if not c.extra.get("character_id") and not c.extra.get("object_id")
        )
        if not any(c.id == clip for c in available):
            clip = available[0].id if available else None
        return AnimationSession(
            self.scene,
            clip,
            solvers=self.constraint_solvers,
            deformers=self.deformer_solvers,
            samplers=self.track_samplers,
            frame=frame,
            select_first_clip=False,
        ).pose

    def add_scene(self, name: str = "") -> str:
        """Add one independent scene as an undoable change, without compiling it."""
        if self.project is None:
            raise ProjectError("Create or open a project first.")
        from rigora.application_services.cameras import with_main_camera

        scene = with_main_camera(
            Scene(
                name=name.strip() or f"Scene {len(self.project.scenes) + 1:02}",
                settings=self.scene.settings,
            )
        )
        self.execute(
            ProjectPatch(
                "Add scene",
                {"scenes": self.project.scenes},
                {"scenes": (*self.project.scenes, scene)},
            )
        )
        return scene.id

    def delete_scene(self, scene_id: str) -> None:
        """Delete a complete scene in one Undo step, retaining shared source assets."""
        if self.project is None or not any(s.id == scene_id for s in self.project.scenes):
            raise ProjectError("Choose an existing scene.")
        if len(self.project.scenes) == 1:
            raise ProjectError("A project needs at least one scene.")
        if self.scene.id == scene_id:
            self.select_scene(next(s.id for s in self.project.scenes if s.id != scene_id))
        self.execute(
            ProjectPatch(
                "Delete scene",
                {"scenes": self.project.scenes},
                {"scenes": tuple(s for s in self.project.scenes if s.id != scene_id)},
            )
        )

    @property
    def constraint_solvers(self) -> Mapping[str, ConstraintSolver]:
        """Return a read-only view of the document's injected constraint solvers."""
        return MappingProxyType(self._constraint_solvers)

    def fork(self) -> "DocumentService":
        """Create an isolated scratch session sharing immutable authoring records and bytes.

        The asset map and animation state are independent; history and save destination are
        never inherited. External sources retain their original validated project directory.
        """
        scratch = DocumentService(
            constraint_solvers=self.constraint_solvers,
            deformer_solvers=self.deformer_solvers,
            track_samplers=self.track_samplers,
            channel_metadata=self.channel_metadata,
        )
        scratch.project = self.project
        scratch._link_objects = False
        scratch._active_scene_id = self.scene.id if self.project else None
        scratch._scene_cursors = dict(self._scene_cursors)
        scratch._asset_data = dict(self._asset_data)
        scratch._asset_root = self._asset_root
        scratch.animation_context = self.animation_context
        scratch.animation_scope = self.animation_scope
        scratch.separated_animation = self.separated_animation
        scratch._animation_cursors = dict(self._animation_cursors)
        scratch._clip_cursors = dict(self._clip_cursors)
        if self.project is not None:
            scratch._animation = self.animation.fork()
        return scratch

    @property
    def deformer_solvers(self) -> Mapping[str, DeformerSolver]:
        """Expose injected deformation functions without allowing registry mutation."""
        return MappingProxyType(self._deformer_solvers)

    @property
    def track_samplers(self) -> Mapping[str, TrackSampler]:
        """Expose injected numeric track sampling callbacks without permitting registry mutation."""
        return MappingProxyType(self._track_samplers)

    @property
    def selected_clip_id(self) -> str | None:
        """Return clip identity without compiling possibly unsupported animation channels."""
        scene = self.scene if self.project else None
        previous = self._animation.evaluator.clip if self._animation else None
        if scene and self.separated_animation:
            available = self.context_clips()
            preferred = (
                previous.id
                if previous
                else self._animation_cursors.get(self.animation_context, (None, 0, False))[0]
            )
            return next(
                (c.id for c in available if c.id == preferred),
                available[0].id if available else None,
            )
        if scene:
            return next(
                (c.id for c in scene.clips if previous and c.id == previous.id),
                scene.clips[0].id if scene.clips else None,
            )
        return None

    def context_clips(self) -> tuple[AnimationClip, ...]:
        """List actions for the edited object, or scene arrangements outside Object Editor."""
        if self.project is None:
            return ()
        scene = self.scene
        if not self.separated_animation:
            return scene.clips
        cached = self._context_clip_cache
        if cached and cached[0] is scene and cached[1] == self.animation_context:
            return cached[2]
        if self.animation_context:
            from rigora.application_services.characters import CharacterService

            if self.animation_context not in {
                r.id for r in (*scene.groups, *scene.objects, *scene.characters)
            }:
                self.animation_context = None
                self.animation_scope = None
                return self.context_clips()
            clips = CharacterService(self).motions(self.animation_context)
            owner = CharacterService(self).record(self.animation_context)
            if owner.extra.get("view_slots"):
                from rigora.application_services.object_views import ObjectViewsService

                active = str(owner.extra.get("active_view", "Default"))
                members = ObjectViewsService(self).edit_members(owner.id) - {owner.id}
                timelines = {t.id: t for t in scene.timelines}
                clips = tuple(
                    c
                    for c in clips
                    if (
                        c.extra.get("object_view") == active
                        or "object_view" not in c.extra
                        and any(t.owner_id in members for t in timelines[c.timeline_id].tracks)
                        or "object_view" not in c.extra
                        and all(t.owner_id == owner.id for t in timelines[c.timeline_id].tracks)
                    )
                )
        else:
            clips = tuple(
                c
                for c in scene.clips
                if not c.extra.get("character_id") and not c.extra.get("object_id")
            )
        self._context_clip_cache = scene, self.animation_context, clips
        return clips

    def set_animation_context(
        self, owner: str | None, scope: frozenset[str] | None = None, *, prepare: bool = True
    ) -> None:
        """Suspend the current transport and restore an independent object/scene cursor.

        This is transient editor state: switching workspaces never authors a clip or an Undo
        command. Only active-object meshes and dynamics are evaluated in the object workspace.
        """
        if (
            self.separated_animation
            and owner == self.animation_context
            and scope == self.animation_scope
        ):
            return
        previous = self._animation
        if previous is not None:
            previous.pause()
            self._animation_cursors[self.animation_context] = (
                previous.evaluator.clip.id if previous.evaluator.clip else None,
                previous.playback.frame,
                previous.playback.loop,
            )
        self.separated_animation = True
        self.animation_context, self.animation_scope = owner, scope
        self._animation = None
        if self.project is None or not prepare:
            return
        available = self.context_clips()
        clip, frame, loop = self._animation_cursors.get(owner, (None, 0, False))
        if (clip is not None or available) and not any(c.id == clip for c in available):
            clip = available[0].id if available else None
            frame = 0
        self._animation = AnimationSession(
            self.scene,
            clip,
            solvers=self.constraint_solvers,
            deformers=self.deformer_solvers,
            samplers=self.track_samplers,
            frame=frame,
            select_first_clip=False,
            scope=scope,
            local_object=owner,
        )
        self._animation.set_loop(loop)

    @property
    def animation(self) -> AnimationSession:
        """Return the active scene's compiled runtime, rebuilding only when its source changes."""
        if self.project is None:
            raise ProjectError("Create or open a project before evaluating animation.")
        scene = self.scene
        previous = self._animation
        if previous is None or previous.scene is not scene:
            selected = self.selected_clip_id
            if not any(clip.id == selected for clip in scene.clips):
                selected = None
            current = AnimationSession(
                scene,
                selected,
                solvers=self._constraint_solvers,
                deformers=self._deformer_solvers,
                samplers=self._track_samplers,
                frame=previous.playback.frame
                if previous
                else self._animation_cursors.get(self.animation_context, (None, 0, False))[1],
                select_first_clip=not self.separated_animation,
                scope=self.animation_scope,
                local_object=self.animation_context,
                deformation_plan=previous.evaluator.deformation if previous else None,
            )
            if previous is not None:
                current.set_loop(previous.playback.loop)
                current.playback.state = (
                    "paused" if previous.playback.state != "stopped" else "stopped"
                )
            elif self.animation_context in self._animation_cursors:
                current.set_loop(self._animation_cursors[self.animation_context][2])
            self._animation = current
        assert self._animation is not None
        return self._animation

    def use_prepared_animation(self, session: AnimationSession) -> None:
        """Adopt an evaluated session only for the exact current authoring contents."""
        if self.project is None or session.scene.id != self.scene.id:
            raise ProjectError("Prepared animation does not match the current scene.")
        if (
            session.scene != self.scene
            or session.evaluator.scope != self.animation_scope
            or session.evaluator.local_object != self.animation_context
        ):
            session = AnimationSession(
                self.scene,
                session.evaluator.clip.id if session.evaluator.clip else None,
                solvers=self.constraint_solvers,
                deformers=self.deformer_solvers,
                samplers=self.track_samplers,
                frame=session.pose.frame,
                select_first_clip=False,
                scope=self.animation_scope,
                local_object=self.animation_context,
            )
        session.scene = self.scene
        self._animation = session

    def select_animation_clip(self, clip_id: str) -> None:
        """Compile a selected clip atomically, including when another clip cannot be evaluated."""
        if self.project is None:
            raise ProjectError("Create or open a project before selecting animation.")
        if self.separated_animation and not any(c.id == clip_id for c in self.context_clips()):
            raise ProjectError("Choose an animation in the active Scene or Object Editor.")
        previous = self._animation
        if previous and previous.evaluator.clip:
            self._clip_cursors[previous.evaluator.clip.id] = (
                previous.playback.frame,
                previous.playback.loop,
            )
        default_loop = next((c.loop for c in self.scene.clips if c.id == clip_id), False)
        frame, loop = self._clip_cursors.get(clip_id, (0, default_loop))
        self._animation = AnimationSession(
            self.scene,
            clip_id,
            solvers=self._constraint_solvers,
            deformers=self._deformer_solvers,
            samplers=self._track_samplers,
            scope=self.animation_scope,
            local_object=self.animation_context,
            frame=frame,
            deformation_plan=previous.evaluator.deformation if previous else None,
        )
        self._animation.set_loop(loop)

    def configure_extensions(
        self,
        *,
        constraints: Mapping[str, ConstraintSolver],
        deformers: Mapping[str, DeformerSolver],
        samplers: Mapping[str, TrackSampler] | None = None,
        channel_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Refresh solver registries without changing authored records or undo history."""
        if (
            dict(constraints) == self._constraint_solvers
            and dict(deformers) == self._deformer_solvers
            and (samplers is None or dict(samplers) == self._track_samplers)
            and (channel_metadata is None or channel_metadata == self.channel_metadata)
        ):
            return
        previous = self._animation
        self._constraint_solvers, self._deformer_solvers = dict(constraints), dict(deformers)
        if samplers is not None:
            self._track_samplers = dict(samplers)
        if channel_metadata is not None:
            self.channel_metadata = frozen_extra(channel_metadata)
        self._animation = None
        if previous and self.project:
            try:
                current = self.animation
                if previous.evaluator.clip:
                    self.select_animation_clip(previous.evaluator.clip.id)
                    current = self.animation
                current.seek(previous.pose.frame)
                current.set_loop(previous.playback.loop)
            except ProjectError:
                self._animation = None

    @property
    def dirty(self) -> bool:
        """Compare the immutable model to its saved baseline without serializing the document."""
        return self.project is not None and self.project != self._saved

    @property
    def can_undo(self) -> bool:
        """Report whether this document has a reversible committed action."""
        return bool(self.history.undo_stack)

    @property
    def can_redo(self) -> bool:
        """Report whether a reverted action can be reapplied."""
        return bool(self.history.redo_stack)

    def new(
        self,
        name: str = "Untitled project",
        settings: SceneSettings | None = None,
        *,
        with_camera: bool = True,
    ) -> None:
        """Create an unsaved scene with Main Camera and clear assets/history.

        Asset builders pass ``with_camera=False`` for reusable artwork fragments;
        user projects and independently added scenes always start with a camera.
        """
        if self._transaction_commands is not None:
            raise ProjectError("Finish the active transaction before changing document lifecycle.")
        project = Project(name=name)
        if settings is not None:
            project = replace(project, scenes=(replace(project.scenes[0], settings=settings),))
        from rigora.application_services.cameras import with_main_camera

        if with_camera:
            project = replace(project, scenes=(with_main_camera(project.scenes[0]),))
        self.project, self.path, self.manifest = project, None, {}
        self._active_scene_id = None
        self._scene_cursors.clear()
        self._checksum, self._saved = None, None
        self.history = CommandHistory(self.history.limit)
        self._animation = None
        self.animation_context, self.animation_scope = None, None
        self.separated_animation = False
        self._animation_cursors.clear()
        self._clip_cursors.clear()
        self._context_clip_cache = None
        self._asset_data.clear()
        self._asset_root = None
        self.migration_note = None
        self.warnings = ()

    def open(self, path: Path) -> None:
        """Load and validate a package before replacing session state; flag migrated data dirty."""
        if self._transaction_commands is not None:
            raise ProjectError("Finish the active transaction before changing document lifecycle.")
        path = path.resolve()
        loaded = self.storage.load_document(path)
        self.project, self.path, self.manifest = loaded.project, path, loaded.manifest
        self._active_scene_id = None
        self._scene_cursors.clear()
        self._asset_data = dict(loaded.assets)
        self._asset_root = path.parent
        self._checksum = loaded.checksum
        self.migration_note = (
            f"Project upgraded from format {loaded.source_version} to {CURRENT_VERSION}; "
            "save to keep the upgrade with a backup."
            if loaded.source_version < CURRENT_VERSION
            else None
        )
        self._saved = None if self.migration_note else self.project
        self.history = CommandHistory(self.history.limit)
        self._animation = None
        self.animation_context, self.animation_scope = None, None
        self.separated_animation = False
        self._animation_cursors.clear()
        self._clip_cursors.clear()
        self._context_clip_cache = None
        self._refresh_asset_warnings()

    def save(self, path: Path | None = None, *, overwrite: bool = False) -> None:
        """Publish the active project and assets, then advance its saved-state baseline."""
        request = self.prepare_save(path, overwrite=overwrite)
        self.complete_save(request, request.write())

    def prepare_save(self, path: Path | None = None, *, overwrite: bool = False) -> SaveRequest:
        """Capture a revision cheaply on the document owner; perform no serialization or writes."""
        if self._transaction_commands is not None:
            raise ProjectError("Finish the active transaction before changing document lifecycle.")
        if self.project is None:
            raise ProjectError("Create or open a project first.")
        destination = path or self.path
        if destination is None:
            raise ProjectError("Choose a project destination with Save As.")
        destination = destination.resolve()
        if (
            self._asset_root is not None
            and destination.parent != self._asset_root
            and any(asset.storage == "external" for asset in self.project.assets)
        ):
            raise ProjectError("Embed linked assets before saving to another project directory.")
        return SaveRequest(
            self.project,
            json_copy(self.manifest),
            MappingProxyType(dict(self._asset_data)),
            destination,
            self.path,
            self._checksum,
            overwrite,
            self.storage,
        )

    def complete_save(self, request: SaveRequest, checksum: str) -> None:
        """Adopt the revision actually written; newer edits remain dirty after background save."""
        if self.path != request.source_path or self._checksum != request.source_checksum:
            raise ProjectError("Snapshot saved, but the document destination changed meanwhile.")
        if self.project is None or self.project.id != request.project.id:
            raise ProjectError("Snapshot saved, but this document now contains another project.")
        self.path, self._checksum, self._saved = request.destination, checksum, request.project
        self._asset_root = request.destination.parent
        self.migration_note = None

    def persistence_copy(self) -> "DocumentService":
        """Capture immutable authoring/assets without compiling animation; caller owns the copy."""
        if self._transaction_commands is not None:
            raise ProjectError("Finish the current transaction before taking a recovery snapshot.")
        scratch = DocumentService(
            self.storage,
            constraint_solvers=self.constraint_solvers,
            deformer_solvers=self.deformer_solvers,
            track_samplers=self.track_samplers,
            channel_metadata=self.channel_metadata,
        )
        scratch.project = self.project
        scratch.manifest = json_copy(self.manifest)
        scratch._asset_data = dict(self._asset_data)
        scratch._asset_root = self._asset_root
        scratch._active_scene_id = self._active_scene_id
        scratch.separated_animation = self.separated_animation
        scratch._animation_cursors = dict(self._animation_cursors)
        scratch._clip_cursors = dict(self._clip_cursors)
        return scratch

    @property
    def cursor_frame(self) -> float:
        """Read the retained display frame without compiling an unsupported or inactive clip."""
        return self._animation.pose.frame if self._animation is not None else 0.0

    def recover(self, backup: Path) -> None:
        """Open a backup as unsaved work while retaining its asset resolution directory."""
        if self._transaction_commands is not None:
            raise ProjectError("Finish the active transaction before changing document lifecycle.")
        loaded = self.storage.load_document(backup)
        self.project, self.path, self.manifest = loaded.project, None, loaded.manifest
        self._active_scene_id = None
        self._scene_cursors.clear()
        self._asset_data = dict(loaded.assets)
        self._asset_root = backup.resolve().parent
        self._checksum, self._saved = None, None
        self.history = CommandHistory(self.history.limit)
        self._animation = None
        self.animation_context, self.animation_scope = None, None
        self.separated_animation = False
        self._animation_cursors.clear()
        self._clip_cursors.clear()
        self._context_clip_cache = None
        self.migration_note = None
        self._refresh_asset_warnings()

    def execute(self, command: Command) -> None:
        """Validate and publish a reversible mutation against the active immutable model."""
        if self.project is None:
            raise ProjectError("Create or open a project first.")
        changed = command.apply(self.project)
        if not isinstance(changed, Project):
            raise ProjectError("A project command must return a validated Project.")
        if changed == self.project:
            return
        if self._transaction_commands is None:
            command, changed = self._linked_objects_command(self.project, command, changed)
        self.project = changed
        self._restore_scene_selection()
        if self._transaction_commands is not None:
            self._transaction_commands.append(command)
        else:
            self.history.record(command)

    def adopt_prepared(self, snapshot: "DocumentService", baseline: Project, label: str) -> None:
        """Publish an already linked/evaluated worker result atomically on its owning thread.

        A stale document, scene, animation context or open transaction rejects the
        result. Source bytes and compiled animation remain owned by this session;
        Undo/Redo use validated immutable revisions without re-running the import.
        """
        if self.project is not baseline or self._transaction_commands is not None:
            raise ProjectError("The project changed during placement. Drop the template again.")
        if (
            snapshot.project is None
            or snapshot.scene.id != self.scene.id
            or snapshot.animation_context != self.animation_context
            or snapshot.animation_scope != self.animation_scope
            or snapshot._link_objects != self._link_objects
        ):
            raise ProjectError("Prepared placement no longer matches the active editor.")
        command = PreparedProjectChange(label, baseline, snapshot.project)
        changed = command.apply(baseline)
        self._asset_data.update(snapshot._asset_data)
        self.project = changed
        self._animation = snapshot._animation
        self._animation_cursors = dict(snapshot._animation_cursors)
        self._clip_cursors = dict(snapshot._clip_cursors)
        self._context_clip_cache = None
        self.history.record(command)
        self._restore_scene_selection()

    def _linked_objects_command(
        self, before: Project, command: Command, changed: Project
    ) -> tuple[Command, Project]:
        """Fold project-local object publication and propagation into the author's Undo step."""
        from rigora.application_services.object_library import synchronize_objects

        if not self._link_objects:
            return command, changed
        linked = synchronize_objects(before, changed)
        if linked == changed:
            return command, changed
        patch = ProjectPatch(
            "Update linked Objects",
            {"scenes": changed.scenes, "extra": changed.extra},
            {"scenes": linked.scenes, "extra": linked.extra},
        )
        return CompoundCommand(command.label, (command, patch)), linked

    @contextmanager
    def transaction(self, label: str) -> Iterator[None]:
        """Commit several commands as one undo step or restore the original state on failure."""
        if self.project is None or self._transaction_commands is not None:
            raise ProjectError("Transactions require an open project and cannot be nested.")
        previous = self.project
        previous_assets = dict(self._asset_data)
        commands: list[Command] = []
        self._transaction_commands = commands
        try:
            yield
            if commands:
                command, self.project = self._linked_objects_command(
                    previous, CompoundCommand(label, tuple(commands)), self.project
                )
        except BaseException:
            self.project = previous
            self._asset_data = previous_assets
            raise
        else:
            if commands:
                self.history.record(command)
        finally:
            self._transaction_commands = None

    @contextmanager
    def command_group(self, label: str) -> Iterator[None]:
        """Compose service operations into one undo item with rollback to a nested savepoint."""
        if self._transaction_commands is None:
            with self.transaction(label):
                yield
            return
        previous, assets = self.project, dict(self._asset_data)
        commands, count = self._transaction_commands, len(self._transaction_commands)
        try:
            yield
        except BaseException:
            self.project, self._asset_data = previous, assets
            del commands[count:]
            raise

    def update_settings(self, name: str, scene_name: str, settings: SceneSettings) -> None:
        """Change project and scene settings together as one reversible authoring action."""
        project = self.project
        if project is None:
            raise ProjectError("Create or open a project first.")
        scene = self.scene
        self.execute(
            CompoundCommand(
                "Edit project settings",
                (
                    ProjectPatch("Rename project", {"name": project.name}, {"name": name}),
                    ScenePatch(
                        "Edit scene settings",
                        scene.id,
                        {"name": scene.name, "settings": scene.settings},
                        {"name": scene_name, "settings": settings},
                    ),
                ),
            )
        )

    def add_entities(self, scene_id: str, collections: Mapping[str, tuple[Entity, ...]]) -> None:
        """Insert related entity records atomically so cross-references are validated together."""
        project = self.project
        if project is None:
            raise ProjectError("Create or open a project first.")
        scene = next((item for item in project.scenes if item.id == scene_id), None)
        if scene is None or not set(collections) <= set(ENTITY_COLLECTIONS):
            raise ProjectError("Invalid scene or entity collection.")
        before = {key: getattr(scene, key) for key in collections}
        after = {key: (*before[key], *values) for key, values in collections.items()}
        self.execute(ScenePatch("Add scene entities", scene_id, before, after))

    def undo(self) -> None:
        """Revert the last command without cloning unchanged project substructures."""
        if self._transaction_commands is not None:
            raise ProjectError("Finish the active transaction before undoing.")
        if self.project is not None:
            self.project = self.history.undo(self.project)
            self._restore_scene_selection()

    def redo(self) -> None:
        """Reapply a reverted command while retaining the current saved-state baseline."""
        if self._transaction_commands is not None:
            raise ProjectError("Finish the active transaction before redoing.")
        if self.project is not None:
            self.project = self.history.redo(self.project)
            self._restore_scene_selection()

    def read_asset(self, asset_id: str) -> bytes:
        """Resolve embedded bytes or a bounded external file within the project directory."""
        project = self.project
        asset = next((a for a in project.assets if a.id == asset_id), None) if project else None
        if asset is None:
            raise ProjectError("The asset ID is not part of this project.")
        if asset.storage == "embedded":
            data = self._asset_data.get(asset.source)
            if data is None:
                raise ProjectError(f"Embedded asset is unavailable: {asset.name}")
            return data
        if self._asset_root is None:
            raise ProjectError("An external asset needs a saved project directory.")
        base = self._asset_root.resolve()
        source = (base / asset.source).resolve()
        if not source.is_relative_to(base):
            raise ProjectError("External asset resolves outside the project directory.")
        data = self._read_asset_file(source)
        if asset.sha256 is not None and hashlib.sha256(data).hexdigest() != asset.sha256:
            raise ProjectError(f"External asset changed since registration: {asset.name}")
        return data

    @staticmethod
    def _read_asset_file(path: Path) -> bytes:
        """Read opaque source data with a size bound and actionable filesystem errors."""
        try:
            with path.open("rb") as stream:
                data = stream.read(MAX_ASSET_SIZE + 1)
            if len(data) > MAX_ASSET_SIZE:
                raise ProjectError("Source asset exceeds the 32 MiB limit.")
            return data
        except OSError as error:
            raise ProjectError(f"Cannot read asset {path.name}: {error}") from error

    def import_asset(self, source: Path, *, embed: bool = True) -> Asset:
        """Register a source file as portable embedded data or an authorized relative link."""
        if self.project is None:
            raise ProjectError("Create or open a project first.")
        source = source.resolve()
        data = self._read_asset_file(source)
        asset_id = str(uuid4())
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", source.name).lstrip(".") or "asset.bin"
        if embed:
            uri = f"assets/{asset_id}/{filename}"
        else:
            if self._asset_root is None or not source.is_relative_to(self._asset_root):
                raise ProjectError("Linked assets must stay within a saved project directory.")
            uri = source.relative_to(self._asset_root).as_posix()
        media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        kind: Literal["raster", "vector", "audio", "sequence"] = (
            "vector"
            if source.suffix.lower() == ".svg"
            else "audio"
            if media_type.startswith("audio/")
            else "raster"
        )
        asset = Asset(
            id=asset_id,
            name=source.name[:200],
            source=uri,
            storage="embedded" if embed else "external",
            media_type=media_type,
            sha256=hashlib.sha256(data).hexdigest(),
            kind=kind,
        )
        before = self.project.assets
        self.execute(
            ProjectPatch("Register asset", {"assets": before}, {"assets": (*before, asset)})
        )
        if embed:
            self._asset_data[uri] = data
        return asset

    def register_asset_bytes(
        self,
        name: str,
        data: bytes,
        *,
        kind: Literal["raster", "vector", "audio", "sequence"] = "raster",
        media_type: str = "application/octet-stream",
        metadata: Mapping[str, Any] | None = None,
    ) -> Asset:
        """Register already-read immutable source bytes as an undoable portable embedded asset."""
        if self.project is None:
            raise ProjectError("Create or open a project before importing artwork.")
        if type(data) is not bytes or len(data) > MAX_ASSET_SIZE:
            raise ProjectError("Asset data must be bytes within the 32 MiB source limit.")
        used = sum(
            len(self._asset_data.get(asset.source, b""))
            for asset in self.project.assets
            if asset.storage == "embedded"
        )
        if used + len(data) > 96 * 1024 * 1024:
            raise ProjectError("Embedded project sources exceed the 96 MiB import budget.")
        key = str(uuid4())
        filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name).lstrip(".") or "asset.bin"
        asset = Asset(
            id=key,
            name=(Path(name).name or "Artwork")[:200],
            source=f"assets/{key}/{filename}",
            storage="embedded",
            media_type=media_type,
            sha256=hashlib.sha256(data).hexdigest(),
            kind=kind,
            extra=metadata or {},
        )
        self.execute(
            ProjectPatch(
                "Import embedded artwork",
                {"assets": self.project.assets},
                {"assets": (*self.project.assets, asset)},
            )
        )
        self._asset_data[asset.source] = data
        return asset

    def embed_external_assets(self) -> None:
        """Convert linked sources into an undoable portable asset collection."""
        if self.project is None:
            raise ProjectError("Create or open a project first.")
        assets = []
        contents: dict[str, bytes] = {}
        for asset in self.project.assets:
            if asset.storage == "external":
                data = self.read_asset(asset.id)
                filename = re.sub(r"[^A-Za-z0-9._-]", "_", Path(asset.source).name)
                uri = f"assets/{asset.id}/{filename}"
                asset = replace(
                    asset, storage="embedded", source=uri, sha256=hashlib.sha256(data).hexdigest()
                )
                contents[uri] = data
            assets.append(asset)
        before = self.project.assets
        self.execute(
            ProjectPatch("Embed linked assets", {"assets": before}, {"assets": tuple(assets)})
        )
        self._asset_data.update(contents)
        self._refresh_asset_warnings()

    def _refresh_asset_warnings(self) -> None:
        """Collect missing-source diagnostics without preventing a valid project from opening."""
        warnings = []
        if self.project is not None:
            for asset in self.project.assets:
                try:
                    self.read_asset(asset.id)
                except ProjectError as error:
                    warnings.append(str(error))
        self.warnings = tuple(warnings)
