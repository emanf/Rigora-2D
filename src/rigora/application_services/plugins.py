"""Metadata-only discovery, explicit code trust and failure-contained plugin lifecycle."""

import hashlib
import importlib
import importlib.metadata
import importlib.util
import logging
import logging.handlers
import sys
import tempfile
import types
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, cast

from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError
from rigora.engine.constraints import ConstraintSolver
from rigora.engine.deformation import DeformerSolver
from rigora.engine.sampling import TrackSampler
from rigora.infrastructure.preferences import PreferencesStore
from rigora.infrastructure.project_storage import _decode
from rigora.resources import application_root
from rigora.sdk.api import (
    API_VERSION,
    SUPPORTED_API_VERSIONS,
    Contribution,
    PluginContext,
    PluginManifest,
    PluginRequest,
    version_tuple,
)


@dataclass
class PluginState:
    """One discovered executable origin, its code fingerprint and current diagnostic state."""

    manifest: PluginManifest
    root: Path
    fingerprint: str
    installed: bool = False
    error: str = ""
    namespace: str = ""


def inspect_plugin(path: Path, *, installed: bool = False) -> PluginState:
    """Read bounded metadata and fingerprint owned Python/resources without importing code."""
    if path.stat().st_size > 65536:
        raise ProjectError("Plugin manifests must be smaller than 64 KiB.")
    manifest = PluginManifest.from_dict(_decode(path.read_bytes()))
    root = path.parent.resolve()
    names = {"rigora-plugin.json", *manifest.resources}
    for source in root.rglob("*.py"):
        if not any(
            part in (".venv", "__pycache__", ".git") for part in source.relative_to(root).parts
        ):
            names.add(source.relative_to(root).as_posix())
        if len(names) > 2048:
            raise ProjectError("Plugin source exceeds the 2,048-file inspection bound.")
    hasher, total = hashlib.sha256(), 0
    for name in sorted(names):
        source = (root / name).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            raise ProjectError("Plugin source/resources must remain inside the plugin directory.")
        total += source.stat().st_size
        if total > 128 * 1024 * 1024:
            raise ProjectError("Plugin source/resources exceed 128 MiB.")
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(source.read_bytes())
    return PluginState(manifest, root, hasher.hexdigest(), installed)


class PluginManager:
    """Own trusted activations and namespaced registries; manifests are never a sandbox."""

    def __init__(self, preferences: PreferencesStore, *, safe_mode: bool = False) -> None:
        """Initialize disabled discovery and an optional all-plugins-off startup mode."""
        self.preferences = preferences
        self.root = preferences.path.parent / "plugins"
        self.safe_mode = safe_mode
        self.states: dict[str, PluginState] = {}
        self.contexts: dict[str, PluginContext] = {}
        self.diagnostics: list[str] = []
        self.on_changed: Callable[[], None] = lambda: None
        self._wrappers: dict[str, Callable[..., Any]] = {}
        self._known_solvers: set[str] = set()
        self._failed: set[str] = set()
        self._logger: logging.Logger | None = None

    def report(self, plugin_id: str, message: str) -> None:
        """Retain bounded UI diagnostics and an owned rotating local log without root handlers."""
        self.diagnostics.append(f"{plugin_id}: {message}")
        del self.diagnostics[:-200]
        try:
            if self._logger is None:
                self.preferences.path.parent.mkdir(parents=True, exist_ok=True)
                logger = logging.getLogger(f"rigora.plugins.{id(self)}")
                logger.setLevel(logging.INFO)
                logger.propagate = False
                handler = logging.handlers.RotatingFileHandler(
                    self.preferences.path.parent / "plugins.log",
                    maxBytes=1024 * 1024,
                    backupCount=1,
                    encoding="utf-8",
                )
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                logger.addHandler(handler)
                self._logger = logger
            self._logger.warning("%s: %s", plugin_id, message)
        except OSError:
            pass

    def trusted(self, state: PluginState) -> bool:
        """Match explicit trust to inspected code/resources, revoking it when contents change."""
        values = self.preferences.data.get("plugin_trust", {})
        return isinstance(values, dict) and values.get(state.manifest.id) == state.fingerprint

    def discover(
        self,
        extra_dirs: tuple[Path, ...] = (),
        *,
        installed: bool = True,
        allowed_roots: tuple[Path, ...] | None = None,
    ) -> None:
        """Inspect local/development manifests and package entry-point metadata without imports."""
        previous_states = self.states
        self.states = {}
        paths: list[tuple[Path, bool, str | None]] = []
        development = self.preferences.data.get("plugin_development_dirs", [])
        development = development if isinstance(development, list) else []
        dirs = (*extra_dirs, *(Path(p) for p in development[:32] if isinstance(p, str)))
        paths.extend((p / "rigora-plugin.json", False, None) for p in dirs)
        for root in dict.fromkeys((self.root, application_root() / "plugins")):
            if root.is_dir():
                paths.extend(
                    (p, False, None) for p in sorted(root.glob("*/rigora-plugin.json"))[:128]
                )
        if installed:
            try:
                for package_entry in importlib.metadata.entry_points(group="rigora.plugins"):
                    if package_entry.dist is None:
                        continue
                    module = package_entry.module.split(".")[0]
                    manifest = Path(
                        str(package_entry.dist.locate_file(f"{module}/rigora-plugin.json"))
                    )
                    paths.append((manifest, True, package_entry.value))
            except (OSError, ValueError, ImportError) as error:
                self.report("discovery", str(error))
        seen: set[Path] = set()
        for path, packaged, entry in paths:
            if allowed_roots is not None and not any(
                path.resolve().is_relative_to(root) for root in allowed_roots
            ):
                continue
            if path.resolve() in seen:
                continue
            seen.add(path.resolve())
            try:
                state = inspect_plugin(path, installed=packaged)
                if entry is not None and state.manifest.entry_point != entry:
                    raise ProjectError("Package entry point and manifest entry point differ.")
                if state.manifest.id in self.states:
                    self.states[
                        state.manifest.id
                    ].error = "Duplicate plugin ID; all matching origins are disabled."
                    continue
                if state.manifest.api_version not in SUPPORTED_API_VERSIONS:
                    state.error = (
                        f"Requires plugin API {state.manifest.api_version}; "
                        f"host provides {API_VERSION}."
                    )
                self.states[state.manifest.id] = state
            except (ProjectError, OSError, ValueError, RecursionError) as error:
                self.report(str(path), str(error))
        invalid = set()
        for key in self.contexts:
            old, fresh = previous_states[key], self.states.get(key)
            if (
                fresh is None
                or fresh.error
                or (fresh.root, fresh.fingerprint, fresh.installed)
                != (old.root, old.fingerprint, old.installed)
            ):
                invalid.add(key)
            else:
                fresh.namespace = old.namespace
        # Dependents cannot retain registrations backed by an unloaded dependency.
        while more := {
            key
            for key in self.contexts
            if key not in invalid
            and any(dep.id in invalid for dep in self.contexts[key].manifest.dependencies)
        }:
            invalid.update(more)
        for key in reversed(tuple(self.contexts)):
            if key in invalid:
                self._unload(key, previous_states[key])
        self.on_changed()

    def add_development(self, root: Path) -> None:
        """Remember a user-selected source directory without trusting or importing its plugin."""
        inspect_plugin(root / "rigora-plugin.json")
        values = self.preferences.data.get("plugin_development_dirs", [])
        values = [v for v in values if isinstance(v, str)] if isinstance(values, list) else []
        self.preferences.data["plugin_development_dirs"] = list(
            dict.fromkeys([*values, str(root.resolve())])
        )[-32:]
        self.preferences.save()
        self.discover()
        self.restore()

    def install_archive(self, archive: Path) -> Path:
        """Install a bounded ZIP without executing/trusting code or overwriting an existing folder.

        Storage work may run on a worker. Discovery and UI notifications belong to
        the caller's main thread after this operation returns successfully.
        """
        from rigora.infrastructure.plugin_archives import read_plugin_archive

        folder, files = read_plugin_archive(archive)
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / folder
        if destination.exists():
            raise ProjectError("This plugin folder already exists; existing files were preserved.")
        with tempfile.TemporaryDirectory(
            prefix=".rigora-install-", dir=self.root.parent
        ) as temporary:
            stage = Path(temporary) / folder
            stage.mkdir()
            for relative, data in files.items():
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            state = inspect_plugin(stage / "rigora-plugin.json")
            if any(s.manifest.id == state.manifest.id for s in self.states.values()):
                raise ProjectError(
                    "This plugin ID is already discovered; remove the duplicate origin first."
                )
            stage.rename(destination)
        return destination

    def trust(self, plugin_id: str) -> None:
        """Record a deliberate approval of the exact currently inspected plugin source."""
        state = self.states[plugin_id]
        fresh = inspect_plugin(state.root / "rigora-plugin.json", installed=state.installed)
        if fresh.fingerprint != state.fingerprint:
            raise ProjectError("Plugin files changed; refresh before trusting this version.")
        values = self.preferences.data.get("plugin_trust", {})
        values = dict(values) if isinstance(values, dict) else {}
        values[plugin_id] = state.fingerprint
        self.preferences.data["plugin_trust"] = values
        self.preferences.save()

    def _order(self, plugin_id: str, visiting: set[str], result: list[str]) -> None:
        """Validate all required dependencies and trust before importing any activation module."""
        if plugin_id in visiting:
            raise ProjectError("Plugin dependency cycle detected.")
        state = self.states.get(plugin_id)
        if state is None:
            raise ProjectError(f"Missing plugin dependency: {plugin_id}.")
        if state.error or not self.trusted(state):
            raise ProjectError(state.error or f"Explicit trust is required for {plugin_id}.")
        fresh = inspect_plugin(state.root / "rigora-plugin.json", installed=state.installed)
        if fresh.fingerprint != state.fingerprint:
            raise ProjectError(f"Plugin {plugin_id} changed; refresh and review trust again.")
        visiting.add(plugin_id)
        for dependency in state.manifest.dependencies:
            other = self.states.get(dependency.id)
            if other is None:
                raise ProjectError(f"Missing plugin dependency: {dependency.id}.")
            version = version_tuple(other.manifest.version)
            if (
                version < version_tuple(dependency.minimum)
                or dependency.maximum is not None
                and version >= version_tuple(dependency.maximum)
            ):
                raise ProjectError(f"Incompatible dependency version: {dependency.id}.")
            self._order(dependency.id, visiting, result)
        visiting.remove(plugin_id)
        if plugin_id not in result:
            result.append(plugin_id)

    def enable(self, plugin_id: str, *, persist: bool = True) -> None:
        """Activate a validated dependency order, rolling back new registrations on failure."""
        if self.safe_mode:
            raise ProjectError("Safe mode keeps all executable plugins disabled.")
        order: list[str] = []
        self._order(plugin_id, set(), order)
        activated = []
        try:
            for key in order:
                if key in self.contexts:
                    continue
                state = self.states[key]
                context = PluginContext(state.manifest, state.root)
                try:
                    module_name, function_name = state.manifest.entry_point.split(":")
                    if state.installed:
                        module = importlib.import_module(module_name)
                    else:
                        namespace = "_rigora_plugin_" + state.fingerprint[:24]
                        state.namespace = namespace
                        if (
                            module_name.split(".")[0] == state.root.name
                            and (state.root / "__init__.py").is_file()
                        ):
                            spec = importlib.util.spec_from_file_location(
                                namespace,
                                state.root / "__init__.py",
                                submodule_search_locations=[str(state.root)],
                            )
                            if spec is None or spec.loader is None:
                                raise ProjectError("Cannot prepare the local plugin package.")
                            package = importlib.util.module_from_spec(spec)
                            sys.modules[namespace] = package
                            spec.loader.exec_module(package)
                            suffix = module_name.partition(".")[2]
                            module = (
                                importlib.import_module(f"{namespace}.{suffix}")
                                if suffix
                                else package
                            )
                        else:
                            package = types.ModuleType(namespace)
                            package.__path__ = [str(state.root)]
                            sys.modules[namespace] = package
                            importlib.invalidate_caches()
                            module = importlib.import_module(f"{namespace}.{module_name}")
                    callback = getattr(module, function_name)
                    if not callable(callback):
                        raise ProjectError("The plugin entry point is not callable.")
                    cleanup = callback(context)
                    if cleanup is not None:
                        context.on_shutdown(cleanup)
                except (Exception, SystemExit):
                    self._cleanup(context)
                    self._remove_modules(state)
                    raise
                self.contexts[key] = context
                context.changed = partial(self._registrations_changed, key)
                for contribution in context.contributions:
                    self._wrappers[contribution.id] = partial(self.call_raw, contribution.id)
                    if contribution.kind in ("deformers", "constraints", "track_types"):
                        self._known_solvers.add(contribution.id)
                activated.append(key)
                self.report(key, "Enabled")
        except (Exception, SystemExit) as error:
            for key in reversed(activated):
                self._unload(key)
            self.report(plugin_id, f"Activation failed: {type(error).__name__}: {error}")
            raise ProjectError(f"Plugin activation failed: {error}") from error
        if persist:
            self._save_enabled()
        self.on_changed()

    def _registrations_changed(self, plugin_id: str) -> None:
        """Publish live registrations without reactivating or disturbing other plugin instances."""
        context = self.contexts.get(plugin_id)
        if context is None:
            return
        prefix = plugin_id + "."
        for key in tuple(self._wrappers):
            if key.startswith(prefix):
                self._wrappers.pop(key, None)
                if not any(c.id == key for c in context.contributions):
                    self._failed.discard(key)
        for contribution in context.contributions:
            self._wrappers[contribution.id] = partial(self.call_raw, contribution.id)
            if contribution.kind in ("deformers", "constraints", "track_types"):
                self._known_solvers.add(contribution.id)
        self.on_changed()

    def contributions(self, kind: str | None = None) -> tuple[Contribution, ...]:
        """Return activated registrations in dependency/activation order, optionally filtered."""
        return tuple(
            c
            for context in self.contexts.values()
            for c in context.contributions
            if kind is None or c.kind == kind
        )

    def call_raw(self, key: str, *arguments: Any) -> Any:
        """Contain Python callback failures and quarantine a failing contribution until reload."""
        contribution = next((c for c in self.contributions() if c.id == key), None)
        if contribution is None or key in self._failed:
            raise ProjectError(f"Plugin contribution is unavailable or failed: {key}.")
        try:
            return contribution.handler(*arguments)
        except ProjectError:
            # Invalid user inputs remain recoverable; unexpected code failures are quarantined.
            raise
        except (Exception, SystemExit) as error:
            self._failed.add(key)
            self.report(contribution.plugin_id, f"{key} failed: {type(error).__name__}: {error}")
            raise ProjectError(f"Plugin {contribution.name} failed: {error}") from error

    def invoke(self, key: str, request: PluginRequest | None = None) -> Any:
        """Dispatch a documented request callback through the shared failure boundary."""
        contribution = next((c for c in self.contributions() if c.id == key), None)
        if contribution is None:
            raise ProjectError("The plugin contribution is not active.")
        request = request or PluginRequest()
        if (
            request.document is not None
            and "project.read" not in self.states[contribution.plugin_id].manifest.permissions
        ):
            raise ProjectError("Plugin did not declare project.read permission.")
        return self.call_raw(key, request)

    def attach(self, document: DocumentService) -> None:
        """Update plugin solvers while retaining other injections and authored records."""
        deformers = {
            k: v for k, v in document.deformer_solvers.items() if k not in self._known_solvers
        }
        constraints = {
            k: v for k, v in document.constraint_solvers.items() if k not in self._known_solvers
        }
        samplers = {
            k: v for k, v in document.track_samplers.items() if k not in self._known_solvers
        }
        deformers.update(
            {
                c.id: cast(DeformerSolver, self._wrappers[c.id])
                for c in self.contributions("deformers")
            }
        )
        constraints.update(
            {
                c.id: cast(ConstraintSolver, self._wrappers[c.id])
                for c in self.contributions("constraints")
            }
        )
        samplers.update(
            {
                c.id: cast(TrackSampler, self._wrappers[c.id])
                for c in self.contributions("track_types")
            }
        )
        document.configure_extensions(
            constraints=constraints,
            deformers=deformers,
            samplers=samplers,
            channel_metadata={
                c.id: c.metadata.get("animation_channels", {})
                for c in self.contributions("deformers")
            },
        )

    def _cleanup(self, context: PluginContext) -> None:
        """Release every registered resource even when another cleanup callback fails."""
        for callback in reversed(context.cleanups):
            try:
                callback()
            except (Exception, SystemExit) as error:
                self.report(context.manifest.id, f"Cleanup failed: {error}")

    def _remove_modules(self, state: PluginState) -> None:
        """Release private local plugin modules without removing shared installed dependencies."""
        if state.namespace:
            for name in tuple(sys.modules):
                if name == state.namespace or name.startswith(state.namespace + "."):
                    del sys.modules[name]

    def _unload(self, key: str, previous: PluginState | None = None) -> None:
        """Remove registrations before cleanup, preventing calls into an unloading plugin."""
        context = self.contexts.pop(key, None)
        if context:
            context.changed = lambda: None
            for contribution in context.contributions:
                self._wrappers.pop(contribution.id, None)
                self._failed.discard(contribution.id)
            self._cleanup(context)
            state = previous or self.states.get(key)
            if state:
                self._remove_modules(state)

    def disable(self, plugin_id: str) -> None:
        """Disable a plugin and its active dependents, preserving project extension records."""
        dependents = [
            key
            for key in self.contexts
            if any(d.id == plugin_id for d in self.states[key].manifest.dependencies)
        ]
        for key in dependents:
            self.disable(key)
        self._unload(plugin_id)
        self._save_enabled()
        self.on_changed()

    def _save_enabled(self) -> None:
        """Persist explicit enable preferences independently of transient runtime shutdown."""
        self.preferences.data["plugin_enabled"] = list(self.contexts)
        self.preferences.save()

    def restore(self) -> None:
        """Restore only unchanged, explicitly trusted enabled plugins; failures remain optional."""
        enabled = self.preferences.data.get("plugin_enabled", [])
        for key in enabled if isinstance(enabled, list) and not self.safe_mode else ():
            try:
                self.enable(key, persist=False)
            except (ProjectError, KeyError) as error:
                self.report(str(key), str(error))

    def shutdown(self) -> None:
        """Release active plugins in reverse order without erasing saved enable preferences."""
        for key in reversed(tuple(self.contexts)):
            self._unload(key)
        if self._logger is not None:
            for handler in self._logger.handlers[:]:
                self._logger.removeHandler(handler)
                handler.close()
            self._logger = None
