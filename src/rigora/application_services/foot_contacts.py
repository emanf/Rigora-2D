"""Keep generated standing contacts aligned with deliberate edits to their foot controls."""

from collections.abc import Iterable, Mapping

from rigora.domain.entities import Constraint, Transform
from rigora.domain.project import Scene
from rigora.engine.constraints import ConstraintContext
from rigora.engine.state import ScenePose, TransformValues


def edited_contacts(
    scene: Scene,
    pose: ScenePose,
    transforms: Mapping[str, Transform],
    rules: Iterable[Constraint],
) -> dict[str, Transform]:
    """Return target-local transforms for explicitly edited, automatically planted feet.

    Start from the displayed pose and recompose proposed locals in hierarchy order.
    Descendant contacts inherit edited ancestors, including compensated Bone-mode poses.
    Ordinary user constraints and explicitly edited targets retain their own policy.
    This calculation never changes the document or disables standing constraints.
    """
    targets = {r.id for r in (*scene.groups, *scene.objects) if r.extra.get("studio_floor_plant")}
    if not targets:
        return {}
    affected = set(transforms)
    for node in pose.nodes.values():
        if node.parent_id in affected:
            affected.add(node.id)
    contacts = [
        c
        for c in rules
        if c.enabled
        and c.kind == "copy_transform"
        and c.owner_id in affected
        and c.target_id in targets
        and c.target_id not in transforms
    ]
    if not contacts:
        return {}
    context = ConstraintContext(list(pose.nodes.values()))
    for key in pose.nodes:
        if key in transforms:
            transform = transforms[key]
            context.local(
                key, TransformValues(*(getattr(transform, n) for n in TransformValues._fields))
            )
    result = {}
    for contact in contacts:
        assert contact.target_id is not None
        context.world(contact.target_id, context.node(contact.owner_id).world_matrix)
        result[contact.target_id] = Transform(**context.node(contact.target_id).local._asdict())
    return result
