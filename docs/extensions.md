# Extension SDK 2

Plugins contribute native menus, toolbars, editor actions, context menus, widgets,
viewport tools, docks, inspectors, hooks, character presets and reusable content.
Existing deformers, constraints, track samplers, overlays and offline jobs remain
supported. API 1 packages remain compatible.

Start with the [step-by-step plugin tutorial](plugin-development.md) and its
runnable Scene Tools example. This page is the integrated-control reference.

## Install and activate

**Plugins → Manage plugins → Install ZIP…** installs one package folder containing
`rigora-plugin.json` directly inside it. Background installation validates bounded
portable entries and metadata, refuses duplicates/overwrites and never executes
or trusts code. Review the source, then trust and enable it. Copying packages into
app/user `plugins/` folders and selecting development manifests are also supported.

Refresh retains unchanged active instances. Changed, missing, duplicate or
incompatible origins and their active dependents unload. Source changes require
renewed trust. Disable removes contributions while retaining authored data.
Safe mode disables executable plugins. Normal use happens through editor controls;
the collapsed Developer console is for validators and data callbacks.

## Integrated controls

```python
def add_bone(request):
    return request.service("rig").create_bone((100, 100), (200, 100))


def register(context):
    context.action(
        context.manifest.id + ".bone",
        "Add example bone",
        add_bone,
        placements=(
            "menu:Rig/My tools",
            "toolbar:My tools",
            "surface:object.actions",
            "context:scene",
        ),
        icon="device_hub",
        when=("project",),
    )
```

Declare `commands`, `project.read` and `project.write` for this example. Set
`tool=True` for a viewport tool (`tools` capability and `ui` permission).
Tools receive `phase`, scene-space `x`, `y` and `ctrl`. Stamps commit during press;
drag tools own their transient preview and commit strategy.

One action can appear in multiple locations. `menu:` creates nested/new top-level
menus. `toolbar:` targets a named surface or creates an owned toolbar. `surface:`
adds an icon button to a named layout. `context:` adds clicked-item arguments.
`shortcut=` uses normal shortcuts; conflicts are diagnosed rather than overridden.
`when=` combines AND conditions: `project`, `selection`, `bones`, `mesh`, `object`,
`scene`, `playing`. The shared service also checks these conditions.

| Surface | Location |
| --- | --- |
| `main` | Main toolbox (`toolbar:main`) |
| `object.actions` | Object Editor layer actions |
| `object.header` | Object Editor name/view header |
| `timeline.actions` | Timeline editing controls |
| `assets.actions` | Project Assets action strip |
| `character.creator` | Creator header, while its dialog exists |

Context targets: `scene`, `layers`, `timeline`, `assets`. Click data includes
`item_id`, `asset_id`, `track_ids` or `frame` where applicable.

## Widgets and desktop access

`context.widget(key, name, factory, surface="object.header")` mounts a QWidget
returned by `factory(request, parent)` (`widgets` and `ui` required). Import Qt
inside the factory. The host adopts/removes the widget. Existing dock/inspector
contracts remain supported. Optional `rigora_bind(request)` receives authored and
context changes; keep it cheap. Playback does not rebuild these controls.

Desktop requests with `ui` permission expose `PluginHost`:

- `execute(id, arguments=None)`: extension commands or built-in actions without
  arguments. Use canonical services for parameterized project edits.
- `available_commands()`: live command IDs, labels, enabled state and shortcuts.
- `select(ids, kind="scene"|"bones")`: navigate selection through ViewModels.
- `show_panel(id)`: reveal a contributed dock. `notify(text)`: nonmodal status.
- `surfaces.targets`: view-owned UI slots. Custom views can publish more slots
  with `surfaces.register(id, layout_or_toolbar)`; native owner destruction
  automatically withdraws them.

Headless/isolated requests have no desktop host. Use services/command dispatch
for authored edits rather than changing widgets to simulate data. Trusted Python
has ordinary process access; manifest permissions are not an OS sandbox.

## State, services and hooks

`request.state` is immutable JSON: `project_id`, `document_id`, `selection`,
`bone_ids`, `mesh_id`, `editor`, `frame`, `playing`. Resolve the current request;
do not retain a document across tab switches.

`request.service(name)` supports `rig`, `scene`, `mesh`, `skin`, `characters`,
`animation`, `appearance`, `deformation`, `face`, `bindings`. Mutating commands execute inside
one undo transaction and refresh through the ViewModel; exceptions roll back.
Python clients use the same Qt-free `PluginCommandService.execute`. The existing
`PluginManager.invoke` remains the lower-level callback interface.

`context.hook(key, event, handler)` subscribes a callback (`hooks` capability).
Requests include `arguments["event"]` and event data. Notifications: `app.ready`,
`app.closing`, `project.opened`, `project.closed`, `project.activated`,
`project.changed`, `selection.changed`, `editor.changed`, `timeline.frame_changed`,
`creator.opened`. Project open/close includes the affected `document_id`. Closing
runs before unsaved-change decisions, including canceled attempts. Notifications
do not intercept saves/exports. Recursive delivery of the same event is suppressed;
unexpected failures are quarantined. User-input ProjectErrors remain recoverable.
Move heavy work to workers over immutable snapshots.

Helpers and generic `register` work after activation. `context.remove(id)`
withdraws an owned contribution; unrelated panels retain their instances/state.
Use `context.on_shutdown(callback)` for resources outside Qt ownership. Arbitrary
trusted native crashes cannot be contained by Python exception handling.

## Dynamic catalogs

`context.character_preset(key, name, provider)` supplies a `CharacterRecipe`
(`templates` capability). Creator combo/card choices update live using the same
assembler and replaceable parts as built-ins. Presets customize existing recipe
components; they do not add new component renderer implementations.

`context.content_pack(key, name, declared_resource)` adds a `.rigpack` to the
normal offline library (`asset_packs`). Packs support custom character artwork,
rigs, templates, poses and motions. Custom categories appear in both library
filters. Arbitrary geometry belongs in packs; custom creation workflows can add
widgets/commands. Saved geometry stays editable after its plugin is disabled.

## Architecture and examples

`sdk/` owns Qt-free contracts; `application_services/plugin_commands.py` owns
canonical dispatch/undo; `presentation/viewmodels/extensions.py` owns extension
state/events; `presentation/extension_surfaces.py` and `plugin_workspace.py` own
the Qt adapters. Domain/engine remain Qt-free with one project/animation system.

Working packages: [Studio Tools](../plugins/studio_tools/README.md) and
[Rig Health Check](../plugins/rig_health/README.md). The generator emits integrated
tools. See [manifest/callback contracts](plugin-sdk.md) for additional details.
