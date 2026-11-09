# SVG props, static catalog posters and spring playback

Validated on 2026-10-21 with the local Python/PySide6 environment.

- 144 original SVG props, twelve distinct designs in each of twelve families.
  Every prop applies through ContentService as original embedded SVG artwork with
  eight triangles; one Undo restores the project. All twelve family galleries
  were visually reviewed under `build/props-review/`.
- All 289 bundled entries have nonempty 144 × 144 PNG posters. Catalog browsing
  decodes saved PNGs at their existing size; the shelf and browser reuse icons.
  New shared scenes/rigs bake a poster once. A headless installation without render
  extras uses the bundled static fallback and still exports a valid pack.
- Discovery includes every bundled `.rigpack`, including the two new prop packs.
  Family filtering works in both browsers and is ignored outside the prop category.
- Timeline playback owns the viewport pose; queued live spring callbacks cannot
  overwrite it. Interactive physics remains available while paused.
- Ten preset examples use the real solver and a shared visible-only animation
  clock. Cached samples differ by preset and retain connected joints.

The focused library, spring, tool lifecycle, automation and plugin suite passed
41 tests. Two subsequent checks passed for the headless poster fallback and
pre-sized PNG loading. Ruff lint/format and strict mypy passed (133 source files).
Reports: `build/props-springs-final-tests.xml` and `build/poster-edge-tests.xml`.

`tools/benchmark_workspace.py --case willow --samples 7` measured medians of
2.90 ms for hand pan, 0.88 ms for pose evaluation, and 10.70 ms for sequential
playback including paint. These are local offscreen diagnostics, not portable
frame-rate guarantees. Results: `build/props-review/performance/workspace.json`.
