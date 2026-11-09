"""Stable turnaround slots and ownership partitions shared by editing and evaluation."""

from collections import defaultdict

from rigora.domain.character_recipe import VIEWS, canonical_view
from rigora.domain.entities import Group
from rigora.domain.project import Scene

VIEW_SLOTS = ("Default", *VIEWS)


def view_partitions(scene: Scene, root: Group) -> dict[str, set[str]]:
    """Return owned view-local sets without changing scene data or bindings.

    Dependent controls inherit saved owner memberships before newly added records
    go to the edited slot, retaining older views with incomplete control lists.
    """
    saved = root.extra.get("view_members", {})
    result = {name: set(saved.get(name, ())) for name in VIEW_SLOTS}
    owned = {root.id}
    children: dict[str, list[str]] = defaultdict(list)
    for record in (*scene.groups, *scene.objects):
        parent = getattr(record, "parent_id", None)
        if parent:
            children[parent].append(record.id)
        if record.extra.get("object_id") == root.id:
            owned.add(record.id)
    pending = list(owned)
    while pending:
        for key in children[pending.pop()]:
            if key not in owned:
                owned.add(key)
                pending.append(key)
    for rig in scene.skeletons:
        if rig.extra.get("object_id") in owned:
            owned.update((rig.id, *(b.id for b in rig.bones)))
    for actor in scene.characters:
        if actor.extra.get("object_id") == root.id or set(actor.object_ids).intersection(owned):
            owned.add(actor.id)
            owned.add(actor.skeleton_id)
            owned.update(
                b.id for r in scene.skeletons if r.id == actor.skeleton_id for b in r.bones
            )
    for mesh in scene.meshes:
        if mesh.object_id in owned:
            owned.update((mesh.id, *(v.id for v in mesh.vertices)))
    for dependency in (*scene.deformers, *scene.constraints):
        if dependency.owner_id in owned:
            owned.add(dependency.id)
            for members in result.values():
                if dependency.owner_id in members:
                    members.add(dependency.id)
    owned.discard(root.id)
    known = set().union(*result.values())
    active = str(root.extra.get("active_view", "Default"))
    result[active if active in VIEW_SLOTS else "Default"].update(owned - known)
    if not root.extra.get("view_slots"):
        source = canonical_view(str(root.extra.get("character_recipe", {}).get("view", "")))
        if source in VIEWS:
            result[source].update(result["Default"])
    return result
