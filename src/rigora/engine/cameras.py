"""Shared orthographic camera projection, framing and active-cut resolution."""

from dataclasses import replace
from types import MappingProxyType

from rigora.domain.entities import Camera
from rigora.domain.geometry import inverse, multiply, transform_point
from rigora.domain.project import SceneSettings
from rigora.engine.state import ScenePose


def camera_size(camera: Camera, settings: SceneSettings) -> tuple[float, float]:
    """Resolve a scene-matched or explicitly sized camera frame in output pixels."""
    return (
        (float(settings.width), float(settings.height))
        if camera.match_scene
        else (camera.width, camera.height)
    )


def active_camera(pose: ScenePose) -> Camera | None:
    """Choose the last enabled active cut, falling back deterministically to the first camera."""
    enabled = [c for c in pose.cameras if c.enabled and c.id in pose.nodes]
    return next(
        (c for c in reversed(enabled) if pose.nodes[c.id].visible), enabled[0] if enabled else None
    )


def camera_corners(
    camera: Camera, pose: ScenePose, settings: SceneSettings
) -> tuple[tuple[float, float], ...]:
    """Return the four evaluated world-space corners for picking and frame overlays."""
    width, height = camera_size(camera, settings)
    matrix = pose.nodes[camera.id].world_matrix
    return tuple(
        transform_point(matrix, x, y) for x, y in ((0, 0), (width, 0), (width, height), (0, height))
    )


def camera_view(pose: ScenePose, camera: Camera | None = None) -> ScenePose:
    """Project a display snapshot into camera pixels; never feed it back into the solvers."""
    camera = camera or active_camera(pose)
    pose = pose.for_display()
    if camera is None:
        return pose
    matrix = inverse(pose.nodes[camera.id].world_matrix)
    return replace(
        pose,
        nodes=MappingProxyType(
            {
                key: replace(node, world_matrix=multiply(matrix, node.world_matrix))
                for key, node in pose.nodes.items()
            }
        ),
        particles=MappingProxyType(
            {
                owner: tuple(replace(p, matrix=multiply(matrix, p.matrix)) for p in parts)
                for owner, parts in pose.particles.items()
            }
        ),
    )
