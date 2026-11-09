"""Undoable gameplay regions and deterministic world/local-space particle emitter authoring."""

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from rigora.application_services.meshes import MeshService
from rigora.domain.entities import SceneObject, Transform
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.particles import emitter_settings
from rigora.engine.sampling import number
from rigora.engine.view_switching import movement_settings


class GameAuthoringService(MeshService):
    """Author metadata-backed scene objects using ordinary transform/visibility/opacity tracks."""

    def movement_views(self, target: str, settings: dict[str, Any] | None) -> None:
        """Configure automatic authored-view switching; explicit View keys take precedence."""
        from rigora.domain.object_views import view_partitions

        root = next((g for g in self.scene.groups if g.id == target), None)
        if root is None or not root.extra.get("view_slots"):
            raise ProjectError("Choose an Object with authored views in Object Editor first.")
        if self.document.animation_context and target != self.document.animation_context:
            raise ProjectError("Configure the currently edited Object or return to Scene first.")
        extra = dict(root.extra)
        if settings is None:
            extra.pop("movement_views", None)
        else:
            data = movement_settings(settings)
            if data["driver"] not in self.document.animation.pose.nodes:
                raise ProjectError("Choose an existing transform driver in this scene.")
            partitions = view_partitions(self.scene, root)
            if any(not partitions[view] for view in data["slots"].values()):
                raise ProjectError("Movement mappings must use nonempty authored Object views.")
            extra["movement_views"] = data
        self.commit(
            "Configure movement-driven views",
            groups=tuple(
                replace(g, extra=extra) if g.id == target else g for g in self.scene.groups
            ),
        )

    def region(
        self,
        *,
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
    ) -> str:
        """Create/edit a non-rendering collision region; deletion uses normal scene ownership."""
        width, height = number(width), number(height)
        if kind not in ("hitbox", "hurtbox") or shape not in ("rectangle", "ellipse"):
            raise ProjectError("Choose Hitbox/Hurtbox and Rectangle/Ellipse.")
        if not 0 < width <= 1e6 or not 0 < height <= 1e6:
            raise ProjectError("Region dimensions must be positive and at most one million pixels.")
        if payload is not None and not isinstance(payload, Mapping):
            raise ProjectError("Region payload must be a JSON object.")
        payload = json_copy(payload if payload is not None else {})
        if len(json.dumps(payload).encode()) > 16384:
            raise ProjectError("Region payloads are limited to 16 KiB.")
        data = dict(
            type=kind,
            shape=shape,
            width=width,
            height=height,
            group=group,
            payload=payload,
        )
        return self._object(identity, name, parent, x, y, "game_region", data)

    def emitter(
        self,
        *,
        identity: str = "",
        name: str = "Particles",
        parent: str | None = None,
        x: float | None = None,
        y: float | None = None,
        settings: dict[str, Any] | None = None,
    ) -> str:
        """Create/edit a seeded emitter; ordinary visibility suppresses output and birth samples."""
        data = emitter_settings(settings or {})
        return self._object(identity, name, parent, x, y, "particle_emitter", data)

    def _object(
        self,
        identity: str,
        name: str,
        parent: str | None,
        x: float | None,
        y: float | None,
        field: str,
        data: dict[str, Any],
    ) -> str:
        """Publish one stable identity, preserving metadata and authored transforms on edit."""
        existing = next((o for o in self.scene.objects if o.id == identity), None)
        if (
            self.document.animation_scope is not None
            and identity
            and identity not in self.document.animation_scope
        ):
            raise ProjectError("Choose a region/emitter in this editable Object view.")
        if not identity and parent is None:
            parent = self.document.animation_context
        if identity and (existing is None or field not in existing.extra):
            raise ProjectError("Choose an existing region/emitter of this type.")
        if parent and parent not in {o.id for o in (*self.scene.objects, *self.scene.groups)}:
            raise ProjectError("Choose an Object/folder parent in this scene.")
        if (
            parent
            and self.document.animation_scope is not None
            and parent not in self.document.animation_scope
        ):
            raise ProjectError("Create regions/emitters inside the currently edited Object.")
        item = (
            replace(
                existing,
                name=name,
                extra={**existing.extra, field: data},
                transform=replace(
                    existing.transform,
                    x=existing.transform.x if x is None else number(x),
                    y=existing.transform.y if y is None else number(y),
                ),
            )
            if existing
            else SceneObject(
                name=name,
                parent_id=parent,
                transform=Transform(
                    x=number(x if x is not None else 0), y=number(y if y is not None else 0)
                ),
                extra={field: data},
            )
        )
        self.commit(
            "Edit game region/emitter",
            objects=tuple(o for o in self.scene.objects if o.id != item.id) + (item,),
        )
        return item.id
