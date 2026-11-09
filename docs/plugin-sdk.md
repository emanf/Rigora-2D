# Public plugin SDK · API 2 with API 1 compatibility

See the [extension SDK 2 guide](extensions.md) for integrated menus, toolbars,
editor widgets, hooks, ZIP installation, shared services and dynamic catalogs.
The callback and engine contracts below remain supported.

For a complete first package with menus, a toolbar, a panel and tests, follow
[Build a Rigora plugin](plugin-development.md).

Deformer registrations can supply optional `animation_channels` metadata to name
and group their nested numeric parameters in **Add tracks**. The same scalar
engine contract handles keying, curves, undo, save/load and headless evaluation.
See [timeline.md](timeline.md#developers) for the complete working contract/example.

Python extensions use the shared command services, engine and desktop.
Plugins are optional and work offline. New discoveries start disabled.
Open **Plugins → Manage plugins** to inspect metadata, permissions, source path,
fingerprint and diagnostics. Review the Python and resources, check the trust
box, then enable. Dependencies need their own explicit trust decisions first.
Disable removes active contributions and dependent plugins; project records and
undo history remain intact. Missing deformers/constraints produce evaluation
warnings; missing custom numeric track samplers stop that clip with an explicit
error, preserving its keys for later recovery.

## Create and try an extension

From the repository, after `uv sync --locked --extra gui`:

```powershell
uv run python -m rigora.sdk init .\my-plugin --id org.example.bonestamp --kind tool
```

`--kind deformer` creates a working sine displacement solver; `--kind content`
creates an original three-bone `.rigpack`. The generator refuses an existing
destination. It writes a normal Python package, manifest, README and packaging
configuration. No code is installed or executed by generation.

Three complete original CC0 examples are in
[`examples/plugins`](../examples/plugins/README.md). In the manager, choose **Add
development plugin…** and select the example package's `rigora-plugin.json`.
Adding a source never trusts it. After trust/enable:

1. The tool appears in the plugin toolbar, Plugins menu and command palette.
   Select **Stamp a bone**, then click the viewport. Each stamp is one undoable
   canonical bone. Ordinary navigation still supports middle/Space panning.
2. Import artwork, select its mesh, then choose **Sine wave** from Plugins →
   Active extensions. The geometric stage runs in actual viewport/playback
   evaluation. Its numeric `amount` parameter supports existing deformation keys.
3. The content example adds **Three-joint original** to the normal content
   browser, with scratch preview and the same validated Apply workflow.

To distribute a generated plugin:

```powershell
uv build .\my-plugin
uv pip install --python .venv\Scripts\python.exe .\my-plugin\dist\YOUR_PLUGIN.whl
```

Install into the **same Python environment** as Rigora. Refresh discovery. A
package must expose the `rigora.plugins` entry-point group and include its
manifest at `<top_level_package>/rigora-plugin.json`. The manifest entry point
must match the installed entry point. The generated `pyproject.toml` supplies
these rules. Rigora does not download/install Python distributions from its UI.

Local plugins can also live directly under
`<preferences-directory>/plugins/<plugin-directory>/rigora-plugin.json`.
Native Windows/Linux builds additionally discover
`<application-directory>/plugins/<plugin-directory>/rigora-plugin.json`, beside
the executable. macOS uses `Rigora.app/Contents/Resources/plugins`. Refresh the
plugin manager after copying a plugin there. App-local and per-user plugins use
the same trust checks, and duplicate IDs are disabled. Use the per-user folder
when the app directory is read-only; settings and logs always remain in the profile.
Generated packages put the manifest inside their Python package: add that inner
directory in development mode, or copy it as the local plugin directory.
Preferences normally live in `%LOCALAPPDATA%\Rigora\workspace.json` on Windows;
`RIGORA_PREFERENCES_PATH` overrides this location for portable/test profiles.

## Manifest

```json
{
  "id": "org.example.bonestamp",
  "name": "Bone stamp",
  "description": "Stamp an original bone at a scene coordinate.",
  "version": "1.0.0",
  "author": "Example author",
  "api_version": "2",
  "entry_point": "rigora_org_example_bonestamp:register",
  "capabilities": ["tools"],
  "permissions": ["project.read", "project.write", "ui"],
  "dependencies": [],
  "resources": [],
  "icon": "device_hub",
  "license": "CC0-1.0",
  "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
  "documentation_url": ""
}
```

IDs use lowercase reverse DNS, with letters, digits and underscores in segments.
Stable versions use `MAJOR.MINOR.PATCH`. The host supports API `1` and `2`; new packages should use `2`. Dependencies are `{ "id": "org.example.base", "minimum":
"1.0.0", "maximum": "2.0.0" }`: inclusive minimum, exclusive optional maximum.
Missing/version-mismatched dependencies, cycles, duplicate origins and incompatible
APIs are rejected before importing activation modules. Unknown capabilities,
malformed entry points and unsafe resource paths are invalid.

`icon` names a bundled Material glyph. `resources` lists portable relative paths;
`context.resource(name)` resolves only declared existing files inside the plugin.
Icons, resources and third-party content need appropriate distribution rights.
Licensing metadata grants no permission beyond the author's actual license.

## Lifecycle and registration

```python
from rigora.sdk import PluginContext, PluginRequest


def validate(request: PluginRequest) -> dict[str, int]:
    """Count canonical skeletons without mutating the active project."""
    document = request.require_document()
    return {"rigs": len(document.project.scenes[0].skeletons)}


def register(context: PluginContext) -> None:
    """Publish an owned validator after explicit trust and compatibility checks."""
    context.register("validators", context.manifest.id + ".count", "Count rigs", validate)
    # Register resource cleanup with context.on_shutdown(callable) when needed.
```

The entry point receives `PluginContext`. Registration stages callbacks and
publishes all of them only when activation succeeds. IDs must start with the
plugin ID plus `.`; every ID must be unique. Kind must appear in `capabilities`.
Tools/panels/inspectors/renderers additionally require the `ui` declaration.
`context.register(kind, id, name, callback, **metadata)` freezes JSON metadata;
common metadata is `icon` and numeric solver `parameters` defaults.

Register cheap factories/callbacks, never widgets, threads or project mutations at
module import. In particular, desktop restoration discovers/activates plugins
before the Qt application exists. Construct widgets only inside a panel factory.
`context.on_shutdown(callback)` registers reverse-order cleanup. Alternatively,
return one cleanup callable from `register`. Cleanup must stop owned timers/jobs
and release external resources; it must tolerate already-closed widgets.
Failed registration releases all its resources and rolls back newly activated
dependencies. Existing active dependencies remain active.

Local imports use a private namespace. Use relative imports for sibling modules;
do not add global `sys.path` entries. Disabling/reloading releases those private
modules. Installed package modules use Python's normal import cache: **restart
Rigora after upgrading an installed wheel**. Development Refresh preserves unchanged
active instances and unloads changed/removed origins and their active dependents.

## Callback contracts

`PluginRequest.document` is the current `DocumentService`, or `None` when no
project is selected or `project.read` was not declared. `require_document()`
raises an actionable `ProjectError` when unavailable. `arguments` is deeply
frozen JSON data. Do not retain a request/document across project switches;
resolve it for each callback. Use canonical application services and validated
commands, never replace project collections directly in plugin code.

| Kind | Callback and host integration |
| --- | --- |
| `commands`, `importers`, `exporters`, `generators`, `templates`, `poses`, `motions` | `(request) -> result`. Run from Active extensions, command palette or manager JSON arguments. Use the existing rig, mesh, animation, content or document services for real edits/import/export. Returning a record alone does not apply it. |
| `tools` | `(request) -> result`. Activated viewport pointer tool. Arguments contain `phase` (`press`, `move`, `release`, `cancel`), scene-space `x`, `y` and `ctrl`. Cancel has no meaningful coordinate. Keep transient preview state separate; commit through commands. The supplied stamp example commits on press. |
| `panels`, `inspectors` | `(request, parent: QWidget) -> QWidget`. Adopted into a dock with standard custom chrome or an inspector tab. Optional widget method `rigora_bind(request)` receives project changes; keep it read-only and fast. Close/disabling removes owned widgets. UI code may depend on optional PySide6; the engine must not. |
| `renderers` | `(request, painter: QPainter, pose: ScenePose \| None) -> None`. Draw a viewport overlay in device/widget coordinates; request arguments supply frame, zoom and offsets. Pose is omitted without project access. Painter state is saved/restored for each callback. This is a viewport extension, not a video-export pipeline. |
| `deformers` | `(context: DeformationContext) -> tuple[(x, y), ...]`. Return finite mesh-local points with unchanged count; use `context.points` and `context.scalar(name, default)`. Active extensions adds a real stage to the selected mesh using metadata parameter defaults. Existing intensity/masks/animation remain authoritative. |
| `constraints` | `(rule: Constraint, context: ConstraintContext) -> None`. Read targets with `context.node`, publish frame-only transforms with `local`, `world` or `position`. Metadata supplies default parameters. The manager accepts `owner_id`, optional `target_id` and `parameters`; a menu action defaults to the selected bone. Do not mutate authored records during evaluation. |
| `track_types` | `(track: Track, frame: float) -> float \| None`. Set `track.extra["sampler"]` to the contribution ID. Supports finite numeric channels over existing canonical property paths. Playback, blends and graph display use this callback. Keys remain ordinary editable scalar keys; custom curves are sampled for graph display. Arbitrary new serialized value types are outside API 1. |
| `asset_packs` | `(request) -> pathlib.Path`. Return a declared `.rigpack` resource. Active packs are included in the offline content browser; normal pack validation and compatibility rules apply. |
| `validators`, `batch_jobs`, `services` | `(request) -> result`. Callable from the manager or Python SDK. Data-only variants can use optional subprocess execution. Long-running work must use a worker, not block a Qt slot. |

Generic desktop callbacks declaring `project.write` run inside one
`DocumentService.command_group`; failure restores the baseline and successful
commands create one undo entry. A declaration is **not enforcement against
arbitrary Python**. Panel button handlers that call services directly own their
undo grouping and UI notification; prefer `request.run_command(contribution_id,
arguments)` from a panel button. That desktop dispatcher resolves the current
tab, groups undo and refreshes the application through the same ViewModel as the
normal action registry. It raises `ProjectError` on failure; a panel should
display that error in its own controls. Only desktop widget/overlay requests
provide this dispatcher; data jobs use canonical services. `rigora_bind` is a
refresh hook, not an editing callback.
Do not mutate documents from worker threads.

Qt-free consumers use the same host:

```python
from rigora.application_services.plugins import PluginManager
from rigora.infrastructure.preferences import PreferencesStore
from rigora.sdk import PluginRequest

plugins = PluginManager(PreferencesStore())
plugins.discover()
# Trust must result from an explicit human decision about inspected source.
plugins.restore()
try:
    plugins.attach(document)
    result = plugins.invoke("org.example.validator.count", PluginRequest(document))
finally:
    plugins.shutdown()
```

`contributions(kind=None)` lists active records. `invoke` is for request callbacks;
engine/presentation-specific signatures are host adapters via `call_raw`.
Headless runtime/CLI evaluation attaches the same trusted engine extensions.

## Reliability, diagnostics and isolation

Python `Exception`/`SystemExit` in registration, callbacks and cleanup are contained
and logged. A failing callback is quarantined until disable/re-enable or reload;
other plugins remain available. Renderer failures stop repaint retries. Native
crashes, infinite loops and arbitrary side effects in trusted in-process Python
cannot be contained by exception handling.

The manager shows recent diagnostics; `<preferences-directory>/plugins.log` is a
rotating 1 MiB log with one backup. Metadata inspection bounds manifests to 64
KiB and owned code/resources to 2,048 files/128 MiB. Trust fingerprints cover the
manifest, owned Python files and declared resources. Changes require a new review
and explicit trust. External dependencies and undeclared data are **not covered**
by that fingerprint; trust the complete environment and distribution source.

For data-only jobs, validators, generators and services:

```python
from rigora.application_services.plugin_jobs import run_isolated

result = run_isolated(plugins, "org.example.validator.count", request, timeout=30)
```

The desktop manager runs this on a background worker. A fresh process verifies
trusted fingerprints and receives JSON arguments plus an optional immutable
project snapshot. Child mutations do not return to the active document. Embedded
asset bytes, Qt widgets and arbitrary Python objects do not cross this boundary.
Inputs are limited to 8 MiB, JSON output to 4 MiB and timeout to at most 300 s.
Exceptions, hard child exits and timeouts report an error without killing the
parent; timeout terminates that child. Callbacks must return JSON-compatible
values. Normal stdout is captured so it cannot corrupt the response.

This separates **job execution**, not registration: trusted plugins first register
in the host. It is not an OS sandbox, does not revoke filesystem/network access,
and does not promise to terminate descendant processes created by plugin code.

Start with `rigora --safe-mode` or `RIGORA_SAFE_MODE=1` to inspect projects with
all executable plugins disabled. Safe mode retains saved enable preferences.
Discovery reads metadata only; it never imports newly discovered code. No
network access, plugin auto-install or remote execution is required.

## Stability policy and limits

API 2 covers `rigora.sdk` contracts, namespaced registration, the documented
callback signatures, canonical records and the application/engine service methods
used by shipped examples. Underscore-prefixed internals and Qt workspace
implementation details are private. Compatible additions retain existing
contracts, including API 1 packages; incompatible changes require a new manifest
API major. Plugin version ranges are independent of Rigora's application version.

Plugins supply their own optional dependencies and licenses. Commands/renderers
must be fast; arbitrary plugin native code is not isolated. Canonical services are
shared by the Python, CLI and MCP adapters. Registering a plugin command does not
automatically expose a new MCP tool; use the documented dispatch contracts.

Production service names available through `request.service(name)` are `artwork`,
`audio`, `contacts`, `paths`, `game`, `cameras`, `camera_shots`, `state_machines`
and `export_preflight`, in addition to `rig`, `scene`, `mesh`, `skin`, `characters`,
`animation`, `appearance`, `deformation`, `face`, `bindings` and `scene_attachments`.
Scene attachment services provide whole-Object following, held pickup/release keys
and reusable local grip points; see [Scene attachments](scene-attachments.md).
Each binds to the
request's document. Long scans/bakes belong on a fork/worker with revision checks;
the factory does not move work off-thread automatically. Animation playback emits
the `animation.event` hook with typed event data. Payloads are data only; plugins
choose behavior explicitly. See [production workflows](production-workflows.md).
