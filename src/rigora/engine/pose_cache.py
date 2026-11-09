"""Bounded per-session evaluated-pose reuse; no sources, widgets or transport state are owned."""

from collections import OrderedDict

from rigora.engine.state import ScenePose


class PoseCache:
    """Reuse immutable frame samples under conservative memory and entry-count bounds."""

    def __init__(self, limit: int = 64 * 1024 * 1024) -> None:
        """Allocate an empty cache; memory accounting intentionally overestimates shared arrays."""
        self.limit = limit
        self.entries: OrderedDict[tuple[object, ...], tuple[ScenePose, int]] = OrderedDict()
        self.bytes = self.hits = self.misses = 0

    def get(self, key: tuple[object, ...]) -> ScenePose | None:
        """Return an exact sample only; fractional frames are never silently quantized."""
        if key not in self.entries:
            self.misses += 1
            return None
        self.hits += 1
        self.entries.move_to_end(key)
        return self.entries[key][0]

    def put(self, key: tuple[object, ...], pose: ScenePose) -> None:
        """Retain an immutable pose, evicting oldest entries to preserve both bounds."""
        size = (
            1024 * (len(pose.nodes) + len(pose.spring_targets or ()))
            + sum(
                256 + 128 * len(m.positions) + 64 * len(m.triangles) for m in pose.meshes.values()
            )
            + len(pose.bone_placements) * 256
            + sum(len(parts) * 256 for parts in pose.particles.values())
        )
        if size > self.limit:
            return
        old = self.entries.pop(key, None)
        if old:
            self.bytes -= old[1]
        while self.entries and (self.bytes + size > self.limit or len(self.entries) >= 128):
            _, (_, cost) = self.entries.popitem(last=False)
            self.bytes -= cost
        self.entries[key] = pose, size
        self.bytes += size

    def clear(self) -> None:
        """Release all retained frames while preserving lifetime hit/miss counters."""
        self.entries.clear()
        self.bytes = 0
