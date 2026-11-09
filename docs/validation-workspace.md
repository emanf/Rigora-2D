# Prompts 2â€“3 validation

Date: 2026-10-17. Host: Windows, CPython 3.12.14, PySide6/Qt 6.12.0.

## Delivered

- Complete neutral dark/light workspace themes and persisted dock layout.
- Custom title bar with integrated menus, compact borderless branding, Material
  window controls, native system menu, resize and maximize hit testing.
- Multiple project tabs with independent models, histories and canvas views;
  duplicate-path reuse, reorder, save-all, cycling and guarded closure.
- Welcome/recent projects, searchable commands, scoped shortcuts, dockable
  hierarchy, inspector, source browser and honest timeline empty states.
- Cursor-anchored zoom, middle/Space-drag pan, fit, grid and checkerboard.
- Complete Qt-free authoring model: layers, groups, objects/transforms, assets,
  characters, skeletons/bones, meshes/vertices/weights, slots/attachments,
  clips/timelines/tracks/keys, deformers/constraints and inert plugin data.
- Version 2 packages, embedded and relative external sources, bounded safe
  resolution, explicit format 1 migration, atomic saves, backups and recovery.
- Reversible field deltas, compound commands and rollback-capable transactions.
- Packaged root assets, original transparent app icon, schemas, format
  specification and a complete original data-contract example.
- Purpose-focused docstrings for every source module, class and function,
  reinforced by durable project instructions in AGENTS.md.

Animation evaluation, artwork rendering and the corresponding editing tools
remain later milestones. Their controls are explicitly disabled.

## Checks

| Check | Result |
| --- | --- |
| `Test_Rigora.bat --no-pause` | 89 passed, 1 skipped; all four stages passed |
| Ruff lint and format | Passed; 60 checked/formatted Python files |
| Strict mypy | Passed; 35 source files |
| Source documentation audit | No undocumented modules, classes or functions |
| Batch script line endings | Both launchers verified CRLF |
| `Run_Rigora.bat --no-pause --headless --log-level WARNING` | Exit 0, valid JSON, current milestone identity |
| `uv lock --check --offline --cache-dir .uv-cache` | Lock consistent |
| `uv build --offline --cache-dir .uv-cache` | Wheel and source distribution built |
| Native Windows captures | Final dark, light and welcome layouts inspected |
| Native frame checks | Resize/system/min/max styles, corner and maximize hit tests passed |
| Maximize/restore/minimize/close | Passed; maximized geometry matched available screen, 1920 Ã— 1040 |
| Installed wheel core | Full model, source bytes, save/open/undo/redo passed with Qt imports blocked |
| Installed wheel GUI | Material font, branding, source package and multiple tabs passed |
| Distribution contents | Assets/license, examples, schemas, tools and launchers included; caches/environments excluded |

The single skipped test requires creating a real symlink, unavailable under this
Windows account without Developer Mode or symlink privileges. Ordinary relative
path, traversal and changed/missing source cases passed. The resolver follows
existing symlinks and checks the resolved path remains under the project root.

Regression coverage includes complete model round trips, preserved optional
fields and stable IDs, invalid types/references/cycles/geometry, finite values,
transaction rollback, structural sharing, conflict-safe history, format 1
migration without source mutation, portable embedded assets, linked source
integrity, package corruption, interrupted/racing saves, backups/recovery,
independent tabs, save-all, canceled closure, theme recoloring and text-field
shortcut isolation.

Tests use isolated preferences and do not alter real desktop settings. This host
requires the normal user token for pytest private temporary-folder ACL access;
normal tests do not require administrator privileges. GUI wheel checks borrow
the already-installed, pinned Qt libraries; the Rigora package and assets resolve
from the installed wheel, independently of the editable source package.

Initial foundation work used the earlier requested implementation/review pair.
Both were stopped after the owner changed the preference. All remaining prompt
2â€“3 implementation, review, fixes and validation used one agent in this chat.
Interactive Snap flyouts, multiple-monitor DPI transitions, other platforms,
assistive technologies and production-scale importing remain acceptance work.
See `limitations.md` for scope and platform limits.

## Window chrome follow-up

The subsequent UI increment adds a closable Welcome tab, centered same-surface
menus, rounded toolbar state containers, shared custom dialog/floating-panel
captions, and native maximize state feedback with standard red Close states.
Current complete check result: **101 passed, 1 skipped**, Ruff lint/format passed,
strict mypy passed (37 source files). See `ui-chrome.md`.

Welcome closure is covered through its close button and Ctrl+W, reopening from
View, project reordering with Welcome absent, retained canvas views, and an empty
workspace after closing all tabs.

## About dialog

The dedicated About window presents the app icon, version, creator contacts,
capability summary, runtime/platform details and attribution. Its footer remains
visible while details scroll in small windows. The reproduction test failed on
the prior generic message box and now passes through the real Help action.
Latest checks: **104 passed, 1 skipped**, Ruff lint/format passed, strict mypy
passed (38 source files). Native Windows dark/light, compact sizing and
maximize/restore/close checks passed; captures were visually inspected.
