# Prompt 5 validation — character rigging

Windows, 2026-10-17; CPython 3.12.14, PySide6/Qt 6.12.0, pytest 9.1.1,
Ruff 0.17.1 and mypy 1.20.2. Single-agent implementation, review and testing.
No dependencies or format-version changes were introduced.

## Automated and native checks

`Test_Rigora.bat --no-pause`: **147 passed, 1 skipped**, Ruff lint/format clean,
strict mypy clean across 54 source files. The existing symlink test requires
Windows Developer Mode or a Unix host. Local pytest uses normal-user temporary
permissions on this restricted host. Source module/class/function docstring
inspection passed. Batch scripts remain unchanged with CRLF line endings.

Coverage includes rest-world preservation through insertion/reparenting/deletion,
cycles/cross-skeleton rejection, shear rejection, mirrored geometry, templates,
group hiding/locking, undo/redo and project round trips. IK tests cover reachable,
unreachable, coincident and nearly straight targets, bend direction, reach limits,
stretch, FK switching, reflected joints, random/backward evaluation and symmetric
animated targets. Constraint tests cover dependency order, cycles, invalid setup
rollback, pivoted aim, local limits, space switching without a jump, point pinning,
copy/follow transforms and custom solver injection through shared services.

Real Qt tests cover bone drawing, movement and endpoint handles, property edits,
locking/hiding, IK target dragging/editing, FK switching, independent tab state,
undo and Material icon recoloring in dark/light themes. CLI subprocess tests
actively reject Qt imports while evaluating both animation and rigging examples.

Native Windows checks passed templates, contextual properties, IK targets,
save/reopen equivalence and dark/light captures. Framed biped and symmetric-arm
screenshots were inspected under ignored `build/ui-preview/rig-*.png`. Review
resolved pivot-aware aiming/endpoint edits, reflected IK orientation, fixed-point
pin capture, world-preserving space changes and light-theme icon refresh.

The final viewport guide-line adjustment is verified by the focused GUI checks
and static checks, in addition to the full suite above.

## Distribution checks

Offline wheel/source build and isolated installed-package checks are the final
gate. The core run rejects Qt imports; the GUI run borrows the pinned local Qt
runtime while asserting Rigora imports resolve inside the QA environment. Checks
exercise rig authoring/undo, solved target positions, save/reopen, shared CLI JSON,
viewport/inspector integration and packaged fonts/assets.

All distribution checks passed: offline lock consistency, wheel/source builds,
Qt-blocked installed core and native installed GUI. Imports were asserted inside
the QA environments, outside editable source resolution. Packaged Material fonts,
app branding, rig engine/editor and source example/docs were verified. Archive
inspection confirmed cache/environment/build exclusions. The normal batch
launcher evaluated the rigging example at frame 23.5 with six nodes and no warnings.

The full suite above is supplemented by six passing focused rig/animation GUI
checks after the final viewport guide adjustment; Ruff lint/format and strict
mypy passed on that final source as well.

## Scope and retained requirements

Rig authoring, FK, two-bone IK and transform constraints are implemented. The
[rigging guide](rigging.md) documents connected/unit-magnitude/zero-pivot IK joint
requirements, inverse/shear restrictions and rest-only topology preservation.
Skinning, artwork rendering, mesh/FFD deformation and key editing remain later
increments. The owner's FFD/customized-deformation request is retained in
`AGENTS.md` and [the Prompt 6 note](deformation-requirements.md). Prompt 6 has not
been started.
