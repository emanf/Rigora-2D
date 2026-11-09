"""Integrated original rig tools and dynamic catalogs using only public extension contracts."""

import math
from dataclasses import replace

from rigora.domain.character_recipe import character_preset
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError


def add_chain(request):
    """Create a canonical connected chain, grouped by the host for undo."""
    if request.arguments.get("phase", "press") != "press":
        return None
    document = request.require_document()
    rig = request.service("rig")
    count = request.arguments.get("count", 3)
    length = request.arguments.get("length", 80)
    if type(count) is not int or not 1 <= count <= 32:
        raise ProjectError("Chain count must be an integer from 1 to 32.")
    if type(length) not in (int, float) or not math.isfinite(length) or not 1 <= length <= 10000:
        raise ProjectError("Bone length must be between 1 and 10000 pixels.")
    parent = str(request.arguments.get("parent_id") or "") or None
    if parent:
        node = document.animation.pose.nodes.get(parent)
        if node is None or node.kind != "bone":
            raise ProjectError("The requested parent bone is not available.")
        x, y = transform_point(node.world_matrix, node.length, 0)
    else:
        settings = document.project.scenes[0].settings
        x = request.arguments.get("x", settings.width / 2)
        y = request.arguments.get("y", settings.height / 2)
    created = []
    for index in range(count):
        key = rig.create_bone(
            (x, y), (x + length, y), parent, new_skeleton=parent is None and index == 0
        )
        created.append(key)
        parent, x = key, x + length
    if request.host:
        request.host.select(tuple(created), kind="bones")
        request.host.notify(
            f"Created a connected {count}-bone chain. Undo removes the complete chain."
        )
    return {"bone_ids": created}


def explorer(request):
    """Supply an editable character preset through the live creator catalog."""
    original = character_preset("Little")
    return replace(original, name="Studio explorer", colors={**original.colors, "Hair": "#3b2f28"})


def project_ready(request):
    """Demonstrate an application lifecycle hook without opening a window or altering a project."""
    if request.host:
        request.host.notify("Studio Tools: use the chain tool on the stage or Rig → Studio tools.")


def selection_widget(request, parent):
    """Create a live view that consumes request state instead of looking up a global window."""
    from PySide6.QtWidgets import QLabel

    class SelectionSummary(QLabel):
        """Reflect current selection through the host's ordinary context binding."""

        def rigora_bind(self, current):
            """Keep the label current when switching tabs, selection or editor."""
            count = len(current.state.get("bone_ids", ())) or len(
                current.state.get("selection", ())
            )
            self.setText(f"Selected: {count}")

    widget = SelectionSummary(parent)
    widget.setAccessibleName("Studio selected item count")
    widget.rigora_bind(request)
    return widget


def register(context):
    """Publish native app contributions with deterministic ownership and normal disable cleanup."""
    prefix = context.manifest.id
    context.action(
        prefix + ".chain",
        "Add three-bone chain",
        add_chain,
        placements=("menu:Rig/Studio tools", "surface:object.actions", "context:scene"),
        icon="device_hub",
        when=("project",),
    )
    context.action(
        prefix + ".draw_chain",
        "Draw bone chain",
        add_chain,
        tool=True,
        placements=("toolbar:Studio tools", "menu:Rig/Studio tools"),
        icon="gesture",
    )
    context.widget(
        prefix + ".selection", "Selected item count", selection_widget, surface="object.header"
    )
    context.hook(prefix + ".ready", "project.opened", project_ready)
    context.character_preset(prefix + ".explorer", "Studio explorer", explorer)
    context.content_pack(prefix + ".templates", "Studio templates", "studio.rigpack")
