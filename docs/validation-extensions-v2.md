# Extension SDK 2 validation

Date: 2026-10-27.

The extension host now supports native menu/toolbar placements, named editor
surfaces, context commands, arbitrary widget factories, stable navigation and
selection access, lifecycle hooks, live registrations/removal, creator recipe
providers, content categories and background ZIP installation. API 1 remains
supported. Command adaptation moved out of the main window ViewModel into a
Qt-free application service; extension presentation state/events have their own
ViewModel. Views own Qt mounting and cleanup. See [ADR 0012](architecture/0012-extension-host.md).

Resolved review findings:

- Surface destruction could emit through an already deleted Qt registry; native
  validity/shutdown guards now cover owner teardown.
- Rebuilding all contributions discarded unrelated dock state. Identity-based
  reconciliation and unchanged-context discovery preserve running instances.
- Unchanged refresh could reload plugins and background content unnecessarily;
  only changed instances/packs now require rebuilding/reloading.
- Surface toolbar widget actions need explicit removal as well as widget deletion;
  both ownership layers are now cleaned up.
- Disabled/reloaded widgets must not receive late context binds. Binds compare the
  actual active contribution identity and skip removed native objects.
- Closing hooks could create edits after the discard decision. They now run
  before the existing guard, with a test confirming the new undo entry is seen.
- User-input validation errors should allow correction rather than quarantine;
  ProjectErrors remain recoverable while unexpected callback failures quarantine.
- The manager no longer presents callback execution as the primary workflow.
  Native editor controls/panels are primary; the developer console is collapsible.

Validation evidence:

- `build/extensions-v2-release.xml`: **37 passed**, covering integrated examples,
  live action/widget ownership, selection hooks, context arguments, creator cards,
  content categories, one-step undo, refresh retention, ZIP install/refusal,
  installation without trust, close-hook preservation, API 1-compatible features,
  background jobs, existing content behavior, packaging routes and Object Editor.
- `build/extensions-v2-validation-recovery.xml`: **14 passed** in the final focused
  recheck, including recovery after invalid input and genuine callback containment.
  These overlap the broader set and are not additional unique test cases.
- `build/extensions-api1-compatibility.xml`: the original, unchanged API 1 tool
  package loads and executes through the new shared service with a single undo entry.
- Repository-wide Ruff lint/format checks pass; strict mypy passes **207** source files.
- Standard `Build_Rigora.bat --no-pause` passes in compile-only mode. Its report
  still says testing was not requested; application validation was separate.
- `build/extensions-native-ui.json`: actual frozen desktop passes **13** integration
  checks with both external API 2 examples, ordinary menu/toolbar/editor controls,
  connected-chain creation, undo grouping, live selection, context menu, creator
  preset, custom category, diagnostic worker, refresh retention and disable cleanup.
  This used a temporary test-only hook package and isolated saved trust/preferences.
- `build/extensions-v2-bundle.json`: the separate frozen bundle check passes all
  12 codec, resource, worker, MCP, animation, persistence, export, icon and startup
  checks, including exact hashes for all 2,183 bundled assets.
- All GUI checks ran with the offscreen platform, including the compiled app;
  the owner's live desktop preferences and saved enable/trust settings were untouched.

Windows output:
`dist/windows-amd64-20261027-174843-923887/Rigora/Rigora.exe`.
The folder includes disabled Studio Tools and Rig Health Check packages under
`plugins/`; clean install ZIPs are `dist/studio-tools-plugin-2.0.0.zip` and
`dist/rig-health-plugin-2.0.0.zip`. Older output folders were preserved.

Review: **9/10**. Criteria: integrated behavior 2/2, MVVM/shared command boundaries
2/2, data/undo/trust handling 2/2, ownership/lifecycle/native Windows evidence 2/2,
platform/scope coverage 1/2. Native Linux/macOS were not run on this Windows host.
Hooks are documented desktop lifecycle notifications, not interception of every
low-level function. Recipe providers reuse existing component renderers; arbitrary
custom character geometry uses portable packs and new workflows can provide UI.
