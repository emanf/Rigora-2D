# Tools layout startup crash

Date: 2026-10-28.

Windows Application events recorded `python.exe` terminating in `ucrtbase.dll`
with `0xc0000409` (the launcher's signed exit code `-1073740791`). Starting
the editor on a separate Windows desktop with a copied workspace reproduced a
native abort inside `ToolboxDock.dock_to`, called by `restore_placement` during
`MainWindow._restore_workspace`. The offscreen renderer alone did not reproduce it.

The serialized Qt layout already contained an independent Tools column. Restoring
the extra placement record removed and split that column again unnecessarily.
The shared docking function now retains an already independent column on the
requested side. Floating palettes, side changes and legacy tab repairs still use
the existing docking behavior. Neither the real preferences nor project data was
modified for diagnosis or validation.

## Checks

- `build/toolbox-crash-final.xml`: 12 passing docking, visibility, saved placement,
  menu and workspace tests, including a new no-resplit regression.
- `build/toolbox-startup-layout.xml`: the expanded regression also passes through
  the full workspace restoration route with the failing layout fixture.
  `tests/fixtures/toolbox-startup-layout.json` contains only UI geometry and panel
  placement, without recent documents or other user data.
- Ruff lint/format checks pass for the modified Python files; mypy passes for
  the modified widget module.
- Compile-only build passed:
  `dist/windows-amd64-20261027-223854-22eb81/Rigora/Rigora.exe`.
- `build/toolbox-startup-windows/run-1.json`, `run-2.json` and `run-3.json`:
  three successful frozen Windows launches, each with a fresh copy of the saved
  workspace, each passing all 14 native UI checks. Reports explicitly confirm
  the `windows` Qt platform. Checks cover startup, full-height independent panels,
  drag detachment, free floating movement, both docking edges, tab repair,
  placement saving and unchanged project identity.
- The native runner creates a separate desktop without activating it, and uses
  isolated preferences and a temporary validation plugin under `build/`.
  It never switches the user's desktop or enables the plugin in normal sessions.
  The compiled native checks run separately from the normal compile-only build.

**Review: 9/10.** Criteria: startup recovery **3/3**, retained layout and data
**2/2**, independent docking behavior **2/2**, validation coverage **2/3**.
Windows native and offscreen rendering were checked; Linux/macOS native window
systems and manual foreground interaction were not tested in this fix.
