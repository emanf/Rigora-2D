"""Canonical automation operations shared by local Python, CLI and bounded MCP adapters."""

import hashlib
import inspect
import json
import threading
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, get_args, get_origin, get_type_hints

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.bindings import BindingService
from rigora.application_services.cameras import CameraService
from rigora.application_services.content_library import ContentLibrary, ContentService
from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.application_services.facial import FaceService, waveform
from rigora.application_services.meshes import MeshService
from rigora.application_services.output import (
    FORMAT_NOTES,
    FORMATS,
    VIDEO_OPTIONS,
    Exporter,
    OutputService,
    OutputSettings,
)
from rigora.application_services.plugins import PluginManager
from rigora.application_services.render_queue import RenderQueue
from rigora.application_services.retargeting import RetargetService, suggest_mapping
from rigora.application_services.rigging import RigService
from rigora.application_services.rigging_guide import RiggingGuideService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.application_services.skinning import SkinService
from rigora.domain.entities import Record, SceneObject, Transform, nested_records
from rigora.domain.mesh_geometry import normalize_weights
from rigora.domain.project import ProjectError, Scene, SceneSettings
from rigora.domain.validation import json_copy, portable_relative_path
from rigora.infrastructure.content_packs import read_pack
from rigora.infrastructure.preferences import PreferencesStore
from rigora.infrastructure.project_storage import _atomic_bytes
from rigora.resources import asset_path

API_VERSION = "1"
OPERATIONS = (
    "project_create",
    "project_open",
    "project_inspect",
    "project_validate",
    "project_save",
    "asset_import",
    "asset_replace",
    "assets_import",
    "video_rig_import",
    "media_rig_import",
    "sequence_import",
    "sequence_place",
    "spritesheet_import",
    "layered_import",
    "layered_place",
    "audio_import",
    "audio_attach",
    "audio_detach",
    "audio_tracks",
    "audio_track_edit",
    "audio_track_remove",
    "event_set",
    "motion_layer_edit",
    "path_motion",
    "path_artwork",
    "game_region_edit",
    "particle_emitter_edit",
    "camera_shots",
    "camera_shot_edit",
    "camera_follow",
    "state_machine_define",
    "state_machine_sample",
    "export_preflight",
    "asset_pack_install",
    "object_create",
    "object_edit",
    "object_library_list",
    "object_library_save",
    "object_library_place",
    "authoring_copy",
    "authoring_paste",
    "scene_create",
    "scene_select",
    "scene_delete",
    "camera_list",
    "camera_create",
    "camera_edit",
    "camera_activate",
    "camera_delete",
    "character_create",
    "rig_create",
    "mesh_create",
    "weights_assign",
    "template_apply",
    "pose_apply",
    "motion_apply",
    "clip_create",
    "clip_edit",
    "keyframe_set",
    "deformer_apply",
    "timeline_inspect",
    "frame_evaluate",
    "frame_render",
    "render_submit",
    "render_status",
    "render_cancel",
    "output_formats",
    "project_export",
    "library_list",
    "plugin_list",
    "diagnostics",
    "motion_retarget",
    "face_create",
    "face_controls",
    "lip_sync_set",
    "audio_waveform",
    "speech_analyze",
    "face_enable_character",
    "tracking_apply",
    "dynamics_configure",
    "dynamics_bake",
    "bounce_apply",
    "squash_apply",
    "character_parts_import",
    "character_rig_generate",
    "character_mesh_generate",
    "character_bind",
    "bindings_inspect",
    "binding_create",
    "binding_remove",
    "scene_attachments_inspect",
    "scene_attach",
    "scene_detach",
    "attachment_point_save",
    "attachment_point_remove",
    "character_template_save",
    "undo",
    "redo",
)


def validate_argument(value: Any, hint: Any) -> bool:
    """Apply strict JSON argument types without requiring the optional MCP/Pydantic dependency."""
    origin, args = get_origin(hint), get_args(hint)
    if hint is Any:
        return True
    if origin is types.UnionType:
        return any(validate_argument(value, item) for item in args)
    if origin is Literal:
        return any(type(value) is type(item) and value == item for item in args)
    if origin is list:
        return isinstance(value, list) and all(validate_argument(item, args[0]) for item in value)
    if origin is dict:
        return isinstance(value, dict) and all(
            validate_argument(k, args[0]) and validate_argument(v, args[1])
            for k, v in value.items()
        )
    if hint is float:
        return type(value) in (int, float)
    return type(value) is hint


class AutomationError(ProjectError):
    """Structured, actionable adapter error without internal exception traces or
    environment data.
    """

    def __init__(self, code: str, message: str) -> None:
        """Retain a stable machine code alongside a concise caller-facing explanation."""
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OperationResult:
    """JSON-compatible operation outcome with persistent IDs, warnings and undo availability."""

    operation: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    dry_run: bool = False
    can_undo: bool = False
    revision: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return an owned JSON-compatible structure for CLI and MCP serialization."""
        return asdict(self)


class RigoraAPI:
    """Own an automation session over the same document and editing services as the desktop.

    Inputs resolve inside the workspace or explicitly authorized read-only asset roots.
    Outputs stay inside the workspace. Calls are serialized; no executable plugins are
    activated by automation. Host-provided document sessions retain ordinary undo history.
    """

    def __init__(
        self,
        root: Path,
        *,
        asset_roots: tuple[Path, ...] = (),
        document: DocumentService | None = None,
        allow_overwrite: bool = True,
        progress: Callable[[int, int], None] | None = None,
        encoder: Path | None = None,
        speech_analyzer: Path | None = None,
        exporters: dict[str, Exporter] | None = None,
    ) -> None:
        """Require an existing authorized workspace and create isolated automation preferences."""
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise AutomationError("invalid_root", "Workspace root must be an existing directory.")
        self.asset_roots = tuple(path.resolve(strict=True) for path in asset_roots)
        if any(not path.is_dir() for path in self.asset_roots):
            raise AutomationError("invalid_root", "Asset roots must be existing directories.")
        self.document = document or DocumentService()
        self.allow_overwrite, self.progress = allow_overwrite, progress
        self.lock = threading.RLock()
        self.library = ContentLibrary(
            PreferencesStore(self.root / ".rigora-automation" / "preferences.json"),
            allowed_roots=(
                self.root,
                *self.asset_roots,
                asset_path("shapes/bone.svg").parents[1],
            ),
        )
        self._dry_run = False
        self.encoder = encoder.resolve(strict=True) if encoder is not None else None
        self.speech_analyzer = (
            speech_analyzer.resolve(strict=True) if speech_analyzer is not None else None
        )
        self.exporters = dict(exporters or {})
        self.render_queue: RenderQueue | None = None

    def path(self, value: str, *, output: bool = False, approve_overwrite: bool = False) -> Path:
        """Resolve symlinks/junctions before checking authorized roots and overwrite approval."""
        if not isinstance(value, str) or not value or "\x00" in value:
            raise AutomationError("invalid_path", "Provide a nonempty workspace-relative path.")
        candidate = Path(value)
        path = (candidate if candidate.is_absolute() else self.root / candidate).resolve()
        roots = (
            (self.root,)
            if output
            else (self.root, *self.asset_roots, asset_path("shapes/bone.svg").parents[1])
        )
        if not any(path.is_relative_to(root) for root in roots):
            raise AutomationError(
                "path_outside_root",
                "Path is outside the authorized workspace or asset directories.",
            )
        if output:
            portable_relative_path(self.relative(path))
            if path.exists() and (not approve_overwrite or not self.allow_overwrite):
                raise AutomationError(
                    "approval_required",
                    "Overwriting a file requires explicit approval and host permission.",
                )
            if path.exists() and not path.is_file():
                raise AutomationError("invalid_path", "Output destination must be a file.")
        elif not path.is_file():
            raise AutomationError("not_found", "The authorized input file does not exist.")
        return path

    def relative(self, path: Path) -> str:
        """Describe outputs without exposing unrelated local environment paths."""
        return path.relative_to(self.root).as_posix()

    def revision(self) -> str:
        """Hash immutable authored state for optional optimistic concurrency checks."""
        data = self.document.project.to_dict() if self.document.project else None
        return hashlib.sha256(
            json.dumps(data, sort_keys=True, allow_nan=False).encode()
        ).hexdigest()

    def execute(
        self,
        operation: str,
        arguments: dict[str, Any] | None = None,
        *,
        dry_run: bool = False,
        expected_revision: str | None = None,
    ) -> OperationResult:
        """Validate one task operation and return structured results; dry runs use an
        asset-owning fork.
        """
        if (
            type(dry_run) is not bool
            or expected_revision is not None
            and not isinstance(expected_revision, str)
        ):
            raise AutomationError(
                "invalid_arguments", "Dry run and revision options have invalid types."
            )
        if operation not in OPERATIONS:
            raise AutomationError(
                "unknown_operation",
                "Unknown operation; use diagnostics to list supported operations.",
            )
        with self.lock:
            if expected_revision is not None and expected_revision != self.revision():
                raise AutomationError(
                    "revision_conflict",
                    "Project revision changed; inspect the project before retrying.",
                )
            if dry_run:
                scratch = RigoraAPI(
                    self.root,
                    asset_roots=self.asset_roots,
                    document=self.document.fork(),
                    allow_overwrite=self.allow_overwrite,
                    encoder=self.encoder,
                    speech_analyzer=self.speech_analyzer,
                    exporters=self.exporters,
                )
                scratch._dry_run = True
                scratch.library.additional_packs = self.library.additional_packs
                if operation in ("render_status", "render_cancel"):
                    scratch.render_queue = self.render_queue
                result = scratch.execute(operation, arguments)
                return replace(result, dry_run=True, can_undo=self.document.can_undo)
            method = getattr(self, operation)
            try:
                if arguments is not None and not isinstance(arguments, dict):
                    raise ValueError("Operation arguments must be a JSON object.")
                args = json_copy(arguments if arguments is not None else {})
                inspect.signature(method).bind(**args)
                if len(json.dumps(args, allow_nan=False)) > 1024 * 1024:
                    raise ValueError("Arguments exceed the 1 MiB size limit.")
                hints = get_type_hints(method)
                for key, value in args.items():
                    if not validate_argument(value, hints[key]):
                        raise ValueError(f"Invalid argument type or value for {key}.")
            except (ProjectError, TypeError, ValueError) as error:
                raise AutomationError("invalid_arguments", str(error)) from None
            try:
                data = method(**args)
                warnings = tuple(self.document.warnings)
                return OperationResult(
                    operation,
                    data,
                    warnings,
                    self._dry_run,
                    self.document.can_undo,
                    self.revision(),
                )
            except AutomationError:
                raise
            except (ProjectError, ValueError, TypeError, KeyError, IndexError) as error:
                raise AutomationError("validation_error", str(error)) from None
            except OSError:
                raise AutomationError(
                    "io_error",
                    "Cannot access the authorized input or output; check its permissions.",
                ) from None

    @contextmanager
    def transaction(self, label: str = "Automation transaction") -> Iterator[None]:
        """Group in-memory edits into one undo item; persistence and rendering are
        separate effects.
        """
        with self.lock, self.document.command_group(label):
            yield

    def motion_retarget(
        self,
        source_clip: str,
        source_skeleton: str,
        target_skeleton: str,
        profile: str = "Human",
        mapping: dict[str, str] | None = None,
        rotation_offsets: dict[str, float] | None = None,
        rotation_gains: dict[str, float] | None = None,
        root_scale: float | None = None,
        source_path: str = "",
    ) -> dict[str, Any]:
        """Transfer evaluated motion from this project or an authorized local source archive."""
        source = self.document
        if source_path:
            source = self.document.fork()
            source.open(self.path(source_path))
        if source.project is None:
            raise ProjectError("Open a source project first.")
        src = next((r for r in source.scene.skeletons if r.id == source_skeleton), None)
        dst = next(
            (r for r in MeshService(self.document).scene.skeletons if r.id == target_skeleton), None
        )
        if src is None or dst is None:
            raise ProjectError("Choose existing source and target skeletons.")
        result = RetargetService(self.document).apply(
            source,
            source_clip,
            source_skeleton,
            target_skeleton,
            mapping if mapping is not None else suggest_mapping(src, dst, profile),
            profile=profile,
            rotation_offsets=rotation_offsets,
            rotation_gains=rotation_gains,
            root_scale=root_scale,
        )
        return asdict(result)

    def face_create(
        self, parent_bone: str | None = None, x: float = 600, y: float = 350
    ) -> dict[str, Any]:
        """Create original replaceable vector facial parts with an optional head-bone anchor."""
        return {"face_id": FaceService(self.document).create(parent_bone=parent_bone, x=x, y=y)}

    def face_enable_character(self, object_id: str) -> dict[str, Any]:
        """Upgrade an older creator character to separate bound visemes without replacing it."""
        return {"face_id": FaceService(self.document).enable_character(object_id)}

    def tracking_apply(
        self,
        target_id: str,
        samples: list[dict[str, Any]],
        start: float | None = None,
        smoothing: float = 0.35,
    ) -> dict[str, Any]:
        """Convert bounded local detector observations into keys without accessing hardware."""
        from rigora.application_services.tracking import TrackingSample, TrackingTake
        from rigora.engine.sampling import number

        if not isinstance(samples, list) or not 1 <= len(samples) <= 600:
            raise ProjectError("Supply one to 600 timestamped tracking samples.")
        observations = [TrackingSample(**value) for value in samples]
        scratch = self.document.fork()
        if start is not None:
            if number(start) < 0:
                raise ProjectError("Tracking start must be nonnegative.")
            scratch.animation.seek(start)
        take = TrackingTake(scratch, target_id, smoothing)
        if start is not None:
            take.start = number(start)
        take.recording, take.record_start = True, observations[0].seconds
        for sample in observations:
            take.feed(sample, preview=False)
        self.document.execute(take.recorded_command())
        return {
            "target_id": target_id,
            "samples": len(take.frames),
            "channels": len(take.values),
            "start": take.start,
        }

    def speech_analyze(
        self, asset_id: str, transcript: str = "", recognizer: str = "phonetic"
    ) -> dict[str, Any]:
        """Return draft cues from built-in speech recognition or an explicit host tool."""
        project = self.document.project
        if project is None or not any(
            a.id == asset_id and a.kind == "audio" for a in project.assets
        ):
            raise ProjectError("Choose an embedded audio source.")
        cues = FaceService.speech_cues(
            self.document.read_asset(asset_id),
            self.speech_analyzer,
            transcript=transcript,
            recognizer=recognizer,
        )
        return {
            "asset_id": asset_id,
            "cues": [{"seconds": time, "phoneme": shape} for time, shape in cues],
        }

    def face_controls(
        self,
        face_id: str,
        frame: float,
        expression: str = "Neutral",
        look_x: float = 0,
        look_y: float = 0,
        blink: float = 0,
        mouth: str | None = None,
    ) -> dict[str, Any]:
        """Key expression, gaze, blink and mouth controls as one editable animation command."""
        FaceService(self.document).controls(
            face_id,
            frame,
            expression=expression,
            look_x=look_x,
            look_y=look_y,
            blink=blink,
            mouth=mouth,
        )
        return {"face_id": face_id, "frame": frame}

    def lip_sync_set(
        self,
        face_id: str,
        cues: list[dict[str, Any]],
        start: float = 0,
        audio_asset: str | None = None,
    ) -> dict[str, Any]:
        """Key timed seconds/phoneme rows after validating the complete local cue list."""
        if any(
            set(cue) != {"seconds", "phoneme"} or not isinstance(cue["phoneme"], str)
            for cue in cues
        ):
            raise ProjectError("Each cue requires seconds and a phoneme string.")
        FaceService(self.document).lip_sync(
            face_id,
            ((cue["seconds"], cue["phoneme"]) for cue in cues),
            start=start,
            audio_asset=audio_asset,
        )
        return {"face_id": face_id, "cues": len(cues)}

    def audio_waveform(self, asset_id: str, bins: int = 1024) -> dict[str, Any]:
        """Inspect an embedded PCM WAV envelope without a player, model or network service."""
        duration, peaks = waveform(self.document.read_asset(asset_id), bins)
        return {"duration_seconds": duration, "peaks": peaks}

    def dynamics_configure(
        self,
        bones: list[str],
        frequency: float = 3,
        damping: float = 0.5,
        inertia: float = 0.6,
        gravity: float = 0,
        strength: float = 1,
        max_angle: float = 65,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Configure validated anchored child-bone springs through the shared dynamics service."""
        keys = DynamicsService(self.document).configure(
            tuple(bones),
            frequency=frequency,
            damping=damping,
            inertia=inertia,
            gravity=gravity,
            strength=strength,
            max_angle=max_angle,
            enabled=enabled,
        )
        return {"constraint_ids": keys}

    def dynamics_bake(self) -> dict[str, Any]:
        """Bake the selected motion into a separate deterministic editable FK clip."""
        return {"clip_id": DynamicsService(self.document).bake()}

    def bounce_apply(
        self,
        owner: str,
        preset: str = "Soft bounce",
        start: float = 0,
        duration: float = 48,
        height: float = 100,
    ) -> dict[str, Any]:
        """Create an original decaying bounce clip with editable transform and impact keys."""
        service = DynamicsService(self.document)
        service.bounce(owner, preset=preset, start=start, duration=duration, height=height)
        assert service.clip is not None
        return {"clip_id": service.clip.id}

    def squash_apply(
        self, owner: str, frame: float, amount: float = 0.25, duration: float = 8
    ) -> dict[str, Any]:
        """Key area-preserving scale samples around the control's evaluated pose."""
        DynamicsService(self.document).squash(owner, frame, amount, duration)
        return {"owner_id": owner}

    def character_parts_import(self, paths: list[str]) -> dict[str, Any]:
        """Import an editable multipart character with one reversible command."""
        keys = RiggingGuideService(self.document).import_parts(
            tuple(self.path(path) for path in paths)
        )
        return {"mesh_ids": keys}

    def character_rig_generate(
        self, template: str, meshes: list[str], scale: float = 1
    ) -> dict[str, Any]:
        """Generate a human, animal, winged or flexible rig fitted to the selected artwork."""
        return {
            "rig_id": RiggingGuideService(self.document).generate_rig(
                template, tuple(meshes), scale=scale
            )
        }

    def character_mesh_generate(
        self, meshes: list[str], columns: int = 6, rows: int = 6, replace_edits: bool = False
    ) -> dict[str, Any]:
        """Generate guide topology while requiring explicit consent to replace edited meshes."""
        RiggingGuideService(self.document).generate_meshes(
            tuple(meshes), columns, rows, replace_edits=replace_edits
        )
        return {"mesh_ids": meshes}

    def character_bind(
        self, rig_id: str, meshes: list[str], assignments: dict[str, str] | None = None
    ) -> dict[str, Any]:
        """Bind selected parts to all rig bones or explicit rigid part assignments."""
        RiggingGuideService(self.document).bind_parts(rig_id, tuple(meshes), assignments)
        return {"rig_id": rig_id, "mesh_ids": meshes}

    def bindings_inspect(self) -> dict[str, Any]:
        """List stable removable relationship IDs across the current scene."""
        return {"bindings": [asdict(row) for row in BindingService(self.document).relationships()]}

    def binding_create(
        self, sources: list[str], target: str, rigid: bool = False
    ) -> dict[str, Any]:
        """Bind artwork or bones through the same validated transaction as the desktop."""
        BindingService(self.document).bind(tuple(sources), target, rigid=rigid)
        return self.bindings_inspect()

    def binding_remove(
        self, sources: list[str] | None = None, relationships: list[str] | None = None
    ) -> dict[str, Any]:
        """Unbind selected endpoints or precise inspected rows, including physics cleanup."""
        if bool(sources) == bool(relationships):
            raise ProjectError("Specify sources or relationship IDs to unbind.")
        service = BindingService(self.document)
        if sources:
            service.unbind(tuple(sources))
        else:
            service.remove_relationships(tuple(relationships or ()))
        return self.bindings_inspect()

    def scene_attachments_inspect(self) -> dict[str, Any]:
        """Inspect placed attachment states and their reusable point choices at the playhead."""
        from rigora.application_services.scene_attachments import SceneAttachmentService

        service = SceneAttachmentService(self.document)
        owners = service.document.animation.evaluator.scene_followers.defaults
        return {
            "attachments": [
                {
                    "owner": owner,
                    "state": service.state(owner).to_dict(),
                    "label": service.target_label(service.state(owner)),
                }
                for owner in owners
            ]
        }

    def scene_attach(
        self,
        sources: list[str],
        target: str,
        *,
        point: str = "",
        source_point: str = "",
        snap: bool = False,
        frame: float | None = None,
        inherit_rotation: bool = True,
        inherit_scale: bool = True,
    ) -> dict[str, Any]:
        """Attach placed Objects without changing skinning; frame creates a pickup key."""
        from rigora.application_services.scene_attachments import SceneAttachmentService

        SceneAttachmentService(self.document).attach(
            tuple(sources),
            target,
            point=point,
            source_point=source_point,
            snap=snap,
            frame=frame,
            inherit_rotation=inherit_rotation,
            inherit_scale=inherit_scale,
        )
        return self.scene_attachments_inspect()

    def scene_detach(self, sources: list[str], frame: float | None = None) -> dict[str, Any]:
        """Release only Scene links while keeping evaluated placement, rigs and physics."""
        from rigora.application_services.scene_attachments import SceneAttachmentService

        SceneAttachmentService(self.document).detach(tuple(sources), frame=frame)
        return self.scene_attachments_inspect()

    def attachment_point_save(
        self,
        owner: str,
        name: str,
        *,
        x: float = 0,
        y: float = 0,
        rotation: float = 0,
        identity: str = "",
        view: str = "",
    ) -> dict[str, Any]:
        """Create or update a reusable local grip with optional Object-view registration."""
        from rigora.application_services.scene_attachments import SceneAttachmentService

        service = SceneAttachmentService(self.document)
        key = service.add_point(
            owner, name, x=x, y=y, rotation=rotation, identity=identity, view=view
        )
        return {"point_id": key, "points": list(service.point_choices(owner))}

    def attachment_point_remove(self, owner: str, identity: str) -> dict[str, Any]:
        """Remove an unused local grip; references in setup or keys protect points in use."""
        from rigora.application_services.scene_attachments import SceneAttachmentService

        SceneAttachmentService(self.document).remove_point(owner, identity)
        return {"removed": identity}

    def character_template_save(
        self,
        path: str,
        name: str = "My character",
        author: str = "",
        license: str = "All rights reserved",
        approve_overwrite: bool = False,
    ) -> dict[str, Any]:
        """Save an authorized portable scene template without writing during dry runs."""
        output = self.path(path, output=True, approve_overwrite=approve_overwrite)
        if output.suffix.lower() != ".rigpack":
            raise ProjectError("Character templates must end in .rigpack.")
        self.project_validate()
        if not self._dry_run:
            RiggingGuideService(self.document).share(
                output, name=name, author=author, license=license, overwrite=approve_overwrite
            )
        return {"path": self.relative(output), "planned": self._dry_run}

    def project_create(
        self, name: str = "Untitled project", width: int = 1920, height: int = 1080, fps: int = 24
    ) -> dict[str, Any]:
        """Create an empty project; existing unsaved state requires an explicit separate session."""
        if self.document.project is not None:
            raise AutomationError(
                "session_not_empty", "Open a separate session before replacing an active project."
            )
        self.document.new(name, SceneSettings(width=width, height=height, fps=fps))
        return self.project_inspect()

    def project_open(self, path: str) -> dict[str, Any]:
        """Open a validated project inside an authorized directory without discarding
        dirty state.
        """
        if self.document.dirty:
            raise AutomationError(
                "unsaved_changes", "Save or use a separate session before opening another project."
            )
        self.document.open(self.path(path))
        return self.project_inspect()

    def project_inspect(self, kind: str = "summary") -> dict[str, Any]:
        """Inspect stable scene/entity IDs; full authored data requires an explicit
        detail request.
        """
        project = self.document.project
        if project is None:
            raise ProjectError("Create or open a project first.")
        scene = self.document.scene
        if kind == "full":
            return project.to_dict()
        groups: dict[str, tuple[Record | Scene, ...]] = {
            "scenes": project.scenes,
            "bones": tuple(b for r in scene.skeletons for b in r.bones),
            "clips": scene.clips,
            "objects": scene.objects,
            "meshes": scene.meshes,
            "rigs": scene.skeletons,
            "assets": project.assets,
        }
        if kind != "summary":
            if kind not in groups:
                raise ProjectError(
                    "Inspection kind must be summary, full, scenes, bones, clips, "
                    "objects, meshes, rigs or assets."
                )
            return {"items": [record.to_dict() for record in groups[kind]]}
        return {
            "project_id": project.id,
            "name": project.name,
            "scene_id": scene.id,
            "counts": {key: len(value) for key, value in groups.items()},
            "dirty": self.document.dirty,
            "rigs": [{"id": r.id, "name": r.name} for r in scene.skeletons],
            "meshes": [
                {"id": m.id, "name": m.name, "object_id": m.object_id} for m in scene.meshes
            ],
        }

    def project_validate(self) -> dict[str, Any]:
        """Validate authored records and evaluate the current frame through the canonical engine."""
        self.project_inspect()
        pose = self.document.animation.pose
        warnings = [*self.document.warnings, *pose.warnings]
        assert self.document.project is not None
        return {"valid": not warnings, "warnings": warnings, "project_id": self.document.project.id}

    def project_save(self, path: str, approve_overwrite: bool = False) -> dict[str, Any]:
        """Atomically save a project; overwrite approval is required even for an existing
        open file.
        """
        output = self.path(path, output=True, approve_overwrite=approve_overwrite)
        if output.suffix.lower() != ".rigora":
            raise ProjectError("Project filenames must end in .rigora.")
        self.project_validate()
        if not self._dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
            self.document.save(output, overwrite=approve_overwrite)
        return {"path": self.relative(output), "planned": self._dry_run}

    def asset_import(self, path: str, place: bool = False) -> dict[str, Any]:
        """Register original image bytes and optionally create an independent mesh instance."""
        source = self.path(path)
        if source.stat().st_size > 16 * 1024 * 1024:
            raise ProjectError("Artwork import exceeds the 16 MiB input limit.")
        return AssetPipeline(self.document).image(source, place=place)

    def video_rig_import(
        self,
        path: str,
        models: str,
        profile: str = "Auto",
        start: float = 0,
        duration: float = 10,
        sample_fps: float = 15,
        subject: int = 0,
        confidence: float = 0.35,
        smoothing: float = 0.25,
        cutout: bool = True,
        name: str = "Video character",
        region: list[float] | None = None,
    ) -> dict[str, Any]:
        """Convert authorized local video into an editable Object/action using installed models.

        Downloads never run implicitly. Every model path must be inside the caller's
        workspace or explicitly authorized read-only asset roots. Dry-run uses the
        ordinary isolated API transaction; it may analyze but cannot publish changes.
        """
        return self.media_rig_import(
            [path],
            models,
            profile=profile,
            start=start,
            duration=duration,
            sample_fps=sample_fps,
            subject=subject,
            confidence=confidence,
            smoothing=smoothing,
            cutout=cutout,
            name=name,
            region=region,
        )

    def media_rig_import(
        self,
        paths: list[str],
        models: str,
        profile: str = "Auto",
        start: float = 0,
        duration: float = 10,
        sample_fps: float = 15,
        subject: int = 0,
        confidence: float = 0.35,
        smoothing: float = 0.25,
        cutout: bool = True,
        name: str = "Media character",
        region: list[float] | None = None,
        key_method: str = "Auto",
        key_color: list[float] | None = None,
        key_tolerance: float = 0.1,
        key_softness: float = 0.1,
        key_despill: float = 1,
        key_balance: float = 0.5,
        key_despill_balance: float = 0.5,
        key_pre_blur: int = 0,
        key_matte_blur: int = 0,
        key_grow: int = 0,
        key_feather: int = 0,
    ) -> dict[str, Any]:
        """Convert authorized video, a still or ordered images into an editable rig.

        Image paths preserve caller order, and sample_fps sets sequence timing.
        One image creates a posed rig without an invented animation clip. Existing
        alpha is kept; opaque artwork uses the built-in CPU keyer. No external
        program, executable configuration or implicit download is involved.
        """
        from rigora.application_services.video_rig import VideoRigService
        from rigora.infrastructure.video_keying import KeyingSettings, key_cutout
        from rigora.infrastructure.video_models import MODELS
        from rigora.infrastructure.video_rig import IMAGE_EXTENSIONS, analyze_images, analyze_video

        directory = Path(models)
        resolved = [self.path(str(directory / (key + ".onnx"))) for key in MODELS]
        if not 1 <= len(paths) <= 3600:
            raise ProjectError("Choose one video, one image or up to 3600 ordered images.")
        sources = tuple(self.path(path) for path in paths)
        if region is not None and len(region) != 4:
            raise ProjectError("Subject region requires left, top, right and bottom fractions.")
        settings: dict[str, Any] = {
            "profile": profile,
            "sample_fps": sample_fps,
            "subject": subject,
            "region": (region[0], region[1], region[2], region[3]) if region else None,
        }
        if all(path.suffix.lower() in IMAGE_EXTENSIONS for path in sources):
            analysis = analyze_images(sources, resolved[0].parent, **settings)
        elif len(sources) == 1 and sources[0].suffix.lower() not in IMAGE_EXTENSIONS:
            analysis = analyze_video(
                sources[0], resolved[0].parent, start=start, duration=duration, **settings
            )
        else:
            raise ProjectError("Select one video or a sequence of supported raster images.")
        if key_color is not None and len(key_color) != 3:
            raise ProjectError("Key color requires three RGB values from 0 to 1.")
        keying = KeyingSettings(
            key_method,
            (key_color[0], key_color[1], key_color[2]) if key_color else None,
            key_tolerance,
            key_softness,
            key_despill,
            key_balance,
            key_despill_balance,
            key_pre_blur,
            key_matte_blur,
            key_grow,
            key_feather,
        )
        result = VideoRigService(self.document).create(
            analysis,
            name=name,
            confidence=confidence,
            smoothing=smoothing,
            artwork=key_cutout(analysis.image, keying) if cutout else b"",
        )
        return {**result, "warnings": list(analysis.warnings)}

    def asset_replace(self, asset_id: str, path: str) -> dict[str, Any]:
        """Replace a shared source while retaining rigs, topology and stable references."""
        from rigora.application_services.artwork_editing import ArtworkEditingService

        return ArtworkEditingService(self.document).replace_file(asset_id, self.path(path))

    def assets_import(
        self,
        paths: list[str],
        place: bool = False,
        allow_unsupported: bool = False,
        parent: str | None = None,
        before: str | None = None,
        position: list[float] | None = None,
        center: bool = False,
    ) -> dict[str, Any]:
        """Add mixed local sources in one undo step with explicit per-file results."""
        sources = tuple(self.path(path) for path in paths)
        if position is not None and len(position) != 2:
            raise ProjectError("Drop position must contain X and Y.")
        return AssetPipeline(self.document).batch(
            sources,
            place=place,
            allow_unsupported=allow_unsupported,
            parent=parent,
            before=before,
            center=center,
            position=(position[0], position[1]) if position is not None else None,
        )

    def sequence_import(
        self,
        paths: list[str],
        fps: float = 24,
        start: float = 0,
        loop: bool = True,
        place: bool = False,
    ) -> dict[str, Any]:
        """Import 1–256 explicitly ordered equal-size images with reversible sprite playback."""
        if not 1 <= len(paths) <= 256:
            raise ProjectError("Choose 1–256 image sequence paths.")
        return AssetPipeline(self.document).sequence(
            tuple(self.path(p) for p in paths), fps=fps, start=start, loop=loop, place=place
        )

    def sequence_place(self, asset_id: str) -> dict[str, Any]:
        """Place an independent instance of a previously imported sequence or sprite sheet."""
        return {"mesh_id": AssetPipeline(self.document).place_sequence(asset_id)}

    def spritesheet_import(
        self,
        path: str,
        frame_width: int,
        frame_height: int,
        fps: float = 24,
        count: int | None = None,
        margin: int = 0,
        spacing: int = 0,
        place: bool = False,
    ) -> dict[str, Any]:
        """Slice uniform row-major sprite cells while retaining the unmodified sheet source."""
        return AssetPipeline(self.document).spritesheet(
            self.path(path),
            frame_width=frame_width,
            frame_height=frame_height,
            fps=fps,
            count=count,
            margin=margin,
            spacing=spacing,
            place=place,
        )

    def layered_import(
        self, path: str, allow_unsupported: bool = False, place: bool = False
    ) -> dict[str, Any]:
        """Import ORA/basic PSD layers; approximations require explicit acknowledgement."""
        return AssetPipeline(self.document).layered(
            self.path(path),
            allow_unsupported=allow_unsupported,
            place=place,
        )

    def layered_place(self, asset_id: str) -> dict[str, Any]:
        """Place another independently editable instance of imported layered artwork."""
        return AssetPipeline(self.document).place_layered(asset_id)

    def audio_import(self, path: str) -> dict[str, Any]:
        """Preserve PCM WAV audio and timing metadata for later lip-sync authoring."""
        return AssetPipeline(self.document).audio(self.path(path))

    def audio_attach(
        self, asset_id: str, start: float = 0, gain: float = 1, muted: bool = False
    ) -> dict[str, Any]:
        """Attach an embedded WAV to the active clip with portable playback settings."""
        AudioService(self.document).attach(asset_id, start=start, gain=gain, muted=muted)
        return {"asset_id": asset_id, "start_frame": start, "gain": gain, "muted": muted}

    def audio_detach(self) -> dict[str, Any]:
        """Remove the active clip's audio association without deleting source assets."""
        AudioService(self.document).detach()
        return {"detached": True}

    def audio_tracks(self) -> dict[str, Any]:
        """Read independent audio placements using portable scene/source timing."""
        return {"tracks": list(AudioService(self.document).tracks())}

    def audio_track_edit(
        self,
        asset_id: str,
        identity: str = "",
        name: str = "Audio",
        start: float = 0,
        trim_start: float = 0,
        trim_end: float | None = None,
        gain: float = 1,
        fade_in: float = 0,
        fade_out: float = 0,
        muted: bool = False,
        solo: bool = False,
        rate: float = 1,
        loop_frames: float = 0,
        end_frame: float | None = None,
        source_offset: float = 0,
        loop_start_frame: float | None = None,
    ) -> dict[str, Any]:
        """Create/edit a bounded PCM placement with trims, envelopes and mixer state."""
        return {
            "track_id": AudioService(self.document).put_track(
                asset_id,
                identity=identity,
                name=name,
                start=start,
                trim_start=trim_start,
                trim_end=trim_end,
                gain=gain,
                fade_in=fade_in,
                fade_out=fade_out,
                muted=muted,
                solo=solo,
                rate=rate,
                loop_frames=loop_frames,
                end_frame=end_frame,
                source_offset=source_offset,
                loop_start_frame=loop_start_frame,
            )
        }

    def audio_track_remove(self, identity: str) -> dict[str, Any]:
        """Remove one placement while retaining its reusable source."""
        AudioService(self.document).remove_track(identity)
        return {"removed": identity}

    def event_set(
        self,
        name: str,
        frame: float,
        event_type: str = "custom",
        payload: dict[str, Any] | None = None,
        identity: str = "",
        delete: bool = False,
    ) -> dict[str, Any]:
        """Author typed, non-executable game events on the current clip timeline."""
        AnimationEditingService(self.document).marker(
            name, frame, key=identity, delete=delete, event_type=event_type, payload=payload
        )
        return {
            "events": [
                e.to_dict(fps=self.document.scene.settings.fps)
                for e in self.document.animation.runtime_events
            ]
        }

    def motion_layer_edit(
        self,
        identity: str,
        layer: int = 0,
        weight: float = 1,
        blend: str = "override",
        fade_in: float = 0,
        fade_out: float = 0,
        mask: list[str] | None = None,
        muted: bool = False,
        solo: bool = False,
    ) -> dict[str, Any]:
        """Edit live arranged-action layer settings through the same authoring service."""
        from rigora.application_services.characters import CharacterService

        CharacterService(self.document).edit_segment(
            identity,
            layer=layer,
            weight=weight,
            blend=blend,
            fade_in=fade_in,
            fade_out=fade_out,
            mask=mask or [],
            muted=muted,
            solo=solo,
        )
        return {"segment_id": identity}

    def path_motion(
        self,
        owner: str,
        points: list[list[float]],
        start: float,
        end: float,
        orient: bool = False,
        space: str = "world",
    ) -> dict[str, Any]:
        """Create/edit an original cubic Object/camera path and its progress keys."""
        from rigora.application_services.path_editing import PathEditingService

        return {
            "constraint_id": PathEditingService(self.document).motion(
                owner, points, start, end, orient=orient, space=space
            )
        }

    def path_artwork(
        self,
        points: list[list[float]],
        mesh_id: str = "",
        closed: bool = False,
        fill: str = "#bcbcbc",
        stroke: str = "#ffffff",
        width: float = 512,
        height: float = 512,
    ) -> dict[str, Any]:
        """Create/edit original cubic SVG artwork while retaining mesh/asset identity."""
        from rigora.application_services.path_editing import PathEditingService

        return {
            "mesh_id": PathEditingService(self.document).artwork(
                points,
                mesh_id=mesh_id,
                closed=closed,
                fill=fill,
                stroke=stroke,
                width=width,
                height=height,
            )
        }

    def game_region_edit(
        self,
        identity: str = "",
        name: str = "Hitbox",
        kind: str = "hitbox",
        shape: str = "rectangle",
        width: float = 100,
        height: float = 100,
        x: float | None = None,
        y: float | None = None,
        parent: str | None = None,
        group: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Author reversible hit/hurt geometry animated by ordinary scene channels."""
        from rigora.application_services.game_authoring import GameAuthoringService

        return {
            "object_id": GameAuthoringService(self.document).region(
                identity=identity,
                name=name,
                kind=kind,
                shape=shape,
                width=width,
                height=height,
                x=x,
                y=y,
                parent=parent,
                group=group,
                payload=payload,
            )
        }

    def particle_emitter_edit(
        self,
        identity: str = "",
        name: str = "Particles",
        x: float | None = None,
        y: float | None = None,
        parent: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Author a bounded deterministic world/local-space vector particle emitter."""
        from rigora.application_services.game_authoring import GameAuthoringService

        return {
            "object_id": GameAuthoringService(self.document).emitter(
                identity=identity, name=name, x=x, y=y, parent=parent, settings=settings
            )
        }

    def camera_shots(self) -> dict[str, Any]:
        """Read chronological camera cut boundaries in the current scene action."""
        from rigora.application_services.camera_shots import CameraShotService

        return {"shots": list(CameraShotService(self.document).shots())}

    def camera_shot_edit(
        self,
        camera: str,
        frame: float,
        duration: float = 0,
        easing: str = "smooth",
        delete: bool = False,
    ) -> dict[str, Any]:
        """Author/remove a real camera cut and optional continuous framing transition."""
        from rigora.application_services.camera_shots import CameraShotService

        service = CameraShotService(self.document)
        if delete:
            service.remove_shot(frame)
        else:
            service.shot(camera, frame, duration=duration, easing=easing)
        return {"shots": list(service.shots())}

    def camera_follow(
        self, camera: str, target: str = "", offset_x: float = 0, offset_y: float = 0
    ) -> dict[str, Any]:
        """Set/remove pivot-centered following through canonical camera constraints."""
        from rigora.application_services.camera_shots import CameraShotService

        CameraShotService(self.document).follow(
            camera, target, offset_x=offset_x, offset_y=offset_y
        )
        return {"camera_id": camera}

    def state_machine_define(
        self,
        owner: str,
        states: list[dict[str, Any]],
        transitions: list[dict[str, Any]],
        parameters: dict[str, Any],
        initial: str,
    ) -> dict[str, Any]:
        """Save a bounded Object-owned state machine using existing source actions."""
        from rigora.application_services.state_machines import StateMachineService

        StateMachineService(self.document).define(owner, states, transitions, parameters, initial)
        return {"owner_id": owner}

    def state_machine_sample(
        self, owner: str, parameters: dict[str, Any] | None = None, seconds: float = 0
    ) -> dict[str, Any]:
        """Sample runtime inputs on a fresh state preview without authoring edits."""
        from rigora.application_services.state_machines import StateMachinePreview

        preview = StateMachinePreview(self.document, owner)
        for key, value in (parameters or {}).items():
            preview.set_parameter(key, value)
        pose = preview.advance(seconds)
        return {"state": preview.current, "pose": pose.to_dict()}

    def asset_pack_install(self, path: str) -> dict[str, Any]:
        """Validate and install an offline pack without execution or existing-pack replacement."""
        source = self.path(path)
        pack, _ = read_pack(source)
        self.path(str(self.library.root / f"{pack.id}.rigpack"), output=True)
        if self._dry_run:
            self.library.additional_packs = (*self.library.additional_packs, source)
        else:
            self.library.install(source)
        return {"pack_id": pack.id, "name": pack.name, "item_count": len(pack.items)}

    def object_create(
        self, name: str = "Object", x: float = 0, y: float = 0, parent_id: str | None = None
    ) -> dict[str, Any]:
        """Create a validated scene object with a stable ID and ordinary undo ownership."""
        scene = MeshService(self.document).scene
        obj = SceneObject(name=name, parent_id=parent_id, transform=Transform(x=x, y=y))
        self.document.add_entities(scene.id, {"objects": (obj,)})
        return {"object_id": obj.id}

    def object_library_list(self) -> dict[str, Any]:
        """List project-local reusable definitions without loading animation runtimes."""
        from rigora.application_services.object_library import ObjectLibraryService

        return {
            "objects": [
                {"id": key, "name": value["name"]}
                for key, value in ObjectLibraryService(self.document).entries().items()
            ]
        }

    def object_library_save(self, object_ids: list[str]) -> dict[str, Any]:
        """Publish existing scene Objects through the same linked library as the desktop."""
        from rigora.application_services.object_library import ObjectLibraryService

        return {"definition_ids": ObjectLibraryService(self.document).save(tuple(object_ids))}

    def object_library_place(
        self, definition_id: str, x: float | None = None, y: float | None = None
    ) -> dict[str, Any]:
        """Place a linked Object at a scene point, defaulting to the camera center."""
        from rigora.application_services.object_library import ObjectLibraryService

        if (x is None) != (y is None):
            raise ProjectError("Placement needs both x and y.")
        return {
            "object_id": ObjectLibraryService(self.document).place(
                definition_id, (x, y) if x is not None and y is not None else None
            )
        }

    def authoring_copy(
        self, scene_id: str | None = None, object_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Return portable project-local clipboard data without using an OS clipboard."""
        from rigora.application_services.object_library import ObjectLibraryService

        service = ObjectLibraryService(self.document)
        return (
            service.copy_scene(scene_id)
            if scene_id
            else service.copy_objects(tuple(object_ids or ()))
        )

    def authoring_paste(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Paste copied Objects or a whole scene with fresh IDs and ordinary Undo."""
        from rigora.application_services.object_library import ObjectLibraryService

        return {"ids": ObjectLibraryService(self.document).paste(payload)}

    def scene_create(self, name: str = "") -> dict[str, Any]:
        """Add a scene without activating or compiling it."""
        return {"scene_id": self.document.add_scene(name)}

    def scene_select(self, scene_id: str) -> dict[str, Any]:
        """Activate one scene and release the previous animation runtime."""
        self.document.select_scene(scene_id)
        return {"scene_id": scene_id}

    def scene_delete(self, scene_id: str) -> dict[str, Any]:
        """Delete a complete scene through reversible shared document commands."""
        self.document.delete_scene(scene_id)
        return {"deleted": scene_id}

    def camera_list(self) -> dict[str, Any]:
        """Inspect camera settings and the active evaluated output view."""
        service = CameraService(self.document)
        current = service.current()
        return {
            "cameras": [c.to_dict() for c in service.scene.cameras],
            "active_camera_id": current.id if current else None,
        }

    def camera_create(self, name: str = "") -> dict[str, Any]:
        """Add an orthographic scene camera through the shared reversible service."""
        return {"camera_id": CameraService(self.document).add(name)}

    def camera_edit(self, camera_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        """Validate camera dimensions, background or transform data before committing."""
        values = dict(settings)
        if "transform" in values:
            values["transform"] = Transform.from_dict(values["transform"])
        CameraService(self.document).update(camera_id, **values)
        return {"camera_id": camera_id}

    def camera_activate(self, camera_id: str, frame: float | None = None) -> dict[str, Any]:
        """Choose the default output camera, or record a stepped cut at a frame."""
        CameraService(self.document).activate(camera_id, frame=frame)
        return {"camera_id": camera_id, "frame": frame}

    def camera_delete(self, camera_id: str) -> dict[str, Any]:
        """Remove a scene camera and its dependent animation through ordinary Undo."""
        CameraService(self.document).camera(camera_id)
        SceneEditingService(self.document).delete_entries((camera_id,))
        return {"deleted": camera_id}

    def object_edit(
        self,
        object_id: str,
        transform: dict[str, float] | None = None,
        visible: bool | None = None,
        locked: bool | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Edit a selected object through the same transform, visibility and lock
        services as GUI.
        """
        service = SceneEditingService(self.document)
        with self.transaction("Edit scene object"):
            if transform:
                service.set_transform(object_id, **transform)
            if visible is not None or locked is not None:
                service.flags((object_id,), visible=visible, locked=locked)
            if name is not None:
                service.rename(object_id, name)
        return {"object_id": object_id}

    def _content(self, content: str) -> Any:
        """Resolve exactly one discovered immutable item by UUID, namespaced key or exact name."""
        entries = [
            entry
            for entry in self.library.entries()
            if content in (entry.key, entry.item.id, entry.item.name)
        ]
        if len(entries) != 1:
            raise ProjectError("Choose one unique content name or stable ID from library_list.")
        return entries[0]

    def template_apply(
        self,
        content: str,
        target_id: str = "",
        mesh_id: str = "",
        x: float | None = None,
        y: float | None = None,
    ) -> dict[str, Any]:
        """Apply a discovered template through canonical content placement with fresh identities."""
        entry = self._content(content)
        _, files = read_pack(entry.path)
        before = {r.id for r in nested_records(MeshService(self.document).scene)}
        if (x is None) != (y is None):
            raise ProjectError("Supply both placement coordinates or neither.")
        key = ContentService(self.document).place(
            entry.item,
            files,
            target=target_id,
            mesh_id=mesh_id,
            position=(x, y) if x is not None and y is not None else None,
        )
        scene = MeshService(self.document).scene
        return {
            "id": key,
            "kind": entry.item.kind,
            "rig_ids": [r.id for r in scene.skeletons if r.id not in before],
            "mesh_ids": [m.id for m in scene.meshes if m.id not in before],
            "object_ids": [o.id for o in scene.objects if o.id not in before],
        }

    def character_create(
        self, content: str | None = None, x: float = 0, y: float = 0
    ) -> dict[str, Any]:
        """Instantiate a complete original or installed character scene template."""
        if content is None:
            entry = next(
                (
                    e
                    for e in self.library.entries()
                    if e.path == self.library.bundled and e.item.category == "Characters"
                ),
                None,
            )
            if entry is None:
                raise ProjectError(
                    "No built-in character template is available; refresh the content library."
                )
            content = entry.key
        if self._content(content).item.category != "Characters":
            raise ProjectError("Choose a Characters template from library_list.")
        return self.template_apply(content, x=x, y=y)

    def rig_create(
        self,
        template: str = "Human · full body",
        start: list[float] | None = None,
        end: list[float] | None = None,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a reusable semantic rig or one bone from explicit scene-space endpoints."""
        if start is not None or end is not None:
            if not start or not end or len(start) != 2 or len(end) != 2:
                raise ProjectError("Bone endpoints require two numeric coordinates each.")
            key = RigService(self.document).create_bone(
                (start[0], start[1]), (end[0], end[1]), parent_id
            )
            return {"bone_id": key}
        if self._content(template).item.kind != "rig":
            raise ProjectError("Choose a skeleton template.")
        return self.template_apply(template)

    def mesh_create(
        self, asset_id: str, columns: int | None = None, rows: int | None = None
    ) -> dict[str, Any]:
        """Place artwork with Full triangles by default, or explicit regular grid dimensions."""
        key = MeshService(self.document).instantiate_asset(asset_id, columns, rows)
        return {"mesh_id": key, "object_id": MeshService(self.document).mesh(key).object_id}

    def weights_assign(
        self, mesh_id: str, bone_ids: list[str], weights: dict[str, dict[str, float]] | None = None
    ) -> dict[str, Any]:
        """Bind a mesh and assign normalized explicit per-vertex weights or automatic weights."""
        if not 1 <= len(bone_ids) <= 256:
            raise ProjectError("Choose 1–256 bone IDs.")
        service = SkinService(self.document)
        with self.transaction("Assign skin weights"):
            if weights is not None and any(
                vertex.protected and vertex.id in weights
                for vertex in service.mesh(mesh_id).vertices
            ):
                raise ProjectError("Explicit weights cannot replace protected vertices.")
            stage = service.bind(mesh_id, tuple(bone_ids), auto_weight=weights is None)
            if weights is not None:
                mesh = service.mesh(mesh_id)
                if not set(weights) <= {v.id for v in mesh.vertices} or any(
                    not set(values) <= set(bone_ids) for values in weights.values()
                ):
                    raise ProjectError("Weights reference vertices or bones outside this binding.")
                service.replace_mesh(
                    replace(
                        mesh,
                        vertices=tuple(
                            replace(v, weights=normalize_weights(weights[v.id], 4))
                            if v.id in weights
                            else v
                            for v in mesh.vertices
                        ),
                    ),
                    "Assign explicit weights",
                )
        return {"mesh_id": mesh_id, "deformer_id": stage}

    def pose_apply(self, content: str, target_id: str) -> dict[str, Any]:
        """Apply a semantic pose to an explicitly chosen compatible skeleton."""
        if self._content(content).item.kind != "pose":
            raise ProjectError("Choose a pose item.")
        return self.template_apply(content, target_id=target_id)

    def motion_apply(self, content: str, target_id: str) -> dict[str, Any]:
        """Create a canonical animation clip from an explicitly compatible body motion."""
        if self._content(content).item.kind != "action":
            raise ProjectError("Choose a motion item.")
        return self.template_apply(content, target_id=target_id)

    def deformer_apply(self, content: str, mesh_id: str) -> dict[str, Any]:
        """Apply an installed geometric or animated FFD preset to an explicit mesh."""
        if self._content(content).item.kind != "deformation":
            raise ProjectError("Choose a deformation item.")
        return self.template_apply(content, mesh_id=mesh_id)

    def clip_create(self, name: str = "Animation", duplicate: bool = False) -> dict[str, Any]:
        """Create and select a new or duplicated canonical clip with ordinary undo support."""
        return {
            "clip_id": AnimationEditingService(self.document).new_clip(name, duplicate=duplicate)
        }

    def clip_edit(
        self,
        clip_id: str,
        name: str | None = None,
        in_frame: float | None = None,
        out_frame: float | None = None,
        loop: bool | None = None,
    ) -> dict[str, Any]:
        """Select and edit validated clip boundaries and playback defaults."""
        self.document.select_animation_clip(clip_id)
        changes = {
            key: value
            for key, value in locals().items()
            if key in ("name", "in_frame", "out_frame", "loop") and value is not None
        }
        AnimationEditingService(self.document).clip_settings(**changes)
        return {"clip_id": clip_id}

    def keyframe_set(
        self,
        owner_id: str,
        property_path: str,
        frame: float,
        value: float = 0,
        interpolation: Literal["linear", "step", "bezier"] = "linear",
        delete: bool = False,
    ) -> dict[str, Any]:
        """Insert, replace or remove one validated numeric key in the currently selected clip."""
        AnimationEditingService(self.document).key(
            owner_id, property_path, frame, value, interpolation=interpolation, delete=delete
        )
        return {
            "owner_id": owner_id,
            "property_path": property_path,
            "frame": frame,
            "deleted": delete,
        }

    def timeline_inspect(self) -> dict[str, Any]:
        """Return the selected clip/timeline and available stable animation property paths."""
        service = AnimationEditingService(self.document)
        return {
            "clip": service.clip.to_dict() if service.clip else None,
            "timeline": service.timeline.to_dict() if service.timeline else None,
            "properties": [
                {"owner_id": record.id, "path": path, "value": value}
                for record, path, value in service.properties()
            ],
        }

    def frame_evaluate(self, frame: float = 0, clip_id: str | None = None) -> dict[str, Any]:
        """Evaluate immutable geometry without changing authoring state or the GUI playhead."""
        scratch = self.document.fork()
        if clip_id:
            scratch.select_animation_clip(clip_id)
        return scratch.animation.evaluate(frame).to_dict()

    def frame_render(
        self,
        path: str,
        frame: float = 0,
        frames: list[float] | None = None,
        width: int = 1280,
        height: int = 720,
        bones: bool = False,
        approve_overwrite: bool = False,
        format: str = "auto",
        fps: float | None = None,
        background: str | None = None,
        loop: bool = True,
        columns: int = 8,
        include_audio: bool = True,
    ) -> dict[str, Any]:
        """Render up to 60 preview frames through the same staged exporters as the render queue."""
        times = frames if frames is not None else [frame]
        if not 1 <= len(times) <= 60:
            raise ProjectError("A preview render supports 1–60 frames.")
        settings = self._settings(
            path,
            times,
            width,
            height,
            format,
            fps,
            bones,
            background,
            loop,
            columns,
            frames is not None,
        )
        result = self._output_service(approve_overwrite).export(
            self.document,
            path,
            replace(settings, include_audio=include_audio),
            progress=self.progress,
            dry_run=self._dry_run,
        )
        result["paths"] = [self._output_relative(p) for p in result["paths"]]
        result["frames"] = [
            {
                "frame": time,
                "path": result["paths"][
                    index if settings.format in ("svg", "png") and len(result["paths"]) > 1 else 0
                ],
                "completed": index + 1,
                "total": len(times),
            }
            for index, time in enumerate(times)
        ]
        return result

    def export_preflight(
        self,
        format: str = "png",
        frames: list[float] | None = None,
        width: int = 1280,
        height: int = 720,
        fps: float | None = None,
        include_audio: bool = True,
    ) -> dict[str, Any]:
        """Inspect requested poses, sources and engine capabilities without writing output."""
        from rigora.application_services.export_preflight import ExportPreflight

        settings = OutputSettings(
            format=format,
            frames=tuple(frames or [0]),
            width=width,
            height=height,
            fps=fps or self.document.scene.settings.fps,
            include_audio=include_audio,
        )
        return ExportPreflight(self.document.fork()).inspect(settings, encoder=self.encoder)

    def _settings(
        self,
        path: str,
        frames: list[float],
        width: int,
        height: int,
        format: str,
        fps: float | None,
        bones: bool,
        background: str | None,
        loop: bool,
        columns: int,
        sequence: bool = True,
    ) -> OutputSettings:
        """Resolve format and frame-rate defaults against the current canonical scene."""
        if format == "auto":
            format = Path(path).suffix.lower().removeprefix(".")
            format = {"mkv": "ffv1"}.get(format, format)
        rate = fps if fps is not None else MeshService(self.document).scene.settings.fps
        return OutputSettings(
            format, tuple(frames), width, height, rate, sequence, bones, background, loop, columns
        )

    def _output_service(self, approve_overwrite: bool) -> OutputService:
        """Inject the same boundary and explicit overwrite policy into every output adapter."""
        return OutputService(
            lambda path: self.path(path, output=True, approve_overwrite=approve_overwrite),
            encoder=self.encoder,
            exporters=self.exporters,
        )

    def _output_relative(self, value: str) -> str:
        """Normalize already-authorized result paths without applying overwrite checks again."""
        path = Path(value)
        return self.relative((path if path.is_absolute() else self.root / path).resolve())

    def render_submit(
        self,
        path: str,
        frames: list[float],
        width: int = 1280,
        height: int = 720,
        format: str = "auto",
        fps: float | None = None,
        bones: bool = False,
        background: str | None = None,
        loop: bool = True,
        columns: int = 8,
        approve_overwrite: bool = False,
        include_audio: bool = True,
    ) -> dict[str, Any]:
        """Queue a snapshot of up to 600 frames after synchronous path/settings preflight."""
        settings = self._settings(
            path, frames, width, height, format, fps, bones, background, loop, columns
        )
        settings = replace(settings, include_audio=include_audio)
        service = self._output_service(approve_overwrite)
        plan = service.export(self.document, path, settings, dry_run=True)
        if self._dry_run:
            return plan
        if self.render_queue is None:
            self.render_queue = RenderQueue()
        return self.render_queue.submit(self.document, service, path, settings)

    def render_status(self, job_id: str | None = None) -> dict[str, Any]:
        """Inspect bounded job history without blocking on active frame rendering."""
        if self.render_queue is None:
            if job_id:
                raise ProjectError("Render job is not part of this session.")
            return {"jobs": []}
        state = self.render_queue.inspect(job_id)
        if state.get("result"):
            state["result"] = {
                **state["result"],
                "paths": [self._output_relative(p) for p in state["result"]["paths"]],
            }
        elif "jobs" in state:
            state["jobs"] = [self.render_status(item["job_id"]) for item in state["jobs"]]
        return state

    def render_cancel(self, job_id: str) -> dict[str, Any]:
        """Request safe cancellation of one owned job before output publication begins."""
        if self.render_queue is None:
            raise ProjectError("Render job is not part of this session.")
        if self._dry_run:
            return self.render_status(job_id)
        return self.render_queue.cancel(job_id)

    def output_formats(self) -> dict[str, Any]:
        """List installed output capabilities without probing a binary or activating plugins."""
        import importlib.util

        raster = all(importlib.util.find_spec(name) is not None for name in ("PIL", "resvg_py"))
        return {
            "formats": [
                {
                    "id": key,
                    "name": name,
                    "extension": suffix,
                    "notes": FORMAT_NOTES.get(key, ""),
                    "available": key in ("svg", "runtime-json")
                    or raster
                    and (key not in VIDEO_OPTIONS or self.encoder is not None),
                }
                for key, (name, suffix) in FORMATS.items()
            ],
            "custom": list(self.exporters),
            "max_frames": 600,
            "max_preview_frames": 60,
        }

    def close(self, *, wait: bool = True) -> None:
        """Cancel unfinished owned render jobs and release their worker on host shutdown."""
        if self.render_queue:
            self.render_queue.close(wait=wait)

    def project_export(
        self,
        path: str,
        format: Literal["project-json", "rigaction", "rigpack", "rigora"] = "project-json",
        approve_overwrite: bool = False,
    ) -> dict[str, Any]:
        """Export authored JSON, a reusable animation action, or an original portable scene pack."""
        output = self.path(path, output=True, approve_overwrite=approve_overwrite)
        expected = {
            "project-json": ".json",
            "rigaction": ".rigaction",
            "rigpack": ".rigpack",
            "rigora": ".rigora",
        }
        if format not in expected or output.suffix.lower() != expected[format]:
            raise ProjectError("Export extension must match project-json, rigaction or rigpack.")
        self.project_validate()
        if format == "rigaction" and AnimationEditingService(self.document).clip is None:
            raise ProjectError("Select a clip to export.")
        if not self._dry_run:
            output.parent.mkdir(parents=True, exist_ok=True)
            if format == "project-json":
                data = self.project_inspect("full")
                _atomic_bytes(output, json.dumps(data, indent=2, allow_nan=False).encode())
            elif format == "rigaction":
                AnimationEditingService(self.document).export_action(
                    output, overwrite=approve_overwrite
                )
            elif format == "rigora":
                snapshot = self.document.fork()
                snapshot.embed_external_assets()
                snapshot.save(output, overwrite=approve_overwrite)
            else:
                ContentService(self.document).export_own(
                    output,
                    "Shared scene",
                    "Rigora user",
                    "All rights reserved",
                    overwrite=approve_overwrite,
                )
        return {"path": self.relative(output), "format": format, "planned": self._dry_run}

    def library_list(self, category: str = "All") -> dict[str, Any]:
        """List discovered data-only content without downloading or enabling executable code."""
        return {
            "items": [
                {
                    "id": entry.key,
                    "name": entry.item.name,
                    "kind": entry.item.kind,
                    "category": entry.item.category,
                    "license": entry.item.license,
                }
                for entry in self.library.entries()
                if category == "All" or entry.item.category == category
            ],
            "warnings": list(self.library.warnings),
        }

    def plugin_list(self) -> dict[str, Any]:
        """Inspect installed manifests in safe mode without executing or activating plugins."""
        manager = PluginManager(self.library.preferences, safe_mode=True)
        manager.discover(installed=False, allowed_roots=(self.root, *self.asset_roots))
        return {
            "items": [
                {
                    "id": key,
                    "name": state.manifest.name if state.manifest else key,
                    "enabled": False,
                    "installed": state.installed,
                    "error": state.error,
                }
                for key, state in manager.states.items()
            ]
        }

    def diagnostics(self) -> dict[str, Any]:
        """Report capabilities and package version without environment variables or credentials."""
        from rigora import __version__

        return {
            "version": __version__,
            "api_version": API_VERSION,
            "offline": True,
            "operations": list(OPERATIONS),
            "render_formats": list(FORMATS),
            "export_formats": ["project-json", "rigaction", "rigpack", "rigora"],
            "max_render_frames": 600,
            "active_project": self.document.project is not None,
        }

    def undo(self) -> dict[str, Any]:
        """Undo one ordinary application command in the current session."""
        self.document.undo()
        return self.project_inspect()

    def redo(self) -> dict[str, Any]:
        """Redo one previously undone ordinary application command."""
        self.document.redo()
        return self.project_inspect()
