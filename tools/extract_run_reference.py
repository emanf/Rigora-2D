"""Extract normalized side-view run and jump trajectories from a pinned CC0 KayKit reference.

Run with a local Knight.glb and an output JSON path. Only numeric joint motion is
retained; meshes, materials and textures are never copied into the runtime asset.
The source digest prevents silently changing the reference during regeneration.
"""

import argparse
import bisect
import hashlib
import json
import math
import struct
from pathlib import Path

SOURCE_SHA256 = "60428e3abc09ba83e595d256e3af8c5c976b46cdae599f0802fc82b4a3445168"
SOURCE = (
    "https://github.com/KayKit-Game-Assets/KayKit-Character-Pack-Adventures-1.0/"
    "blob/672074b73ba276876a19e8816ecdc5241817ab47/"
    "addons/kaykit_character_pack_adventures/Characters/gltf/Knight.glb"
)


def multiply(a, b):
    """Compose row-major transforms for offline glTF joint projection."""
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def matrix(node):
    """Implement glTF's T*R*S convention with quaternion rotation and column-major matrices."""
    if "matrix" in node:
        return [[node["matrix"][j * 4 + i] for j in range(4)] for i in range(4)]
    x, y, z, w = node.get("rotation", (0, 0, 0, 1))
    rotation = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    scale, translation = node.get("scale", (1, 1, 1)), node.get("translation", (0, 0, 0))
    return [[rotation[i][j] * scale[j] for j in range(3)] + [translation[i]] for i in range(3)] + [
        [0, 0, 0, 1]
    ]


def extract(path, *, quaternius=False):
    """Validate the reference and sample its FK hierarchy without executing model content."""
    data = path.read_bytes()
    digest = (
        "4c748767741a3e495d89667b9a218b690ba9810b9517a12e960780e3ca72c4e9"
        if quaternius
        else SOURCE_SHA256
    )
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Use the documented, pinned CC0 reference.")
    size, _ = struct.unpack_from("<II", data, 12)
    doc = json.loads(data[20 : 20 + size])
    binary = data[28 + size :]

    def accessor(index):
        record = doc["accessors"][index]
        assert record["componentType"] == 5126 and "sparse" not in record
        width = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[record["type"]]
        if "bufferView" not in record:
            return [(0.0,) * width for _ in range(record["count"])]
        view = doc["bufferViews"][record["bufferView"]]
        offset = view.get("byteOffset", 0) + record.get("byteOffset", 0)
        stride = view.get("byteStride", width * 4)
        return [
            struct.unpack_from("<" + "f" * width, binary, offset + i * stride)
            for i in range(record["count"])
        ]

    parents = {child: i for i, n in enumerate(doc["nodes"]) for child in n.get("children", ())}
    names = {n["name"]: i for i, n in enumerate(doc["nodes"])}

    def positions(animation=None, time=0):
        nodes = [dict(n) for n in doc["nodes"]]
        if animation:
            for channel in animation["channels"]:
                sampler = animation["samplers"][channel["sampler"]]
                assert sampler.get("interpolation", "LINEAR") == "LINEAR"
                times = [v[0] for v in accessor(sampler["input"])]
                values = accessor(sampler["output"])
                if len(times) == 1:
                    nodes[channel["target"]["node"]][channel["target"]["path"]] = values[0]
                    continue
                i = max(0, min(len(times) - 2, bisect.bisect_right(times, time) - 1))
                t = max(0, min(1, (time - times[i]) / (times[i + 1] - times[i])))
                a, b = values[i], values[i + 1]
                path = channel["target"]["path"]
                if path == "rotation":
                    dot = sum(x * y for x, y in zip(a, b, strict=True))
                    if dot < 0:
                        b, dot = tuple(-v for v in b), -dot
                    if dot < 0.9995:
                        angle = math.acos(min(1, dot))
                        value = [
                            (
                                (math.sin((1 - t) * angle) * x + math.sin(t * angle) * y)
                                / math.sin(angle)
                            )
                            for x, y in zip(a, b, strict=True)
                        ]
                    else:
                        value = [x + t * (y - x) for x, y in zip(a, b, strict=True)]
                    length = math.sqrt(sum(v * v for v in value))
                    value = [v / length for v in value]
                else:
                    value = [x + t * (y - x) for x, y in zip(a, b, strict=True)]
                nodes[channel["target"]["node"]][path] = value
        world = {}

        def resolve(i):
            if i not in world:
                local = matrix(nodes[i])
                world[i] = multiply(resolve(parents[i]), local) if i in parents else local
            return world[i]

        result = {
            name: tuple(resolve(i)[axis][3] for axis in range(3)) for name, i in names.items()
        }
        if quaternius:
            aliases = {"hips": "pelvis", "chest": "spine_03"}
            for side in ("r", "l"):
                for target, source in (
                    ("upperleg", "thigh"),
                    ("lowerleg", "calf"),
                    ("foot", "foot"),
                    ("toes", "ball"),
                    ("upperarm", "upperarm"),
                    ("lowerarm", "lowerarm"),
                    ("wrist", "hand"),
                ):
                    aliases[target + "." + side] = source + "_" + side
            return {key: result[value] for key, value in aliases.items()}
        return result

    rest = positions()
    leg = math.dist(rest["upperleg.r"], rest["lowerleg.r"]) + math.dist(
        rest["lowerleg.r"], rest["foot.r"]
    )
    forward = 1 if rest["toes.r"][2] > rest["foot.r"][2] else -1
    result = {}
    selected = (
        ("Jog_Fwd_Loop", "Sprint_Loop")
        if quaternius
        else ("Running_A", "Running_B", "Jump_Full_Short", "Jump_Full_Long")
    )
    for name in selected:
        animation = next(a for a in doc["animations"] if a["name"] == name)
        duration = max(accessor(s["input"])[-1][0] for s in animation["samplers"])
        looping = not name.startswith("Jump")
        samples = [positions(animation, duration * i / 32) for i in range(32 if looping else 33)]
        floor = min(p["foot." + side][1] for p in samples for side in ("r", "l"))
        start = max(
            range(32),
            key=lambda i: forward * (samples[i]["foot.r"][2] - samples[i]["upperleg.r"][2]),
        )
        if looping:
            samples = samples[start:] + samples[:start]
        channels = {}

        def angle(p, a, b):
            return math.degrees(math.atan2(p[a][1] - p[b][1], forward * (p[b][2] - p[a][2])))

        channels["height"] = [
            ((p["upperleg.r"][1] + p["upperleg.l"][1]) / 2 - floor) / leg for p in samples
        ]
        channels["lean"] = [angle(p, "hips", "chest") + 90 for p in samples]
        for side in ("r", "l"):
            for axis, component in (("x", 2), ("y", 1)):
                sign = forward if axis == "x" else -1
                channels[f"foot.{side}.{axis}"] = [
                    sign * (p["foot." + side][component] - p["upperleg." + side][component]) / leg
                    for p in samples
                ]
            for key, a, b in (
                ("upper", "upperarm.", "lowerarm."),
                ("fore", "lowerarm.", "wrist."),
                ("foot", "foot.", "toes."),
            ):
                values = [angle(p, a + side, b + side) for p in samples]
                for i in range(1, len(values)):
                    values[i] = values[i - 1] + (values[i] - values[i - 1] + 180) % 360 - 180
                channels[f"{key}.{side}"] = values
        result[name] = {
            "duration": duration,
            "channels": {key: [round(v, 6) for v in values] for key, values in channels.items()},
        }
    return {
        "source": "https://quaternius.com/packs/universalanimationlibrary.html"
        if quaternius
        else SOURCE,
        "source_sha256": digest,
        "author": "Quaternius" if quaternius else "Kay Lousberg",
        "license": "CC0-1.0",
        "samples": 32,
        "cycles": result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--quaternius", action="store_true", help="Read the pinned Standard Jog/Sprint reference."
    )
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(extract(args.source, quaternius=args.quaternius), indent=2) + "\n",
        encoding="utf-8",
    )
