# Independent Toolbox docking

Date: 2026-10-28.

Follow-up: a saved-layout startup crash was subsequently reproduced with the
Windows platform plugin and fixed. See
[startup crash validation](validation-toolbox-startup-crash.md) for the corrected
build and native Windows results; the offscreen results below are historical.

**Review: 9/10.** Criteria: attached/floating behavior and pointer handoff **3/3**,
independent panel layout **2/2**, saved placement and data safety **2/2**,
source/native validation **2/3**. Windows source and compiled offscreen checks
passed. Native Linux/macOS and an interactive foreground mouse session were not
run on this host; all testing remained in the background.

## Behavior

- Attached Tools is a real `QDockWidget`, filling its own 80-pixel side column's
  height. Its shared title bar shows Tools and the normal Float control.
- Detaching changes to a 44-pixel frameless tool window sized to its tool column,
  with a rounded six-dot grip. It is no longer a child overlay confined to Preview.
- One pointer gesture continues through the dock/window and caption changes.
  Explicit mouse capture and an application-level drag filter retain movement
  and release events after the original caption hides. Free placement is not
  clamped to Preview, and only an explicit drop near an edge docks the palette.
- Both left/right edge drops restore the title bar and full docked height.
- Tools never shares a tab group with Scene or another panel. Native panel
  dragging keeps independent panels; the public merge command rejects Tools
  groups, and restored legacy groups are repaired. Scene/Inspector tab groups
  already present in older layouts remain supported independently of Tools.
- Qt treats splitting beside a tabbed anchor as adding a tab. Docking now splits
  from Tools first, reorders the resulting independent columns, then restores the
  anchor's unrelated tabs. The Tools record is excluded from those restored peers.
- Placement stores real floating screen coordinates and a coordinate-space marker;
  older preview-local records are migrated. The workspace snapshot is taken after
  migration/repair so Welcome does not replay an obsolete merged state.
- View visibility, user channel widths, Reset Workspace Layout and project data
  continue to use existing workspace behavior. Dragging does not author data or Undo.

## Verification

- `build/toolbox-docking-final.xml`: **20 passing tests**, including actual
  title-bar-to-floating drag handoff, movement outside Preview without snap-back,
  full-height edge docking, forbidden merges, legacy/native tab repair, saved
  floating geometry, hidden visibility, Timeline widths, workspace reset,
  compact UI, binding dialogs, reusable artwork and main toolbar controls.
- All findings from the initial docking runs were resolved. The legacy tabbed
  anchor case also has a separate passing check in `build/toolbox-legacy-layout.xml`.
- Repository Ruff lint passes; **538 files** pass format checking; mypy passes
  **210 source files**.
- `build/toolbox-docking-native-ui.json`: **14 passing checks** in the rebuilt
  Windows application, with a real Creator Panda and actual Qt pointer events.
  Both left and right docking drops, no snap-back, free movement outside Preview,
  independent Scene/Tools, restored native groups, unchanged project identity
  and saved screen position are checked.
- Screenshots: `build/toolbox-docking-native-ui.png`,
  `build/toolbox-attached-native.png`, `build/toolbox-floating-native.png`.
  Visual review confirms the full-height title bar attached and the compact
  rounded grip floating.
- `build/toolbox-docking-bundle-check.json`: packaged dependency, rendering,
  persistence, asset hash, plugin worker, console companion and MCP checks.
- Compile-only output:
  `dist/windows-amd64-20261027-215610-824f21/Rigora/Rigora.exe`.
  Tests were invoked separately; the normal build remains compile-only. The two
  example plugins are present beside the executable with their normal trust rules.

All native harness settings are isolated under `build/`. Temporary validation
plugins are not shipped or enabled in normal sessions. No foreground application
windows were opened and the owner's preferences were not changed.
