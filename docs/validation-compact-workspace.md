# Compact workspace validation

Date: 2026-10-28.

**Review: 9/10.** Criteria: default arrangement and compact presentation **3/3**,
pointer/keyboard interactions **2/2**, persistent state and project isolation
**2/2**, source/native validation **2/3**. Windows was exercised; native Linux and
macOS checks remain unrun. No unresolved failing cases remain in the scoped checks.

## Implemented behavior

- Default Scene-left, Preview-center, Assets-right layout, with full-width bottom
  Timeline and top toolbar. Inspector is hidden initially and remains available
  from View. Existing serialized layouts remain honored; Reset Workspace Layout
  applies the new default without touching project history.
- A 44-pixel Tools strip overlays Preview. Its rounded six-dot grip supports real
  pointer dragging, left/right edge snapping and keyboard movement. It never
  becomes a separate native window or expands to a full floating dock caption.
- Ordinary panels retain their shared custom title bars and existing docking,
  floating geometry and persistence behavior.
- Tool placement/visibility are saved separately from native dock state. Explicit
  hidden choices synchronize with the View action even before first show. The
  initial inherited dock toggle was unsuitable outside the native dock layout;
  the strip now owns its corresponding checked action.
- Hierarchy guides accompany 20-pixel Scene icons and 12-pixel visibility/lock
  glyphs in compact 26-pixel columns. State controls retain normal click handling.
- Project sources use 44-pixel rows, 36-pixel square checkerboard thumbnail wells
  and small translucent format badges. Original source images remain unchanged.
- Timeline Lock/Show columns start at 26 pixels, with accessible icon headings.
  The name/channel pane starts narrower; extra window space goes to animation.
  Header state is persisted, and refresh no longer resets channel widths.

## Verification and resolved findings

- `build/preview-toolbox-regression.xml` ran 75 cases: 73 initially passed. The
  two findings were the obsolete right-side Scene assertion and measuring a
  hidden Timeline page's cached geometry. The latter now measures the displayed
  divider after confirming that the selected tab restored correctly.
- `build/preview-toolbox-final.xml`: **12 passed**, covering all corrected cases,
  actual grip dragging/snapping, resize attachment, View toggles, compact source
  rendering, dark/light screenshots, visible/hidden placement restoration,
  persistent channel widths and data-safe Reset Workspace Layout.
- Across these reports, **76 distinct cases passed**, including workspace,
  timeline, editor selection/transforms, bindings, plugin and extension checks.
  Both initially failing cases have passing reruns; no failure is left unresolved.
- Ruff lint passes; **536 files** pass formatting; mypy passes **210 source files**.
- `build/compact-native-ui.json`: **14 passing checks** in the compiled Windows
  application. The harness creates a real Creator Panda, waits for asynchronous
  artwork decoding, inspects actual panel geometry, drags the real grip, checks
  edge tracking during resize, toggles visibility, resets the layout without a
  project mutation and inspects saved placement. Screenshots:
  `build/compact-native-ui.png`, `build/compact-native-toolbox.png`.
- Source screenshots for both themes are in `build/preview-toolbox-review/`.
  Visual review caught the initially collapsed grip and missing strip backing;
  an explicit grip size hint and rounded painting resolved both before packaging.
- `build/compact-bundle-check.json`: **12 passing packaged-app checks**, including
  **2,183 canonical asset hashes**, codecs, SVG/PNG rendering, save/reopen,
  console companion, plugin worker, MCP, Material Icons and desktop startup.
- Compile-only output:
  `dist/windows-amd64-20261027-212516-b4b01b/Rigora/Rigora.exe`.
  Build still records `not requested (compile-only)` for tests. Validation was
  invoked separately. Both example plugins are included beside the executable
  with normal trust/enable requirements.

All GUI and packaged checks ran offscreen, using isolated test preferences.
No interactive app window was opened and the owner's workspace settings were
not overwritten. The temporary native validation plugin remains under `build/`
and is not shipped or enabled in normal application sessions.
