"""Qt-free structural contract for optional desktop navigation supplied to UI plugins."""

from typing import Any, Protocol


class PluginHost(Protocol):
    """Expose commands, selection, dock navigation and view-owned extension surface discovery.

    The host exists only in a desktop request with the ui permission. Widgets may
    use surfaces to compose UI; project edits use request.service() and command
    dispatch so the canonical document, notifications and undo stay synchronized.
    """

    surfaces: Any

    def execute(self, key: str, arguments: dict[str, Any] | None = None) -> Any:
        """Execute an application action or an active extension command."""
        ...

    def available_commands(self) -> tuple[dict[str, Any], ...]:
        """Describe current application and extension actions for discovery."""
        ...

    def select(self, ids: tuple[str, ...], *, kind: str = "scene") -> None:
        """Set scene or bone selection through presentation commands."""
        ...

    def show_panel(self, key: str) -> None:
        """Show an existing extension panel by stable ID."""
        ...

    def notify(self, message: str) -> None:
        """Publish a nonmodal status message."""
        ...
