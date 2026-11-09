"""Original pointer-driven stamp using the public viewport-tool contract."""

from rigora.application_services.rigging import RigService
from rigora.engine.sampling import number
from rigora.sdk import PluginContext, PluginRequest


def stamp(request: PluginRequest):
    """Create one undoable bone at the pressed scene coordinate; other pointer phases are inert."""
    if request.arguments.get("phase") != "press":
        return None
    x, y = number(request.arguments["x"]), number(request.arguments["y"])
    key = RigService(request.require_document()).create_bone((x, y), (x + 100, y + 20))
    return {"bone_id": key}


def register(context: PluginContext) -> None:
    """Register an original bone-stamp tool with a bundled Material glyph."""
    context.register(
        "tools", context.manifest.id + ".stamp", "Stamp a bone", stamp, icon="device_hub"
    )
