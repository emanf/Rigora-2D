# Prompt 12 validation

Date: 2026-10-18. Windows, Python 3.12.14, PySide6 6.12.0, MCP 2.3.0,
Pillow 13.0.0, resvg-py 0.5.0, psd-tools 1.25.0. The audit and measured workload
results are in [release-audit.md](release-audit.md).

## Regression and static checks

- `Test_Rigora.bat --no-pause`: **297 passed, 1 skipped, 3 warnings**, 242.22 s;
  Ruff lint/format passed and strict mypy passed for 112 source modules.
- After the final native-discovered icon/caption fixes, **29 focused UI tests
  passed** (79.91 s), covering all shared window chrome, dark/light fields,
  media import/output, automation controls and workspace drag/drop. This includes
  the two regressions added after the full gate. Lint/format/mypy passed again.
- The white close-glyph regression failed before its fix. Actual Qt image
  comparisons verify the fixed glyph and existing media buttons after both theme
  switches. Keyboard Tab navigation and field surface pixels are checked.
- The initial focused core/UI/storage/deformation group passed 44 tests. A further
  40-test chrome/workspace run completed successfully with thread-timeout diagnostics
  enabled; no stall or recovery intervention was required.

The skipped test requires Windows Developer Mode for symlinks. The three warnings
are existing deprecated Qt drag-event test constructors. Optional media/MCP tests
were enabled for the full gate; no feature was silently skipped for missing codecs.

New reliability coverage includes malformed extension output without losing a
preceding valid stage, FFD reference equivalence at 2/4/8 control resolutions,
outside-field bounds, neutral/sparse/dense controls, source immutability, file
deletion during save with Save As recovery and core import dependency direction.
Existing tests cover corrupted projects, missing assets, migrations, interrupted
replacement/backup recovery, invalid topology, failed encoders/publication,
cancelled render snapshots, incompatible/broken plugins and MCP schema/path errors.

## Real workflows and packaging

The new release smoke passed original character creation, motion + FFD, undo/redo,
exact source-byte and evaluated-pose reopening, SVG/PNG export, generated trusted
deformer activation/disable, a real CLI validation process and official MCP stdio.
All workflows use canonical services; no Qt module is imported by the smoke.

The rebuilt wheel was reinstalled offline in three verification environments:

- Core-only: no PySide6, MCP, Pillow, resvg or PSD packages installed. The smoke
  completed original character/FFD, save/reopen, plugin, CLI and SVG output.
- Media: render/PSD dependencies installed, no Qt or MCP. The smoke additionally
  rendered PNG successfully. Prompt 11's installed PSD/source-retention checks
  passed against its final wheel before this audit.
- Installed integration: the built Rigora module was verified to resolve from its
  separate `site-packages`; already prepared development dependencies were exposed
  on PYTHONPATH, including their Windows runtime directories. The smoke completed
  actual MCP stdio and PNG. This is an installed-module check, not a claim of an
  independently downloaded clean full dependency environment.

Source and installed checks operate offline after dependency preparation. The
release smoke creates fresh directories and isolated preferences. Logs and
generated original editable projects remain ignored under `build/maintenance/`
and `build/installed-prompt12-{core,media,mcp}/`.

Native Windows verification used an owned isolated editor, loaded an original
animated project, completed four PNG frames, switched dark/light while dialogs
remained open and captured workspace, output queue and media settings. Final
captures: `build/ui-preview/prompt12-04b1e044944b454590fc411a0c52809d/`.
The light output dialog and dark workspace were visually inspected; glyph recoloring
was subsequently corrected and recaptured. No existing user window was closed.

Locked offline wheel/sdist builds and `python -m tools.audit_release` verify exact
source/asset bytes (including the owner bone SVG), source guide/example/tool
inclusion, documentation, exclusions, local guide links and batch CRLF. The
release manifest records artifact/lock hashes and available dependency metadata.
See [release.md](release.md) for reproduction commands and unresolved public-release
items. Rigora remains a development candidate; this validation does not claim a
signed installer, full accessibility certification or completion of the Master Brief.
