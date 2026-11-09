# Object Editor skin and bone corrections

## Causes and changes

- Container-based characters were still given a legacy actor wrapper in the
  layer tree. The skeleton became a sibling of the container used as the visible
  tree root, making its rows unreachable. Container-based objects now own their
  artwork and skeleton directly; legacy actors retain their wrapper.
- Existing skin keys overrode later base color edits. Appearance edits now update
  an existing keyed channel at the playhead, following the transform editor's
  convention. Unanimated channels remain base edits unless Auto key is enabled.
  This shared service handles palette colors, tint and other appearance scalars.
- Viewport focus loss canceled the shared scene preview even when it belonged
  to the color dialog. Focus loss now cancels only a viewport-owned drag. The
  picker has labeled Apply/Cancel buttons and releases its dialog after use.

## Reproduction and review evidence

`tests/test_object_skin_bones_gui.py` uses the actual creator assembly services
for Panda and a child girl. It checks reachable bone rows, real row selection,
painted bone silhouettes, visible color changes, previously keyed saved skins,
one-step Undo, real modal Apply/Cancel and viewport drag cancellation. Artwork
loading completes before visual comparisons. Captures are in
`build/object-skin-bones-review/`.

The initial reproductions failed for both unreachable skeletons and colors masked
by saved skin keys. A later real modal test also reproduced Apply silently losing
its preview, which mocked dialog results had missed.

`build/object-skin-bones-regression.xml` recorded 65 passing checks and the failing
real modal Apply case before the focus cancellation fix. One existing Qt drag
event constructor emits a deprecation warning. `build/object-color-dialog-final.xml`
records both real modal Apply/Cancel cases passing after the focus fix.

An intermediate repeated-window test process ended in a native Qt access violation
while styling a new window. Explicit color-dialog cleanup was added afterward;
the final complete focused run is recorded separately.

## Final validation

`build/object-skin-bones-verified.xml`: **22 passed**, including all nine new
checks, existing character gestures and timeline workflows, compact editor state
preservation and picker preview/Undo checks. This complete run finished without
a native failure. Across the broader and final reports, the latest result for
each of **67 distinct tests** passes, with no remaining failed assertions.

Repository-wide Ruff lint/format pass (486 checked files); strict mypy passes all
197 source files.

Review: **9/10**, based on visible and selectable bone controls, immediate color
rendering on human/animal specimens, correct handling of existing skin keys,
real Apply/Cancel behavior, atomic Undo and preserved viewport drag cancellation.
Validation covers the affected editor workflows, rather than a full application
release audit.
