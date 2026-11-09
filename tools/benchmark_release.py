"""Profile stacked deformation, large offline libraries and concurrent output without Qt."""

import argparse
import json
import math
import statistics
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from rigora.api import RigoraAPI
from rigora.application_services.content_library import ContentLibrary
from rigora.domain.content import ContentPack
from rigora.domain.entities import Deformer
from rigora.domain.mesh_geometry import grid_mesh
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator
from rigora.infrastructure.content_packs import write_pack
from rigora.infrastructure.preferences import PreferencesStore
from tools.benchmark_animation import fixture


def measure(evaluator: SceneEvaluator, samples: int) -> dict:
    """Time deterministic forward/backward seeks without imposing hardware-dependent thresholds."""
    evaluator.evaluate(0)
    times = []
    for i in range(samples):
        start = time.perf_counter()
        pose = evaluator.evaluate(((i * 0.61803398875) % 1) * evaluator.range.end)
        assert not pose.warnings, pose.warnings
        times.append((time.perf_counter() - start) * 1000)
    return {
        "median_ms": statistics.median(times),
        "p95_ms": sorted(times)[math.ceil(len(times) * 0.95) - 1],
        "samples": samples,
    }


def run(root: Path, samples: int, packs: int) -> dict:
    """Build bounded workloads and leave only the JSON report outside private temporary storage."""
    mesh = grid_mesh(1000, 1000, 32, 32)
    stages = tuple(
        Deformer(owner_id=mesh.id, kind=kind, order=i, parameters=parameters)
        for i, (kind, parameters) in enumerate(
            (
                ("ffd", {"columns": 8, "rows": 8, "controls": [[10, 5]] + [[0, 0]] * 63}),
                ("lattice", {"columns": 4, "rows": 4, "controls": [[0, 0]] * 15 + [[20, 0]]}),
                ("bulge", {"amount": 0.15}),
                ("twist", {"amount": 10}),
            )
        )
    )
    result = {
        "stacked_deformation": {
            "vertices": 1089,
            "stages": 4,
            **measure(SceneEvaluator(Scene(meshes=(mesh,), deformers=stages)), samples),
        }
    }
    scene = fixture(200, 200, 100, "bezier")
    timeline = replace(
        scene.timelines[0],
        tracks=tuple(
            replace(
                track,
                keyframes=tuple(replace(key, frame=key.frame * 100) for key in track.keyframes),
            )
            for track in scene.timelines[0].tracks
        ),
    )
    long_scene = replace(
        scene, timelines=(timeline,), clips=(replace(scene.clips[0], out_frame=99000),)
    )
    result["long_animation"] = {
        "bones": 200,
        "keys": 20000,
        "range_frames": 99000,
        **measure(SceneEvaluator(long_scene), samples),
    }
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rigora-profile-", dir=root) as directory:
        folder = Path(directory)
        library = ContentLibrary(PreferencesStore(folder / "profile.json"))
        library.root.mkdir()
        pose = replace(
            next(e.item for e in library.entries() if e.item.kind == "pose"), thumbnail=""
        )
        for index in range(packs):
            items = tuple(replace(pose, id=str(UUID(int=i + 1))) for i in range(32))
            pack = ContentPack(
                id=str(UUID(int=index + 1)),
                author="Rigora benchmark",
                license="CC0-1.0",
                items=items,
            )
            write_pack(library.root / f"pack-{index:03}.rigpack", pack, {})
        start = time.perf_counter()
        entries = library.entries()
        result["library"] = {
            "packs": packs,
            "items": len(entries),
            "scan_ms": (time.perf_counter() - start) * 1000,
        }
        api = RigoraAPI(folder)
        try:
            api.execute("project_create")
            actor = api.execute("character_create").data
            api.execute(
                "motion_apply", {"content": "Natural · Walk", "target_id": actor["rig_ids"][0]}
            )
            start = time.perf_counter()
            job = api.execute(
                "render_submit", {"path": "frame.svg", "frames": list(range(12))}
            ).data
            submit_ms = (time.perf_counter() - start) * 1000
            poll_ms = []
            while True:
                started = time.perf_counter()
                state = api.execute("render_status", {"job_id": job["job_id"]}).data
                poll_ms.append((time.perf_counter() - started) * 1000)
                if state["status"] in ("completed", "failed", "cancelled"):
                    break
                if time.perf_counter() - start > 60:
                    raise TimeoutError("Profile output exceeded 60 seconds")
                time.sleep(0.005)
            assert state["status"] == "completed", state
            result["background_svg"] = {
                "frames": 12,
                "submit_ms": submit_ms,
                "total_ms": (time.perf_counter() - start) * 1000,
                "status_p95_ms": sorted(poll_ms)[math.ceil(len(poll_ms) * 0.95) - 1],
            }
        finally:
            api.close()
    return result


def main() -> None:
    """Emit portable measurements; fixture construction is excluded from frame timing."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("build/release-profile"))
    parser.add_argument("--samples", type=int, choices=range(3, 1001), default=31)
    parser.add_argument("--packs", type=int, choices=range(1, 129), default=128)
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), args.samples, args.packs), indent=2))


if __name__ == "__main__":
    main()
