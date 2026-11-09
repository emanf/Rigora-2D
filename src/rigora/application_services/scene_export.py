"""Shared sampled scene overlays and camera metadata for editable engine packages."""

from collections.abc import Callable
from typing import Any

from rigora.application_services.documents import DocumentService
from rigora.application_services.rendering import camera_background_svg
from rigora.engine.camera_actions import lens_svg
from rigora.engine.cameras import active_camera, camera_size
from rigora.engine.state import ScenePose


def scene_samples(
    document: DocumentService,
    poses: list[ScenePose],
    limit: int,
    files: dict[str, bytes],
    check: Callable[[], None],
    *,
    overlays: bool,
) -> list[dict[str, Any]]:
    """Retain exact evaluated camera cuts and world particles; rasterize only lens overlays.

    Pixel coordinates remain X-right/Y-down. Images derive from original vectors
    at the texture limit, with identical SVG lens/background code to final rendering.
    Native runtimes can disable camera driving when placing a character into a game.
    """
    result = []
    cache: dict[str, str] = {}

    def image(shapes: str, width: float, height: float) -> str:
        """Share repeated overlay sources and enforce the package's decoded byte budget."""
        if not shapes or not overlays:
            return ""
        import resvg_py

        from rigora.application_services.rig_export import MAX_BYTES
        from rigora.domain.project import ProjectError

        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">'
            + shapes
            + "</svg>"
        )
        if svg not in cache:
            scale = min(1, limit / max(width, height))
            path = f"overlays/{len(cache)}.png"
            files[path] = resvg_py.svg_to_bytes(
                svg_string=svg,
                width=max(1, round(width * scale)),
                height=max(1, round(height * scale)),
                skip_system_fonts=True,
            )
            cache[svg] = path
            if sum(map(len, files.values())) > MAX_BYTES:
                raise ProjectError("Scene overlays exceed the 128 MiB rig file budget.")
        return cache[svg]

    for pose in poses:
        check()
        camera = active_camera(pose)
        entry: dict[str, Any] = {"camera": None, "particles": [], "render_order": pose.render_order}
        if camera:
            width, height = camera_size(camera, document.scene.settings)
            entry["camera"] = {
                "id": camera.id,
                "matrix": pose.nodes[camera.id].world_matrix,
                "width": width,
                "height": height,
                "background": image(
                    camera_background_svg(document, camera, width, height), width, height
                ),
                "lens": image(
                    lens_svg(
                        dict(camera.extra.get("lens_effects", {})),
                        pose.frame / document.scene.settings.fps,
                        width,
                        height,
                        dict(camera.extra.get("lens_speeds", {})),
                    ),
                    width,
                    height,
                ),
            }
        for owner, parts in pose.particles.items():
            node = pose.nodes[owner]
            if node.visible and node.opacity > 0:
                entry["particles"].extend(
                    {
                        "owner": owner,
                        "matrix": p.matrix,
                        "color": p.color,
                        "opacity": p.opacity * node.opacity,
                        "shape": p.shape,
                    }
                    for p in parts
                )
        result.append(entry)
    return result
