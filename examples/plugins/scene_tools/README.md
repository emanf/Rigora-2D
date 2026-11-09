# Scene Tools tutorial

This CC0 API 2 example adds a menu command, toolbar, Object Editor button, Scene
context action and dock panel. It moves selected Object roots through the shared
transform service, with one Undo entry and ordinary binding behavior.

Add `rigora_scene_tools/rigora-plugin.json` through **Plugins → Manage plugins →
Add development plugin…**, review the source, trust it, then enable it. Select an
Object and use **Object → Scene tools → Move Objects right 24 px**. Open
**View → Plugin panels → Scene Tools panel** to choose another distance.

The package is `rigora_scene_tools/`, not this outer example directory. ZIP that
package folder for **Install ZIP…**, or copy it under the app/user `plugins/`
directory. Do not enable two copies with the same plugin ID.

Follow the complete [plugin tutorial](../../../docs/plugin-development.md) for
setup, callback contracts, testing, reloads, dependencies and distribution.
