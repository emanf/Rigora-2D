# Prompt 12 readiness audit

Date: 2026-10-18. Candidate: Rigora 0.1.0, Python API 1, plugin API 1,
project format 2. Windows / Python 3.12.14 / PySide6 6.12.0.

**Status: development candidate; not certified production-ready.** The Master
Brief and Prompts 1–12 were reviewed against the existing implementation and
tests. This audit improves existing behavior; Prompt 13 has not been started.
Remaining product/release gaps are explicit in [limitations.md](limitations.md).

## Findings resolved

- Malformed deformer return values could raise TypeError/IndexError outside the
  plugin callback failure boundary. The evaluator now validates complete finite
  X/Y pairs before blending, retains preceding valid geometry and emits a stage
  warning. Warning-bearing export refuses incomplete output.
- An externally deleted project could be recreated if deletion happened while
  the temporary save ZIP was being compressed. Save now refuses publication,
  keeps in-memory edits dirty and directs the user to Save As. Fault injection
  verifies cleanup and subsequent recovery. This remains ordinary filesystem
  conflict detection, not a cross-process filesystem transaction.
- An unexpected codec/worker exception could leave import/content controls busy.
  The shared job boundary now delivers failure and logs unexpected exceptions.
- Decimal spin boxes and multiline editors were missing the explicit common
  input/focus styling. Both palettes now use the same surface and focus rules;
  actual pixel and keyboard Tab checks cover these controls.
- Theme changes recolored child dialog buttons without restoring caption-specific
  close-hover icons. Refreshing every shared title bar preserves the white glyph
  on its red active surface. A regression failed before the fix and passes after it.
  Native inspection also found media buttons retaining dark-theme glyphs after
  switching to light. Media, automation, workspace and About controls now carry
  the existing Material icon metadata used by the common recoloring path; a
  regression checks already-open import/output controls through both palettes.
- FFD profiling identified repeated zero-control accumulation and binomial
  coefficient calculation. Nonzero controls and coefficients are prepared once
  per field evaluation; a neutral field returns its immutable input. No global
  cache or dependency was added. Sparse/dense fields at multiple resolutions are
  compared against an independent full Bernstein reference, including clamped
  outside points.
- The limitations page still described Prompt 6 and incorrectly listed completed
  features as absent. It now reflects current functionality. Installation, first
  character, Python/CLI/MCP, provenance and release guides are linked from README.
  Public Python API version/operation discovery is explicit and diagnostic.

## Audit coverage

| Area | Evidence / disposition |
| --- | --- |
| Architecture/dependency direction | Core AST regression rejects Qt/presentation/interfaces imports; domain/engine also reject service/infrastructure/SDK imports. Installed core/media workflows run without Qt. Existing adapters remain over canonical services. |
| MVVM | ViewModels own playback, selection, import and output state; commands/evaluation remain in services/engine. Main-window composition and automation modules are large maintenance hotspots; no speculative rewrite performed. |
| Animation correctness | Deterministic engine/constraints/springs, reverse/random seeking, interpolation and blending regressions; exact pose comparison after save/reopen. |
| Mesh/deformation | Topology/skin/FFD/pins/masks/animated controls tests, vector-at-output-resolution checks and malformed extension rollback. |
| Undo/redo | Existing authoring/rig/mesh/weights/key/content/puppet/import tests plus release smoke reversing and redoing animated FFD. File exports are deliberately outside undo history. |
| Project integrity/migrations | Version 1→2 migration, stable IDs, optional-field/source retention, corrupt/duplicate/unsafe ZIP rejection, checksums, external file conflicts, injected interrupted replacement, backup recovery and deletion-during-save regression. |
| Plugins | Manifest/API/dependency/cycle/trust tests; activation rollback; generated tool/deformer/content; missing solver warnings; disabled recovery; subprocess hard exit/timeout. Native in-process crashes/hangs are not isolated. |
| Python/CLI/MCP | Same 39 operations, explicit API version, typed argument/authorization tests, real CLI process and official MCP stdio smoke. HTTP auth/host/origin checks remain tested. |
| Offline | All local workflows use installed sources/codecs without downloads/accounts. HTTP is opt-in. Dependency installation/build-cache preparation is a separate network step. |
| Responsiveness | Decode/library/media/output/baking workers; render snapshot/cancel/progress tests; measured queue polling. Open/save/validation/evaluation and snapshot setup still run synchronously. |
| Themes/accessibility | Both palettes, custom chrome feedback, names/tooltips/shortcuts, timeline keyboard resize, numeric/multiline surface/Tab checks. Full screen-reader/canvas keyboard parity needs native assistive QA. |
| Provenance | Bundled original CC0 content and Material license retained. Source license and owner bone redistribution are open public-release items; see provenance guide. |
| Packaging/docs | Locked setup, wheel/sdist byte audits, exact bone/source assets, source docs/examples/tools, batch CRLF, installed smoke and version/hash manifest. No signed standalone installer. |

## Measured performance

Single-host diagnostic timings on Intel64 Family 6 Model 165 Stepping 5,
20 logical CPUs; no universal frame-rate assertion. Medians below
exclude fixture construction and UI paint. Raw ignored reports are under
`build/maintenance/prompt12-*.json` and the profile text is
`build/maintenance/prompt12-profile-before.txt`.

| Workload | Result |
| --- | --- |
| 1,000 bones/tracks, 100,000 Bézier keys, 31 random/backward seeks | 7.05 ms median, 7.61 ms p95; compile 168.6 ms. Engine stress fixture; not a guarantee that all such data fits the 8 MiB project metadata cap. |
| 1,089 vertices / 2,048 triangles / 64 FFD controls | Before 14.39 ms median; after 7.53 ms on the same 31-frame workload (about 48% lower). |
| Same dense mesh with FFD + lattice + bulge + twist | 15.75 ms median, 16.03 ms p95. |
| 200 animated bones, 20,000 keys spanning 99,000 frames | 1.22 ms median, 1.26 ms p95. |
| 128 installed packs plus bundled collection, 4,215 entries | 1,294.6 ms scan, performed on the library worker in the desktop. |
| Twelve real background SVG frames of an animated original character | 866.4 ms total; submit 12.06 ms; status-call p95 5.07 ms. |

The profiler placed FFD arithmetic at the top of per-frame work before the
optimization. Python/GIL, dense stacks, spring history and UI painting remain
scaling limits. Keep workload-specific measurements; a GPU or a broader threaded
evaluator redesign needs separate evidence and stale-result handling.

## Reproduce and release status

The new `tools.release_smoke` passed the original-character, animated FFD,
undo/redo, exact embedded-source/pose reopen, generated trusted plugin enable/
disable, actual CLI, transparent PNG and official MCP stdio workflows. It uses
fresh artifacts and isolated preferences. The initial focused regression group
passed 44 tests. Full gate, final package/native results are recorded in
[validation-prompt12.md](validation-prompt12.md).

Use [release.md](release.md) for commands and the remaining checklist. Public
release still needs a source-license decision, bone provenance resolution,
distribution/signing/install policy, broader platform/accessibility validation
and explicit scope acceptance for incomplete Master Brief features. No proprietary
asset catalog or engine-specific runtime exporter
is implied by the current milestone.

The later Prompt 13–16 increment adds editable motion retargeting, vector facial
controls and local lip-sync cues, deterministic spring baking/cartoon helpers,
and a character-building guide. See [validation-prompts13-16.md](validation-prompts13-16.md)
for its separate evidence. The original Prompt 12 audit above remains historical.
