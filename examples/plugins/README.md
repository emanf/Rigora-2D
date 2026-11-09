# Original SDK examples

These CC0-1.0 examples extend Rigora without modifying its source:

| Folder | Actual behavior | Manifest directory |
| --- | --- | --- |
| `tool` | Click to create an undoable viewport bone | `tool/rigora_org_rigora_example_tool` |
| `deformer` | Apply a sine displacement to imported mesh artwork | `deformer/rigora_org_rigora_example_deformer` |
| `content` | Add an original three-bone rig to the offline content browser | `content/rigora_org_rigora_example_content` |
| `scene_tools` | Menus, toolbar, Object Editor button and a dock using shared Object transforms | `scene_tools/rigora_scene_tools` |

Open **Plugins → Manage plugins → Add development plugin…**, select the inner
directory's `rigora-plugin.json`, review the code/permissions, then explicitly
trust and enable. The SDK never trusts examples automatically.

The `tool`, `deformer` and `content` starters are also independently buildable Python distributions:

```powershell
uv build examples/plugins/tool
uv pip install --python .venv/Scripts/python.exe examples/plugins/tool/dist/rigora_org_rigora_example_tool-1.0.0-py3-none-any.whl
```

Choose either a development origin or an installed origin for the same ID;
duplicate IDs are rejected. Refresh discovery after installation; restart after
upgrading an installed distribution. Development source/resource changes require
refresh and renewed trust. See the [SDK guide](../../docs/plugin-sdk.md).

The generator (`python -m rigora.sdk init DIRECTORY --id org.author.plugin
--kind tool|deformer|content`) writes equivalent independently editable examples.

A larger practical example, [Rig Health Check](../../plugins/rig_health/README.md),
is directly discoverable in the source checkout's `plugins/` folder. It demonstrates
a dockable panel, background analysis, stale-result handling and a headless validator
that shares one read-only report implementation. New plugins remain disabled until
explicitly trusted and enabled.

For the complete setup, development, testing and ZIP installation workflow,
follow [Build a Rigora plugin](../../docs/plugin-development.md). Its Scene Tools
example is distributed as a package folder or ZIP rather than a wheel.
