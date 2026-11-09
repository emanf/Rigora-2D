"""Apply reusable physical settings and smooth source keys through the existing engine services."""

from rigora.application_services.documents import DocumentService
from rigora.application_services.dynamics import DynamicsService
from rigora.domain.content import ContentItem
from rigora.domain.entities import Keyframe
from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy


def smooth_keys(values: list[tuple[float, float]], *, loop: bool) -> tuple[Keyframe, ...]:
    """Use centered derivatives and matching periodic endpoint velocities for numeric channels."""
    result = []
    duration = values[-1][0] - values[0][0]
    for index, (time, value) in enumerate(values):
        before = (
            values[index - 1]
            if index
            else (values[-2][0] - duration, values[-2][1])
            if loop
            else values[0]
        )
        after = (
            values[index + 1]
            if index + 1 < len(values)
            else (values[1][0] + duration, values[1][1])
            if loop
            else values[-1]
        )
        slope = (after[1] - before[1]) / max(1e-9, after[0] - before[0])
        incoming = (time - before[0]) / 3
        outgoing = (after[0] - time) / 3
        result.append(
            Keyframe(
                frame=time,
                value=value,
                interpolation="bezier",
                tangent_in=(-incoming, -incoming * slope),
                tangent_out=(outgoing, outgoing * slope),
            )
        )
    return tuple(result)


def apply_spring(
    document: DocumentService, item: ContentItem, target: str, *, demonstration: bool = False
) -> str:
    """Attach live constraints to a chain or secondary bones, preserving primary animation."""
    from rigora.application_services.content_library import ContentService

    rig = ContentService(document).skeleton(target)
    ids = {b.id for b in rig.bones}
    selected = (
        {target}
        if target in ids
        else {b.id for b in rig.bones if b.name.startswith(("hair.", "tail", "ear.", "cloth"))}
    )
    service = DynamicsService(document)
    if not selected:
        selected = {b.id for b in rig.bones if service.can_spring(b.id)}
    if target in ids:
        pending = True
        while pending:
            expanded = selected | {b.id for b in rig.bones if b.parent_id in selected}
            pending = expanded != selected
            selected = expanded
    if not selected:
        raise ProjectError("Choose a connected bone chain for spring follow-through.")
    parameters = json_copy(item.payload["parameters"])
    allowed = {
        "frequency",
        "damping",
        "inertia",
        "gravity",
        "stretch",
        "squash",
        "strength",
        "max_angle",
        "rotate",
        "translate",
        "enabled",
        "clockwise",
        "counterclockwise",
    }
    if parameters.keys() - allowed:
        raise ProjectError("Spring preset contains unsupported physical settings.")
    group = (item.name + " · " + rig.id[:8])[:100]
    selected = {key for key in selected if service.can_spring(key)}
    service.configure(tuple(b.id for b in rig.bones if b.id in selected), group=group, **parameters)
    if demonstration:
        service.motion_test(tuple(selected))
    else:
        service.activation(group, True, document.animation.pose.frame)
    return rig.id
