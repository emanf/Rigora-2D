# Prompt 10 validation

Date: 2026-10-18. Windows, Python 3.12.14, PySide6 6.12.0, official MCP SDK 2.3.0.

The owner's explicit instruction to continue to the next prompt authorized this
milestone after the template-preview fixes. Prompt 11 has not been started.

`Test_Rigora.bat --no-pause` passed **270 tests**, with one existing Windows symlink
permission skip and three Qt drag-constructor deprecation warnings. Ruff lint,
format checks and strict mypy passed (105 source modules). Final focused checks
also passed **14 tests** after the CLI duplicate-JSON error classification and
optional mesh-overlay refinement. Logs are ignored under `build/maintenance/`.

Coverage includes:

- Offline character/rig/motion/clip/key creation, actual evaluated SVG sequences,
  validation, save/reopen and stable identifiers through canonical GUI services.
- Explicit in-memory transaction rollback, grouped undo, asset-owning dry runs,
  revision conflicts, strict argument validation and protected vertex weights.
- Authorized file boundaries, traversal refusal, pre-read content/plugin discovery
  boundaries, existing-file approval and the independent MCP host overwrite gate.
- CLI JSON results, usage/validation/I/O conventions, no-Qt imports, whole-workflow
  dry runs, `--dry-run --save` and ambiguous duplicate JSON rejection.
- Official MCP client discovery and typed schemas; real stdio subprocess tools,
  rendering, per-frame protocol progress, save and denied overwrites.
- HTTP bearer rejection before session creation, authorized protocol initialization
  and DNS-rebinding Host rejection. Remote binding requires host opt-in and an
  explicit host allowlist. No network listener is started by desktop launch.
- Real SVG rasterization checks: transparent background, continuous mesh regions,
  correct translucent opacity and requested output dimensions.
- Actual desktop inspection/configuration and background SVG preview export,
  rejected overwrite, unchanged source document and invalid-root feedback.

The wheel and source archive build offline. An installed core-only environment
without PySide6 or MCP completed the nine-step acceptance workflow, produced four
SVG frames, reopened the `.rigora` project and validated it. Its installed CLI
reported 28 task operations; invoking MCP without its optional extra produced an
actionable dependency message. Original bone SVG bytes, canonical assets, package
exclusions, purpose-focused source docstrings and batch CRLF audits passed.

Native preview verification covers all 119 bundled items, the three original
layered SVG characters, autoplay/loop during FFD speed/strength edits, and isolated
project state. A Windows mouse drag and regression tests verify copy payloads;
native Qt drop-event checks verify installed-package placement. Captures and raw
logs live under ignored `build/ui-preview/` and `build/maintenance/`.

Preview output is SVG, including evaluated mesh deformation from original vectors.
Movie/codecs, raster production exporters and multi-user hosted accounts are not
part of this milestone. HTTP is an optional authenticated service over one
serialized document session. File sequences publish individually; earlier frames
can remain if a later frame fails. Authoring undo does not undo saved files.
