# Build a Rigora plugin

This tutorial builds an extension that appears in the Object menu, its own
toolbar, the Object Editor action strip, a Scene context menu, and a dock panel.
The complete, runnable package is in
[`examples/plugins/scene_tools`](../examples/plugins/scene_tools/README.md).

Use Extension API **2** for new plugins. API 1 remains supported for existing
packages. Application versions, plugin versions, and the extension API version
are separate compatibility numbers.

## 1. Prepare a development environment

Install Python 3.12 and uv, then run these commands from the Rigora repository:

```sh
uv sync --locked --extra gui
uv run --no-sync rigora
```

On Windows, `Run_Rigora.bat` starts that environment after setup. Developing a
plugin does not require compiling Rigora. Use a separate test project so an
unfinished extension cannot change your working animation.

For the walkthrough, copy `examples/plugins/scene_tools` to your own development
folder. Keep the inner `rigora_scene_tools` package intact. Alternatively, start
with one of the SDK generators:

```sh
uv run --no-sync python -m rigora.sdk init ../my-bone-tool --id org.example.bone_tools --kind tool
```

`--kind deformer` generates a sine-displacement solver; `--kind content` generates
a reusable rig pack. The generator refuses an existing destination. It writes
files without installing, trusting, or running the plugin.

## 2. Understand the package layout

```text
scene_tools/                   Outer development folder
  README.md
  rigora_scene_tools/          The package users install
    rigora-plugin.json
    __init__.py
```

The plugin folder contains a manifest and Python source. It can also contain
relative-imported modules, icons, `.rigpack` resources, and other declared data.
Do not copy an entire virtual environment into the package.

| File | Purpose |
| --- | --- |
| `rigora-plugin.json` | Metadata, entry point, capabilities, permissions, dependencies, resources |
| `__init__.py` | Registration and callbacks for this example |
| Additional `.py` files | Separate panels, tools, solvers, or utilities using relative imports |
| `.dll`, `.pyd`, `.so`, `.dylib` | Optional native dependencies; these are not standalone Rigora plugins |

A Python package works in both source and compiled Rigora when its dependencies
are available. Native dependencies must match the operating system, CPU, Python
ABI, and relevant Qt version. A compiled app has its own embedded runtime;
installing a wheel into an unrelated system Python does not add it to that app.

## 3. Read the manifest

The tutorial package declares:

```json
{
  "id": "org.rigora.example.scene_tools",
  "name": "Scene Tools tutorial",
  "description": "Move selected Objects through shared commands, menus, toolbars and a dock panel.",
  "version": "1.0.0",
  "author": "Rigora SDK examples",
  "api_version": "2",
  "entry_point": "rigora_scene_tools:register",
  "capabilities": ["commands", "panels"],
  "permissions": ["project.read", "project.write", "ui"],
  "license": "CC0-1.0",
  "resources": []
}
```

Use a lowercase reverse-DNS ID that you control for a distributed plugin, such
as `org.yourstudio.scene_tools`. Update the `PREFIX` constant in the source when
changing the manifest ID. Contribution IDs must begin with that ID plus a dot.

`entry_point` means “import this module and call this function.” Here, Rigora
loads `rigora_scene_tools` and calls `register(context)`. The function registers
contributions; it does not receive a permanent active document.

Declare every capability you register. Declare `ui` for desktop controls,
`project.read` for document access, and `project.write` for edits. Other supported
permissions are `filesystem`, `network`, and `subprocess`. These declarations help
users review a plugin; trusted Python still has normal process access and is not
an operating-system sandbox.

## 4. Use application services for an edit

The complete `nudge` callback is in the example's
[`__init__.py`](../examples/plugins/scene_tools/rigora_scene_tools/__init__.py).
Its important operation is:

```python
scene = request.service("scene")
scene.part_edit = scene.sprite_edit = True
scene.transform(tuple(keys), dx=distance)
```

The callback reads the current selection from `request.state["selection"]`,
resolves selected character parts to their owning Object, removes duplicate
roots, validates the requested distance, and uses the shared transform service.
Selecting several parts of one Object therefore moves that Object once.

The desktop dispatcher owns the command transaction. Successful edits create
one Undo entry and refresh the workspace. An exception rolls the edit back.
Raise `ProjectError` for an actionable input problem; do not silently apply a
partial edit or assign a replacement directly to `document.project`.

Resolve the document and services inside each callback. Requests are snapshots
of the current context; keeping an old document reference in a global variable
would edit the wrong project after a tab switch.

## 5. Place one command in several locations

The example registers one command with four placements:

```python
context.action(
    PREFIX + ".nudge",
    "Move Objects right 24 px",
    nudge,
    placements=(
        "menu:Object/Scene tools",
        "toolbar:Scene tools",
        "surface:object.actions",
        "context:scene",
    ),
    icon="arrow_forward",
    when=("project", "selection"),
)
```

`menu:` creates nested menus, `toolbar:` uses a named toolbar, `surface:` mounts
an icon button in an existing editor layout, and `context:` adds a context-menu
entry. `when` conditions are combined with AND and also checked during direct
dispatch. A shortcut is optional; conflicts are reported instead of overriding
an existing command. Icons use the bundled Material glyph names.

| Placement | Existing location |
| --- | --- |
| `toolbar:main` | Main toolbox |
| `surface:object.actions` | Object Editor layer actions |
| `surface:object.header` | Object Editor name/view header |
| `surface:timeline.actions` | Timeline editing controls |
| `surface:assets.actions` | Assets action strip |
| `surface:character.creator` | Character Creator header while the dialog exists |
| `context:scene`, `context:layers`, `context:timeline`, `context:assets` | Corresponding item menus |

Context menus can supply clicked-item arguments such as `item_id`, `asset_id`,
`track_ids`, or `frame`. Read those arguments when the action needs the clicked
item rather than the current selection.

## 6. Add a panel

The example registers a panel factory and an action that reveals it:

```python
context.register("panels", PREFIX + ".panel", "Scene Tools", panel)
context.action(
    PREFIX + ".show",
    "Scene Tools panel",
    show_panel,
    placements=("menu:View/Plugin panels",),
    icon="tune",
)
```

The factory has the signature `panel(request, parent) -> QWidget`. Construct the
widget with the supplied parent. Import PySide6 inside the factory, not at module
import or in `register`: plugins may register before QApplication exists, and
headless clients must still be able to discover the package.

The tutorial panel provides a distance field, a command button, and an error
label. Its `rigora_bind(request)` method receives the latest context after
project/selection changes. Keep that method fast and read-only.

Panel buttons should call:

```python
self.request.run_command(PREFIX + ".nudge", {"distance": self.distance.value()})
```

This resolves the current document, checks availability, groups Undo, and refreshes
through the host. Catch `ProjectError` in the panel and show it in the panel's
controls. Calling services directly from a button bypasses that desktop dispatch
contract unless you also implement its transaction and refresh responsibilities.

Use `context.widget(..., surface="object.header")` for a small editor widget
instead of a dock. The callback still receives `(request, parent)` and follows
the same ownership and rebind rules.

## 7. Load and trust the development package

1. Open **Plugins → Manage plugins**.
2. Choose **Add development plugin…** and select the inner package's
   `rigora-plugin.json`.
3. Select **Scene Tools tutorial** in the manager.
4. Review its metadata, source path, permissions, and source code.
5. Mark it trusted, then enable it.
6. Select an Object in the Scene.
7. Choose **Object → Scene tools → Move Objects right 24 px**.
8. Open **View → Plugin panels → Scene Tools panel** and try another distance.

Discovery does not run new code. Trust applies to the inspected source/resource
fingerprint. Editing the plugin requires Refresh, reviewing the changed files,
and trusting the new fingerprint. Disable/re-enable after editing; installed
wheels use Python's module cache and require an application restart after upgrade.

Do not load the same ID through development mode and an installed folder at the
same time. Duplicate IDs are disabled rather than choosing one arbitrarily.

## 8. Check behavior before distributing

For the tutorial, verify these concrete results:

1. Without a project or selection, the move action is unavailable.
2. With one Object selected, the command changes its X position by 24 pixels.
3. One Undo restores the complete previous pose; Redo reapplies it.
4. Moving a character carries its feet, bones, and clothing together.
5. Selecting several parts belonging to one Object does not multiply the movement.
6. A locked Object reports an error and remains unchanged.
7. An invalid distance changes neither the project nor Undo history.
8. Switching projects updates the panel's request and selection count.
9. Disabling the plugin removes its menus, toolbar, and dock without removing
   authored Objects or animation.

The repository tests the example with:

```sh
uv run --no-sync pytest tests/test_plugin_tutorial.py
```

Run GUI checks with `QT_QPA_PLATFORM=offscreen`. On PowerShell set it using
`$env:QT_QPA_PLATFORM = 'offscreen'`; on Linux/macOS prefix the command with
`QT_QPA_PLATFORM=offscreen`. Automated tests use temporary preferences; they must
not trust development code in a user's normal profile.

## 9. Package an installable ZIP

Zip the **inner package folder**, with the manifest one level below the ZIP root:

```text
SceneTools-1.0.0.zip
  rigora_scene_tools/
    rigora-plugin.json
    __init__.py
```

From the repository, this Python command packages the shipped example:

```sh
python -c "import shutil; shutil.make_archive('SceneTools-1.0.0', 'zip', 'examples/plugins/scene_tools')"
```

Remove `__pycache__`, `.pyc`, temporary files, secrets, and virtual environments
before packaging your own copy. The installer rejects links, encrypted entries,
path escapes, duplicate/case-alias paths, multiple plugin roots, more than 2,048
entries, or more than 128 MiB of compressed/expanded content. The manifest is
bounded to 64 KiB; individual declared resources must be portable relative paths.

Users install through **Manage plugins → Install ZIP…**, then review, trust and
enable the extension. Installation refuses an existing destination; disable and
remove the old package before installing a replacement with the same folder/ID.
Back up any plugin-owned settings first.

## 10. Install beside a source or compiled app

| Application | Local package location |
| --- | --- |
| Source checkout | `<repository>/plugins/rigora_scene_tools/` |
| Windows/Linux bundle | `<application-directory>/plugins/rigora_scene_tools/` |
| macOS bundle | `Rigora.app/Contents/Resources/plugins/rigora_scene_tools/` |
| Per-user install | `<preferences-directory>/plugins/rigora_scene_tools/` |

The per-user folder works without modifying an installed application or its
signature. On Windows the normal preferences directory is `%LOCALAPPDATA%/Rigora`.
`RIGORA_PREFERENCES_PATH` can select another profile. Other platforms use the
configured XDG directory or `~/.config/Rigora`; this is the current implementation,
not the macOS Application Support convention.

Python distribution plugins can expose a `rigora.plugins` entry point and ship
their manifest inside their top-level package. Install the wheel into the same
environment as **source Rigora**, restart, then refresh. For compiled apps,
prefer a self-contained package folder; third-party binary dependencies require
separate target-specific testing. Rigora does not run pip inside its UI.

## 11. Add hooks, presets, content, and tools

- **Lifecycle hooks:** declare `hooks`, then use
  `context.hook(PREFIX + ".changed", "project.changed", callback)`. Other events
  include `app.ready`, `app.closing`, `project.opened`, `project.closed`,
  `project.activated`, `selection.changed`, `editor.changed`,
  `timeline.frame_changed`, and `creator.opened`. Notifications are not arbitrary
  save/export interceptors. Avoid edits from refresh hooks that would repeatedly
  trigger another refresh.
- **Character presets:** declare `templates`; register a provider with
  `context.character_preset(...)`. Return a `CharacterRecipe` using the existing
  assembler. This adds presets, not a new part-rendering engine.
- **Content packs:** declare `asset_packs`, add the `.rigpack` filename to
  `resources`, and use `context.content_pack(...)`. Custom categories and
  character artwork enter the normal offline library.
- **Viewport tools:** declare `tools` and `ui`, then use `context.action(...,
  tool=True)`. Read `phase`, scene-space `x`/`y`, and `ctrl`; handle press, move,
  release and cancel. Keep previews transient and commit a drag once on release.
- **Solvers and tracks:** use the documented `deformers`, `constraints`, or
  `track_types` callback contracts. Keep them Qt-free and deterministic. Return
  new finite geometry, retain vertex counts, and do not mutate authored records
  while evaluating a frame.

[Studio Tools](../plugins/studio_tools/README.md) demonstrates presets, content,
tools and hooks. The [deformer starter](../examples/plugins/deformer/README.md)
demonstrates numeric solver parameters and animation channels.

## 12. Handle resources, dependencies and cleanup

List owned files in `resources` and resolve them with `context.resource(name)`.
Use relative imports for sibling Python modules. Do not edit `sys.path`, rely on
Downloads, or read files relative to the current working directory.

`dependencies` lists **other Rigora plugins**, for example
`{"id": "org.example.base", "minimum": "1.0.0", "maximum": "2.0.0"}`.
Minimum is inclusive and maximum is exclusive. Python packages are a separate
installation/deployment concern. External dependencies are not included in the
plugin source fingerprint.

The host adopts contributed widgets and removes their controls on disable. Own
timers, threads, subscriptions, or files that outlive a callback need cleanup:
register it with `context.on_shutdown(callback)` or return a cleanup callable
from `register`. Stop jobs and tolerate already-closed widgets. Keep heavy work
off the GUI thread and never mutate a live document from a worker. Data-only
validators can use the bounded isolated-job API; child mutations do not return
to the active document.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Plugin is missing | Select the inner manifest, press Refresh, and check its source path. |
| Enable is unavailable | Review trust, API version, dependencies, duplicate IDs and diagnostics. |
| Contribution registration fails | Match `PREFIX`, declared capabilities, permissions and unique IDs. |
| Menu exists but is disabled | Inspect `when` conditions and current `request.state`. |
| Panel edits the wrong tab | Use the latest `rigora_bind` request and `run_command`; remove retained document references. |
| Import fails in a compiled app | Check that dependencies match the embedded Python/OS/architecture. |
| Code changes do not appear | Refresh, review and re-trust; restart after replacing an installed wheel. |
| An extension prevents startup | Launch `rigora --safe-mode` or set `RIGORA_SAFE_MODE=1`, then inspect/disable it. |

The manager displays recent diagnostics; `plugins.log` is a rotating log beside
the profile. Unexpected callback failures are quarantined; Python exceptions do
not isolate native crashes or infinite loops in trusted in-process code.

Continue with the [callback reference](plugin-sdk.md) and
[Extension API 2 contracts](extensions.md) for the complete supported surfaces,
events, samplers, services, isolation limits, and versioning policy.
