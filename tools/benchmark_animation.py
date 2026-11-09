"""Measure compilation and random-access evaluation independently of Qt and disk I/O."""

import argparse
import json
import math
import statistics
from time import perf_counter
from typing import Literal
from uuid import UUID

from rigora.domain.entities import AnimationClip, Bone, Keyframe, Skeleton, Timeline, Track
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator


def identity(index: int) -> str:
    """Assign deterministic UUIDs to disjoint fixture record ranges."""
    return str(UUID(int=index + 1))


def fixture(bones: int, tracks: int, keys: int, curve: Literal["linear", "bezier"]) -> Scene:
    """Build animated bone chains with bounded depth and independently indexed key arrays."""
    nodes = tuple(
        Bone(
            id=identity(index),
            parent_id=identity(index - 1) if index % 20 else None,
            length=10,
        )
        for index in range(bones)
    )
    records = tuple(
        Track(
            id=identity(bones + index),
            owner_id=nodes[index % bones].id,
            property_path="transform.rotation",
            keyframes=tuple(
                Keyframe(
                    id=identity(bones + tracks + index * keys + key),
                    frame=key * 10,
                    value=math.sin(key + index) * 30,
                    interpolation=curve,
                )
                for key in range(keys)
            ),
        )
        for index in range(tracks)
    )
    base = bones + tracks + tracks * keys
    timeline = Timeline(id=identity(base), tracks=records)
    clip = AnimationClip(id=identity(base + 1), timeline_id=timeline.id, out_frame=(keys - 1) * 10)
    return Scene(
        id=identity(base + 3),
        skeletons=(Skeleton(id=identity(base + 2), bones=nodes),),
        timelines=(timeline,),
        clips=(clip,),
    )


def main() -> None:
    """Print measured milliseconds and workload sizes as portable JSON without timing assertions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bones", type=int, default=1000)
    parser.add_argument("--tracks", type=int, default=1000)
    parser.add_argument("--keys", type=int, default=100)
    parser.add_argument("--samples", type=int, default=31)
    parser.add_argument("--curve", choices=("linear", "bezier"), default="bezier")
    args = parser.parse_args()
    if min(args.bones, args.tracks, args.keys, args.samples) < 1:
        parser.error("All workload counts must be positive.")
    start = perf_counter()
    scene = fixture(args.bones, args.tracks, args.keys, args.curve)
    built = perf_counter()
    evaluator = SceneEvaluator(scene)
    compiled = perf_counter()
    evaluator.evaluate(0)  # Warm up separately from the timed random and backward seeks.
    elapsed = []
    for index in range(args.samples):
        frame = ((index * 0.61803398875) % 1) * evaluator.range.end
        started = perf_counter()
        evaluator.evaluate(frame)
        elapsed.append((perf_counter() - started) * 1000)
    print(
        json.dumps(
            {
                "bones": args.bones,
                "tracks": args.tracks,
                "keys_per_track": args.keys,
                "total_keys": args.tracks * args.keys,
                "curve": args.curve,
                "samples": args.samples,
                "fixture_ms": round((built - start) * 1000, 3),
                "compile_ms": round((compiled - built) * 1000, 3),
                "evaluate_median_ms": round(statistics.median(elapsed), 3),
                "evaluate_p95_ms": round(sorted(elapsed)[math.ceil(len(elapsed) * 0.95) - 1], 3),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
