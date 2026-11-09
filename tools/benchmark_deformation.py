"""Measure pure-Python FFD evaluation with a reproducible grid and sampled control motion."""

import argparse
import json
import statistics
import time

from rigora.domain.entities import AnimationClip, Deformer, Keyframe, Timeline, Track
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator


def benchmark(cells: int, controls: int, frames: int) -> dict[str, float | int]:
    """Measure complete immutable mesh-pose evaluation separately from Qt texture painting."""
    mesh = grid_mesh(1000, 1000, cells, cells)
    stage = Deformer(
        owner_id=mesh.id, kind="ffd", parameters={"columns": controls, "rows": controls}
    )
    timeline = Timeline(
        tracks=(
            Track(
                owner_id=stage.id,
                property_path="parameters.controls.0.0",
                keyframes=(Keyframe(frame=0, value=0), Keyframe(frame=120, value=180)),
            ),
        )
    )
    scene = Scene(
        meshes=(mesh,),
        deformers=(stage,),
        timelines=(timeline,),
        clips=(AnimationClip(timeline_id=timeline.id, out_frame=120),),
    )
    start = time.perf_counter()
    evaluator = SceneEvaluator(scene)
    compilation = time.perf_counter() - start
    evaluator.evaluate(0)
    times = []
    for index in range(frames):
        start = time.perf_counter()
        pose = evaluator.evaluate(index % 121)
        times.append((time.perf_counter() - start) * 1000)
        if pose.warnings:
            raise RuntimeError(pose.warnings)
    return {
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.triangles),
        "controls": controls**2,
        "frames": frames,
        "compile_ms": compilation * 1000,
        "median_ms": statistics.median(times),
        "max_ms": max(times),
    }


def main() -> None:
    """Print one bounded diagnostic measurement without loading Qt or creating project files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cells", type=int, choices=range(1, 33), default=32)
    parser.add_argument("--controls", type=int, choices=range(2, 9), default=8)
    parser.add_argument("--frames", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.frames <= 10000:
        parser.error("frames must be between 1 and 10000")
    print(json.dumps(benchmark(args.cells, args.controls, args.frames), indent=2))


if __name__ == "__main__":
    main()
