# Dock resizing and toolbox polish

Date: 2026-10-28.

An attached Assets panel could shrink to its minimum width and then ignore
attempts to expand it. Native Windows reproduction showed that even Qt's
`resizeDocks` could not enlarge it. The central widget reported a minimum width
of 1484 pixels while only 1280 pixels were available. The hidden Preview toolbar
contributed the combined minimum width of its tool options through the stacked
page layout, including while Welcome was selected.

The Preview header now uses the same scrolling-row pattern as the main property
toolbar. Controls retain their natural sizes, with horizontal scrolling when
needed. The header cannot impose its combined minimum width on adjacent docks.
Its scroll bar adds height only while needed. Native central minimum width in
the reproduced profile is now 184 pixels, and Assets expands after reaching its
280-pixel minimum. No owner preferences are reset.

Attached Tools has a 64-pixel column with centered 34-pixel controls and a compact
Float button. Its caption's layout height matches the 32-pixel frame, and a
10-pixel content inset adds space before the first tool. Floating tools retain
their smaller inset. Native toolbar layout margins explicitly match the scoped style.
Rounded hover, selected and pressed states work in dark and light themes. The
floating grip consumes idle moves so they cannot invoke Qt's dock resize cursor;
drag capture holds a closed-hand cursor and release restores the open hand.

## Validation

The separator regression exercises real Qt mouse events without moving the OS
pointer, from both fresh Welcome and an open project, with larger UI fonts and
a 1200-pixel-wide window. It grows Assets, shrinks past its minimum, then grows
it again. Both cases fail with the old header and pass with the fix. It also
checks that the last Preview control remains accessible by scrolling.

The broader source run passed 42 tests (`build/asset-resize-regressions.xml`).
After the final spacing adjustment, all 17 focused tests passed
(`build/dock-resize-toolbox-final.xml`). Ruff lint and
formatting and mypy pass for the changed source files.

Native Windows validation uses a copied workspace profile on a separate desktop
that is never activated. It covers actual separator drags, floating/docked Tools,
both side drops and captions, cursor state, rounded control rendering, independent
panels, layout persistence and unchanged project data. Temporary test plugins and
preferences stay under `build/`; real preferences and the foreground desktop
remain untouched.

Three compiled Windows launches passed 26 checks each, including the attached
top gap (`build/toolbox-polish-compiled-windows/run-1.json` through `run-3.json`).
The attached and floating palette screenshots were visually reviewed. A source
early-startup run without the placement-settling wait also passed all 26 checks
(`build/toolbox-polish-early-windows/run-1.json`).

Compile-only output:
`dist/windows-amd64-20261028-005721-794ced/Rigora/Rigora.exe`.
The whole bundle folder must stay together. Example plugins remain included and
require normal trust and enablement; validation plugins are not shipped.

## Review

**9/10.** Criteria: reproduced resize behavior and root-cause fix **3/3**;
toolbox spacing and rounded states **2/2**; cursor and docking interaction **2/2**;
regression and platform coverage **2/3**. Native Linux/macOS and foreground manual
mouse interaction have not been tested.
