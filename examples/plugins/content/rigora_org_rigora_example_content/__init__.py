"""Original data-only skeleton pack registered through the public SDK."""

from rigora.sdk import PluginContext, PluginRequest


def register(context: PluginContext) -> None:
    """Expose a declared pack resource to the normal offline content browser."""

    def pack(request: PluginRequest):
        """Resolve the original bundled pack without changing a project or copying files."""
        return context.resource("starter.rigpack")

    context.register("asset_packs", context.manifest.id + ".starter", "Three-joint starter", pack)
