"""Explicit, non-deforming master controls above a skeleton's independent chains."""

from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

from rigora.domain.entities import Bone, Skeleton, Transform


def rooted_skeleton(skeleton: Skeleton, *, position: tuple[float, float] = (0, 0)) -> Skeleton:
    """Add a non-deforming master while retaining existing IDs and rest geometry.

    The default identity insertion preserves legacy animation keys. Template authors
    may supply an attachment position; direct children are rebased to preserve world
    poses, and their absolute translation keys must use that same offset. Bind matrices
    remain valid. Existing masters are never repositioned implicitly.
    """
    if any(b.extra.get("rig_root") for b in skeleton.bones):
        return skeleton
    root = Bone(
        id=str(uuid5(NAMESPACE_URL, "rigora/rig-root/" + skeleton.id)),
        name="Rig Root",
        length=0,
        transform=Transform(x=position[0], y=position[1]),
        extra={"rig_root": True},
    )
    return replace(
        skeleton,
        bones=(
            root,
            *(
                replace(
                    b,
                    parent_id=root.id,
                    transform=replace(
                        b.transform, x=b.transform.x - position[0], y=b.transform.y - position[1]
                    ),
                )
                if b.parent_id is None
                else b
                for b in skeleton.bones
            ),
        ),
    )
