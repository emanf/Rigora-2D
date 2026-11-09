# Visible startup workspace

Date: 2026-10-28.

Welcome no longer hides the workspace docks. The default horizontal order is
Scene, Tools, the center Welcome/Preview area, then Assets; Timeline stays below.
Scene and Tools remain independent full-height panels. Document switches no
longer restore a separate obsolete dock snapshot over changes made on Welcome.
Saving and Reset Workspace Layout now use the same panel state with or without
an open project.

The supplied legacy layout reproduced a second failure on the native Windows
renderer: Scene and Tools were logically shown but their dock slots remained at
negative coordinates, leaving an empty column. Attempting to split that restored
tree also caused a native access violation. Existing profiles therefore migrate
once to the default panel arrangement before their old native dock tree is
loaded. The `workspace_panels_version` preference records that migration; later
explicit visibility and placement choices persist normally. Main window geometry
and internal panel settings remain available. The diagnosis used copied settings;
the real preferences were not edited or cleared.

## Validation

- `build/workspace-startup-recovery.xml`: four targeted tests pass for immediate
  Welcome visibility/order, Welcome-only layout persistence and reset, legacy
  recovery, and the earlier no-resplit startup regression.
- `build/workspace-visible-panels-final.xml`: 23 tests pass for panel menus,
  floating/docked persistence, native tab repair, Tools dragging, Timeline widths,
  and Object Editor isolation/restoration.
- Ruff lint and format checks pass for the changed Python files; mypy passes for
  the modified MainWindow module.
- Compile-only build passed:
  `dist/windows-amd64-20261027-235250-9a84b3/Rigora/Rigora.exe`.
- `build/workspace-visible-panels-windows/run-1.json` through `run-3.json`:
  three successful compiled Windows launches, each passing 18 UI checks.
  The first starts with a copy of the supplied legacy preferences; subsequent
  launches reuse the migrated profile saved by the previous run. The reports
  explicitly confirm the `windows` Qt platform. Checks include visible panels
  before creating a project, correct Scene/Tools/center order, Welcome visibility
  choices surviving project creation, shared panels across Welcome and Preview,
  both docking edges, legacy tab repairs and unchanged project identity.
- Visual inspection of
  `build/workspace-visible-panels-windows/startup-welcome.png` confirms the actual
  compiled startup arrangement. Native tests ran on a separate, never-activated
  Windows desktop. No windows were opened over the user's game.

**Review: 9/10.** Criteria: startup visibility and recovery **3/3**, independent
panel order **2/2**, persistent layout choices **2/2**, validation coverage **2/3**.
Windows native and offscreen checks passed; Linux/macOS native window systems
and manual foreground interaction were not tested.
