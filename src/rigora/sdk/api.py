"""Versioned plugin manifests, callback contracts and staged registration ownership."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rigora.application_services.documents import DocumentService
from rigora.domain.entities import Record
from rigora.domain.validation import ProjectError, frozen_extra, portable_relative_path, text
from rigora.sdk.host import PluginHost

API_VERSION = "2"
SUPPORTED_API_VERSIONS = ("1", "2")
CAPABILITIES = frozenset(
    {
        "commands",
        "tools",
        "panels",
        "importers",
        "exporters",
        "deformers",
        "constraints",
        "generators",
        "templates",
        "poses",
        "motions",
        "asset_packs",
        "renderers",
        "track_types",
        "inspectors",
        "validators",
        "batch_jobs",
        "services",
        "widgets",
        "hooks",
    }
)
PERMISSIONS = frozenset(
    {"project.read", "project.write", "filesystem", "network", "subprocess", "ui"}
)


def version_tuple(value: str) -> tuple[int, int, int]:
    """Parse the SDK's deliberately bounded stable MAJOR.MINOR.PATCH dependency versions."""
    if not re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}", value):
        raise ProjectError("Plugin versions must use stable MAJOR.MINOR.PATCH numbers.")
    major, minor, patch = (int(part) for part in value.split("."))
    return major, minor, patch


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginDependency(Record):
    """Required plugin identity and an inclusive minimum/exclusive maximum version interval."""

    id: str
    minimum: str = "0.0.0"
    maximum: str | None = None

    def __post_init__(self) -> None:
        """Reject malformed version constraints before any dependent module is imported."""
        Record.__post_init__(self)
        version_tuple(self.minimum)
        if self.maximum is not None and version_tuple(self.maximum) <= version_tuple(self.minimum):
            raise ProjectError("Plugin dependency version interval is empty.")


@dataclass(frozen=True, slots=True, kw_only=True)
class PluginManifest(Record):
    """Data-only manifest; parsing it never imports or grants trust to executable plugin code."""

    id: str
    name: str
    description: str
    version: str
    author: str
    api_version: str
    entry_point: str
    capabilities: tuple[str, ...]
    permissions: tuple[str, ...] = ()
    dependencies: tuple[PluginDependency, ...] = ()
    resources: tuple[str, ...] = ()
    icon: str = "extension"
    license: str = "All rights reserved"
    documentation_url: str = ""
    license_url: str = ""
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate bounded names, declared extension types, permissions and portable resources."""
        Record.__post_init__(self)
        if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+", self.id):
            raise ProjectError("Plugin IDs must be lowercase reverse-DNS identifiers.")
        for value in (self.name, self.version, self.author, self.license):
            text(value, "Plugin metadata")
        version_tuple(self.version)
        if not re.fullmatch(r"[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*:[a-zA-Z_]\w*", self.entry_point):
            raise ProjectError("Plugin entry points must use module:function syntax.")
        if not set(self.capabilities) <= CAPABILITIES or len(set(self.capabilities)) != len(
            self.capabilities
        ):
            raise ProjectError("Plugin declares unknown or duplicate capabilities.")
        if not set(self.permissions) <= PERMISSIONS:
            raise ProjectError("Plugin declares unknown permissions.")
        if len(self.resources) > 256 or len(self.dependencies) > 64:
            raise ProjectError("Plugin manifest exceeds resource/dependency bounds.")
        for resource in self.resources:
            portable_relative_path(resource)
        if len({d.id for d in self.dependencies}) != len(self.dependencies):
            raise ProjectError("Plugin dependencies must be unique.")


@dataclass(frozen=True)
class PluginRequest:
    """One callback request with canonical command services and JSON-compatible arguments."""

    document: DocumentService | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    dispatch: Callable[[str, dict[str, Any]], Any] | None = field(
        default=None, repr=False, compare=False
    )
    state: Mapping[str, Any] = field(default_factory=dict)
    host: PluginHost | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Freeze caller-owned nested arguments without cloning the active document session."""
        object.__setattr__(self, "arguments", frozen_extra(self.arguments))
        object.__setattr__(self, "state", frozen_extra(self.state))

    def service(self, name: str) -> Any:
        """Resolve a canonical application service for this request's current document."""
        from rigora.application_services.plugin_commands import document_service

        return document_service(name, self.require_document())

    def require_document(self) -> DocumentService:
        """Resolve the active session or report an actionable no-project error."""
        if self.document is None or self.document.project is None:
            raise ProjectError("Create or open a project before running this plugin command.")
        return self.document

    def run_command(self, key: str, arguments: dict[str, Any] | None = None) -> Any:
        """Dispatch a panel button command against the current tab with host undo and refresh."""
        if self.dispatch is None:
            raise ProjectError("This request has no desktop command dispatcher.")
        return self.dispatch(key, arguments or {})


@dataclass(frozen=True)
class Contribution:
    """One owned extension callback plus inert presentation/parameter metadata."""

    plugin_id: str
    kind: str
    id: str
    name: str
    handler: Callable[..., Any]
    metadata: Mapping[str, Any]


class PluginContext:
    """Stage registrations until activation succeeds; own resources and cleanup callbacks."""

    def __init__(self, manifest: PluginManifest, root: Path) -> None:
        """Bind one plugin's metadata and source root without exposing a global document."""
        self.manifest, self.root = manifest, root.resolve()
        self.contributions: list[Contribution] = []
        self.cleanups: list[Callable[[], None]] = []
        self.changed: Callable[[], None] = lambda: None

    def register(
        self, kind: str, key: str, name: str, handler: Callable[..., Any], **metadata: Any
    ) -> None:
        """Stage a namespaced declared capability; duplicate contributions fail atomically."""
        if kind not in self.manifest.capabilities:
            raise ProjectError(f"Plugin did not declare capability {kind!r}.")
        placements = metadata.get("placements", ())
        if not isinstance(placements, (tuple, list)):
            raise ProjectError("Action placements must be a sequence of named UI locations.")
        for placement in placements:
            if not isinstance(placement, str):
                raise ProjectError("Action placements must be text.")
            prefix, separator, target = placement.partition(":")
            if (
                prefix not in ("menu", "toolbar", "surface", "context")
                or not separator
                or not target
            ):
                raise ProjectError("Use menu:, toolbar:, surface: or context: action placements.")
        if set(metadata.get("when", ())) - {
            "project",
            "selection",
            "bones",
            "mesh",
            "object",
            "scene",
            "playing",
        }:
            raise ProjectError("Unknown action context condition.")
        if (
            kind in ("tools", "panels", "inspectors", "renderers", "widgets")
            and "ui" not in self.manifest.permissions
        ):
            raise ProjectError("UI contributions must declare the ui permission.")
        if not key.startswith(self.manifest.id + ".") or not callable(handler):
            raise ProjectError("Contributions need a plugin-namespaced ID and callable handler.")
        if any(c.id == key for c in self.contributions):
            raise ProjectError("Plugin contribution IDs must be unique.")
        text(name, "Contribution name")
        self.contributions.append(
            Contribution(self.manifest.id, kind, key, name, handler, frozen_extra(metadata))
        )
        self.changed()

    def action(
        self,
        key: str,
        name: str,
        handler: Callable[..., Any],
        *,
        placements: tuple[str, ...] = (),
        icon: str = "extension",
        shortcut: str = "",
        when: tuple[str, ...] = (),
        tool: bool = False,
    ) -> None:
        """Declare one command/tool shared by menus, toolbars, editor buttons and context menus.

        Placement prefixes are menu:, toolbar:, surface: and context:. Named surfaces
        are owned by views; callbacks use request state and canonical services for edits.
        """
        self.register(
            "tools" if tool else "commands",
            key,
            name,
            handler,
            placements=placements,
            icon=icon,
            shortcut=shortcut,
            when=when,
        )

    def widget(self, key: str, name: str, factory: Callable[..., Any], *, surface: str) -> None:
        """Mount a desktop widget factory in a named surface, adopting its Qt ownership."""
        text(surface, "Extension surface")
        self.register("widgets", key, name, factory, surface=surface)

    def hook(self, key: str, event: str, handler: Callable[..., Any]) -> None:
        """Subscribe to an application event; disabling removes the subscription automatically."""
        text(event, "Hook event")
        self.register("hooks", key, event, handler, event=event)

    def character_preset(self, key: str, name: str, provider: Callable[..., Any]) -> None:
        """Supply a CharacterRecipe to the creator's live preset catalog."""
        self.register("templates", key, name, provider, template_type="character_recipe")

    def content_pack(self, key: str, name: str, resource: str) -> None:
        """Publish a declared portable pack in the shared character/template/motion library."""
        self.resource(resource)
        self.register("asset_packs", key, name, lambda request: self.resource(resource))

    def remove(self, key: str) -> None:
        """Withdraw one owned contribution at runtime and notify attached hosts."""
        self.contributions[:] = [item for item in self.contributions if item.id != key]
        self.changed()

    def resource(self, relative: str) -> Path:
        """Resolve a declared existing resource without permitting path escape from its plugin."""
        if relative not in self.manifest.resources:
            raise ProjectError("Plugin resource was not declared in its manifest.")
        target = (self.root / relative).resolve()
        if not target.is_relative_to(self.root) or not target.is_file():
            raise ProjectError("Plugin resource is missing or outside its source directory.")
        return target

    def on_shutdown(self, callback: Callable[[], None]) -> None:
        """Register cleanup in activation order; the host executes cleanup in reverse order."""
        if not callable(callback):
            raise ProjectError("Plugin cleanup must be callable.")
        self.cleanups.append(callback)
