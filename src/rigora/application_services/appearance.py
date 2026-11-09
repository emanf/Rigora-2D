"""Undoable vector/raster looks and native shape authoring on the common animation channels."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from rigora.application_services.animation_editing import AnimationEditingService
from rigora.application_services.deformation import DeformationService
from rigora.domain.entities import Deformer, Transform
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.engine.vector_appearance import palette, shape_svg


class AppearanceService(DeformationService):
    """Store appearance as an evaluated stage so GUI, export and animation use one model."""

    def ensure(self, mesh_id: str) -> str:
        """Create a neutral look from the original editable palette, retaining source bytes."""
        mesh = self.mesh(mesh_id)
        old = next(
            (d for d in self.scene.deformers if d.owner_id == mesh_id and d.kind == "appearance"),
            None,
        )
        if old:
            return old.id
        data = self.document.read_asset(mesh.asset_id) if mesh.asset_id else b""
        colors = [
            {
                "role": role,
                "source": color,
                "r": int(color[1:3], 16),
                "g": int(color[3:5], 16),
                "b": int(color[5:7], 16),
            }
            for role, color in palette(data)
        ]
        stage = Deformer(
            name="Appearance",
            owner_id=mesh_id,
            kind="appearance",
            order=10000,
            parameters={
                "palette": colors,
                "tint": {"r": 255, "g": 255, "b": 255, "amount": 0},
                "stroke_width": -1,
            },
        )
        self.commit("Add editable appearance", deformers=(*self.scene.deformers, stage))
        return stage.id

    def edit(
        self, mesh_ids: tuple[str, ...], values: dict[str, float], *, auto_key: bool = False
    ) -> None:
        """Edit base looks or current keyed channels, seeding new animation only with Auto key."""
        self._edit({mesh_id: values for mesh_id in mesh_ids}, auto_key=auto_key)

    def _edit(self, changes: Mapping[str, dict[str, float]], *, auto_key: bool = False) -> None:
        """Validate changed looks, then publish base parameters and keyed scalars in batches."""
        with self.document.command_group("Edit appearance"):
            editor = AnimationEditingService(self.document)
            keyed: dict[tuple[str, str], float] = {}
            updated = {}
            for mesh_id, values in changes.items():
                key = self.ensure(mesh_id)
                channels = {(key, "parameters." + path): value for path, value in values.items()}
                timeline = editor.timeline
                # Existing keys mask base parameters, just as they mask rest transforms.
                animated = timeline and any(
                    t.keyframes and (t.owner_id, t.property_path) in channels
                    for t in timeline.tracks
                )
                if auto_key or animated:
                    keyed.update(channels)
                else:
                    params = json_copy(self.stage(key).parameters)
                    from rigora.engine.deformation import DeformationPlan

                    for path, value in values.items():
                        DeformationPlan.override_parameter(params, "parameters." + path, value)
                    stage = replace(self.stage(key), parameters=params)
                    self.validate(stage)
                    updated[key] = stage
            if updated:
                self.commit(
                    "Edit appearance",
                    deformers=tuple(updated.get(d.id, d) for d in self.scene.deformers),
                )
            if keyed:
                editor.auto_key_values(keyed, self.document.animation.pose.frame)

    def color(
        self, mesh_ids: tuple[str, ...], index: int, color: str, *, auto_key: bool = False
    ) -> None:
        """Replace a detected paint on all selected images that contain its original color."""
        with self.document.command_group("Change artwork color"):
            first = self.stage(self.ensure(mesh_ids[0])).parameters["palette"]
            if not 0 <= index < len(first):
                raise ProjectError("Choose a detected artwork color.")
            source, role = first[index]["source"], first[index]["role"]
            self.paint(mesh_ids, role, source, color, auto_key=auto_key)

    def paint(
        self,
        mesh_ids: tuple[str, ...],
        role: str,
        source: str,
        color: str,
        *,
        auto_key: bool = False,
    ) -> None:
        """Change one detected paint consistently across selected editable parts or folders."""
        from rigora.engine.vector_appearance import rgb

        channels = rgb(color)
        if channels is None:
            raise ProjectError("Choose a solid artwork color.")
        with self.document.command_group("Change grouped artwork paint"):
            changes: dict[str, dict[str, float]] = {}
            for mesh_id in mesh_ids:
                paints = self.stage(self.ensure(mesh_id)).parameters["palette"]
                for i, paint in enumerate(paints):
                    if (paint["source"], paint["role"]) == (source, role):
                        changes.setdefault(mesh_id, {}).update(
                            {
                                f"palette.{i}.{k}": value
                                for k, value in zip(("r", "g", "b"), channels, strict=True)
                            },
                        )
            self._edit(changes, auto_key=auto_key)

    def create_shape(self, kind: str, x: float, y: float, width: float, height: float) -> str:
        """Create a real editable SVG asset and ordinary scene object in one undo step."""
        with self.document.command_group("Draw vector shape"):
            mesh_id = self.import_image_bytes(f"{kind.title()}.svg", shape_svg(width, height, kind))
            mesh = self.mesh(mesh_id)
            obj = next(o for o in self.scene.objects if o.id == mesh.object_id)
            self.commit(
                "Place drawn shape",
                objects=tuple(
                    replace(
                        o,
                        transform=Transform(
                            x=x,
                            y=y,
                            pivot_x=mesh.extra["image_width"] / 2,
                            pivot_y=mesh.extra["image_height"] / 2,
                        ),
                    )
                    if o.id == obj.id
                    else o
                    for o in self.scene.objects
                ),
            )
            key = self.ensure(mesh_id)
            params: dict[str, Any] = json_copy(self.stage(key).parameters)
            params["shape"] = {
                "start": kind,
                "end": kind,
                "mix": 0,
                "width": width,
                "height": height,
            }
            self.update(key, parameters=params)
        return mesh_id

    def morph_target(self, mesh_id: str, kind: str) -> None:
        """Choose the compatible contour target while keeping mix on the existing timeline."""
        stage = next(
            (d for d in self.scene.deformers if d.owner_id == mesh_id and d.kind == "appearance"),
            None,
        )
        if stage is None:
            raise ProjectError("Shape tweening works on shapes made with the Draw tool.")
        key = stage.id
        params = json_copy(stage.parameters)
        if "shape" not in params:
            raise ProjectError("Shape tweening works on shapes made with the Draw tool.")
        shape_svg(params["shape"]["width"], params["shape"]["height"], kind)
        params["shape"]["end"] = kind
        self.update(key, parameters=params)
