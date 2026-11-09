"""Bounded Qt-free SVG preview rendering from canonical evaluated scene geometry."""

import base64
import io
import math
from functools import lru_cache
from html import escape

from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Camera
from rigora.domain.geometry import inverse, multiply, transform_point
from rigora.domain.project import ProjectError
from rigora.engine.camera_actions import lens_svg
from rigora.engine.cameras import active_camera, camera_size, camera_view
from rigora.engine.state import ScenePose
from rigora.infrastructure.artwork import inspect_artwork
from rigora.resources import asset_path

MAX_RENDER_BYTES = 32 * 1024 * 1024


@lru_cache(maxsize=64)
def _raster_region(data: bytes, bounds: tuple[int, int, int, int]) -> bytes | None:
    """Cache lossless render regions so atlas triangles do not sample the entire source.

    Source assets and UVs remain unchanged. Cropping affects only the intermediate
    export bitmap. Basic SVG export also works without the optional render adapter.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    with Image.open(io.BytesIO(data)) as source:
        region = source.crop(bounds)
        output = io.BytesIO()
        region.save(output, format="PNG")
        return output.getvalue()


def svg_frame(
    document: DocumentService,
    frame: float,
    *,
    width: int = 1280,
    height: int = 720,
    bones: bool = False,
) -> bytes:
    """Evaluate an authored frame and render it through the shared original-vector pipeline."""
    return svg_pose(
        document, document.animation.evaluate(frame), width=width, height=height, bones=bones
    )


def svg_pose(
    document: DocumentService,
    pose: ScenePose,
    *,
    width: int = 1280,
    height: int = 720,
    bones: bool = False,
) -> bytes:
    """Render actual deformed vector/raster triangles into a portable transparent SVG.

    Source SVGs remain isolated vector subdocuments. Image definitions are shared across
    triangle instances; evaluated UV transforms and clip paths reproduce mesh deformation.
    No Qt application, browser, executable asset, external reference or network is needed.
    """
    if (
        type(width) is not int
        or type(height) is not int
        or not 1 <= width <= 4096
        or not 1 <= height <= 4096
    ):
        raise ProjectError("Preview dimensions must be integers between 1 and 4096.")
    if document.project is None:
        raise ProjectError("Create or open a project before rendering.")
    if pose.scene_id != document.scene.id:
        raise ProjectError("Render a pose from the selected scene.")
    frame = pose.requested_frame
    pose = pose.for_display()
    camera = active_camera(pose)
    pose = camera_view(pose, camera)
    if pose.warnings:
        raise ProjectError("Cannot render incomplete evaluation: " + "; ".join(pose.warnings))
    scene = document.scene
    definitions, shapes = [], []
    sources = {}
    original_bytes = {}
    mesh_sources = {}
    faces = sum(len(mesh.triangles) for mesh in pose.meshes.values())
    if faces > 20000:
        raise ProjectError("Preview rendering supports at most 20,000 triangles per frame.")
    source_bytes = 0
    for mesh in pose.meshes.values():
        source_key = mesh.id if mesh.appearance else str(mesh.asset_id or "")
        mesh_sources[mesh.id] = source_key
        if mesh.asset_id and source_key not in sources:
            data = document.read_asset(mesh.asset_id)
            if mesh.appearance:
                from rigora.engine.vector_appearance import styled_artwork

                data = styled_artwork(data, mesh.appearance)
            source_bytes += len(data)
            if source_bytes > 16 * 1024 * 1024:
                raise ProjectError("Preview sources exceed the 16 MiB per-frame input budget.")
            info = inspect_artwork(data)
            if info.kind == "vector" and b"<text" in data:
                raise ProjectError(
                    "Headless SVG text must be converted to vector outlines before export."
                )
            if info.kind == "raster" and info.media_type not in (
                "image/png",
                "image/jpeg",
                "image/gif",
            ):
                from rigora.infrastructure.media_import import pillow_image, png_bytes

                data = png_bytes(pillow_image(data))
                info = inspect_artwork(data)
            sources[source_key] = info
            original_bytes[source_key] = data
            encoded = base64.b64encode(data).decode("ascii")
            definitions.append(
                f'<image id="asset-{source_key}" width="{info.width}" height="{info.height}" '
                f'href="data:{info.media_type};base64,{encoded}"/>'
            )
    for node_id in pose.render_order:
        node = pose.nodes[node_id]
        if not node.visible or node.opacity <= 0:
            continue
        for particle in pose.particles.get(node_id, ()):
            particle_matrix = " ".join(f"{v:.10g}" for v in particle.matrix)
            primitive_svg = (
                '<circle r="1"/>'
                if particle.shape == "circle"
                else '<rect x="-1" y="-1" width="2" height="2"/>'
            )
            shapes.append(
                f'<g transform="matrix({particle_matrix})" fill="{particle.color}" '
                f'opacity="{node.opacity * particle.opacity:.6g}">{primitive_svg}</g>'
            )
        meshes = [mesh for mesh in pose.meshes.values() if mesh.object_id == node_id]
        for mesh in meshes:
            source_key = mesh_sources[mesh.id]
            source_info = sources.get(source_key)
            if source_info is None:
                continue
            source_id = f"asset-{source_key}"
            if source_info.kind == "raster" and mesh.uv:
                left = max(0, math.floor(min(u for u, _ in mesh.uv) * source_info.width) - 2)
                top = max(0, math.floor(min(v for _, v in mesh.uv) * source_info.height) - 2)
                right = min(
                    source_info.width, math.ceil(max(u for u, _ in mesh.uv) * source_info.width) + 2
                )
                bottom = min(
                    source_info.height,
                    math.ceil(max(v for _, v in mesh.uv) * source_info.height) + 2,
                )
                if right > left and bottom > top:
                    region = _raster_region(original_bytes[source_key], (left, top, right, bottom))
                    if region is not None:
                        source_id = f"region-{mesh.id}"
                        encoded = base64.b64encode(region).decode("ascii")
                        definitions.append(
                            f'<image id="{source_id}" x="{left}" y="{top}" '
                            f'width="{right - left}" height="{bottom - top}" '
                            f'href="data:image/png;base64,{encoded}"/>'
                        )
            groups: dict[str, list[str]] = {}
            for face in mesh.triangles:
                source = [
                    (mesh.uv[i][0] * source_info.width, mesh.uv[i][1] * source_info.height)
                    for i in face
                ]
                target = [transform_point(node.world_matrix, *mesh.positions[i]) for i in face]
                a, b, c = source
                p, q, r = target
                basis = (b[0] - a[0], b[1] - a[1], c[0] - a[0], c[1] - a[1], a[0], a[1])
                destination = (q[0] - p[0], q[1] - p[1], r[0] - p[0], r[1] - p[1], p[0], p[1])
                try:
                    matrix = multiply(destination, inverse(basis))
                except ProjectError:
                    continue
                if any(not math.isfinite(v) or abs(v) > 1e8 for v in matrix):
                    raise ProjectError("Preview geometry exceeds supported coordinate bounds.")
                # Equivalent rigid regions can differ by floating-point signed zero.
                # Normalize that noise so one union clip avoids shared-edge seams.
                values = " ".join(f"{0 if abs(v) < 1e-10 else v:.10g}" for v in matrix)
                points = "L".join(f"{x:.8g},{y:.8g}" for x, y in target)
                groups.setdefault(values, []).append(f"M{points}Z")
            shapes.append(f'<g opacity="{node.opacity:.6g}">')
            for index, (values, paths) in enumerate(groups.items()):
                clip = f"face-{mesh.id}-{index}"
                # Shared affine regions use one union clip, avoiding internal triangle seams.
                definitions.append(
                    f'<clipPath id="{clip}" shape-rendering="crispEdges">'
                    f'<path d="{" ".join(paths)}"/></clipPath>'
                )
                shapes.append(
                    f'<g clip-path="url(#{clip})">'
                    f'<use href="#{source_id}" transform="matrix({values})"/></g>'
                )
            shapes.append("</g>")
        if node.kind == "bone" and (bones or not pose.meshes):
            data = asset_path("shapes/bone.svg").read_bytes()
            if not any('id="bone-source"' in d for d in definitions):
                encoded = base64.b64encode(data).decode("ascii")
                definitions.append(
                    '<image id="bone-source" width="1024" height="1536" '
                    f'href="data:image/svg+xml;base64,{encoded}"/>'
                )
            scale = node.length / 1232
            shape = (0.0, scale, -scale, 0.0, 1402 * scale, -512 * scale)
            matrix = multiply(node.world_matrix, shape)
            values = " ".join(f"{v:.10g}" for v in matrix)
            shapes.append(
                f'<use href="#bone-source" transform="matrix({values})" '
                f'opacity="{node.opacity:.6g}"/>'
            )
    view_width, view_height = (
        camera_size(camera, scene.settings)
        if camera
        else (scene.settings.width, scene.settings.height)
    )
    background = camera_background_svg(document, camera, view_width, view_height) if camera else ""
    data = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {view_width:g} {view_height:g}">'
        f"<title>{escape(document.project.name)} · frame {frame:g}</title><defs>"
        + "".join(definitions)
        + "</defs>"
        + background
        + "".join(shapes)
        + (
            lens_svg(
                dict(camera.extra.get("lens_effects", {})),
                frame / scene.settings.fps,
                view_width,
                view_height,
                dict(camera.extra.get("lens_speeds", {})),
            )
            if camera
            else ""
        )
        + "</svg>"
    ).encode("utf-8")
    if len(data) > MAX_RENDER_BYTES:
        raise ProjectError("A preview frame exceeds the 32 MiB output limit.")
    return data


def camera_background_svg(
    document: DocumentService, camera: Camera, width: float, height: float
) -> str:
    """Encode a packaged color/image backdrop in camera coordinates, preserving alpha."""
    if camera.background_mode == "transparent":
        return ""
    color = camera.background_color
    alpha = int(color[7:9], 16) / 255 if len(color) == 9 else 1.0
    result = (
        f'<rect width="{width:g}" height="{height:g}" fill="{color[:7]}" '
        f'fill-opacity="{alpha * camera.background_opacity:g}"/>'
    )
    if camera.background_mode == "image" and camera.asset_id:
        data = document.read_asset(camera.asset_id)
        if len(data) > 16 * 1024 * 1024:
            raise ProjectError("Camera background exceeds the 16 MiB render input budget.")
        info = inspect_artwork(data)
        fit = {"cover": "xMidYMid slice", "contain": "xMidYMid meet", "stretch": "none"}[
            camera.background_fit
        ]
        encoded = base64.b64encode(data).decode("ascii")
        result += (
            f'<image width="{width:g}" height="{height:g}" preserveAspectRatio="{fit}" '
            f'opacity="{camera.background_opacity:g}" '
            f'href="data:{info.media_type};base64,{encoded}"/>'
        )
    return result
