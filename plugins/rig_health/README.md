# Rig Health Check · API 2 example plugin

A working read-only SDK example with a dockable report, background scanning and
JSON output. No external Python packages are needed beyond Rigora's own runtime.
Original plugin code is dedicated under CC0-1.0.

Put this complete `rig_health` folder inside Rigora's `plugins/` folder. In the
source checkout it is already there. In the compiled app, copy it beside the EXE
under `plugins/rig_health/`. Open **Plugins → Manage plugins**, Refresh, select
**Rig Health Check**, review its source, acknowledge trust and enable it. Its dock
opens automatically; **Rig → Diagnostics → Rig Health Check** and the Object/Timeline
action strips also open it. The existing **Plugins → Active extensions → Rig Health Check** reopens it.
Create/open a project, click **Scan project**, then select a finding for guidance.
**Copy report** copies JSON, including scene/item IDs.

Checks cover collapsed rest transforms, duplicate bone names, independent roots,
unweighted unpinned vertices in enabled skins, missing/incomplete skin bindings,
and keys outside the union of clips using their timeline. Independent roots and
unused keys are informational because they can be intentional. Unweighted vertices
and duplicate names are warnings, not proof that a rig is broken. Animated poses,
visual quality, external assets and engine export compatibility are not checked.

The static score starts at 100 and deducts 20 per error and 5 per warning, with a
floor of zero. Notes have no penalty. An empty project has no score. All finding
counts are retained; details are capped at 200, prioritizing errors over warnings
and notes. Results become stale when the project changes. Scans use immutable
project snapshots on a worker thread; they do not run again during playback.

The separate-process **Scan rig health** validator is available in the plugin
manager's callback list and through `PluginManager.invoke` / `run_isolated`. It
uses the same analysis without importing Qt. The plugin declares only
`project.read` and `ui`; it performs no repairs, network calls or file writes.
Reading a report does not create undo entries. Disabling removes the dock; queued
results cannot update a destroyed panel. Source changes require Refresh and renewed trust.
