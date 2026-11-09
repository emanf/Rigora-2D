# Saved Object editing, packages and template placement

Validated on Windows source on 2026-11-02. GUI checks used
`QT_QPA_PLATFORM=offscreen` and isolated preferences. No executable bundle was
compiled, no foreground windows were opened and no owner content packs were
installed during validation.

## Review score: 9/10

| Criterion | Score | Evidence |
| --- | --- | --- |
| Requested interactions | 4/4 | Scene Object glyphs survive image decoding; Objects double-click edits; Templates/Custom double-click place and remain in Scene; menu priority, populated categories and cursor-only drags verified |
| Ownership and data safety | 2/2 | Unplaced definitions remain editable; source edits publish to linked copies; Undo/Redo and Save reach the owning project; confirmed removal respects current-scene scope; package round-trips preserve rig, appearance, actions and referenced source bytes |
| Responsiveness and UI consistency | 2/2 | Complete composition posters render on one background worker with coalescing and revision checks; cached card state survives editor return; package dialog uses the shared neutral custom window and native file selection |
| Platform coverage | 1/2 | Windows offscreen source checks and package-dialog visual inspection completed; native OS drag loops, Linux/macOS and frozen bundles were not exercised |

## Results

The wider regression run covered 92 tests. It initially passed 89 and exposed
three failures. The fixes were rechecked together with one additional ownership
and saving regression: all 19 affected tests passed. Across these runs, all
**93 distinct relevant tests** passed on their final checks.

- `build/object-library-integration-final-20261102.xml`: wider regression run,
  including linked definitions, assets, source drags, Object Editor, pivots,
  content library/browser, template shelf, scenery and character placement.
- `build/object-library-final-fixes-20261102.xml`: 19 passing affected checks,
  including all three earlier failures, cross-scene removal, package import,
  Custom Templates placement, cursor-only template dragging and unplaced Object
  editing with Undo/Redo and actual owning-project serialization.

The real placement failure was a locked imported camera being included in artwork
root translation. Cameras already did not contribute to the placement anchor;
they are now also excluded from the translated roots, preserving camera transforms
and locks. The other failures were test assumptions: clicking undecoded artwork,
and expecting an empty Favorites category to remain in the selector.

Ruff passed for `src`, `tests` and `tools`. Formatting passed for 508 Python files.
Mypy passed for all 267 source files. Remaining pytest warnings concern deprecated
Qt constructors used to synthesize drag events.

## Review boundaries

Custom Templates are installed snapshots shared across projects, not live links
between separate project files. Placed copies within a project remain linked.
Poses, motions and deformation presets still need compatible existing targets;
their standalone Add to Objects/Add to Scene menu actions are disabled.
Existing bounded, data-only `.rigpack` validation and archive limits apply.
Publication rejects changed or removed source definitions rather than overwriting
concurrent edits. A conflicting working tab stays dirty and recoverable.

Manual visual inspection confirmed the package dialog's preview area, editable
category, aligned fields, neutral outline, shared title controls and Cancel focus.
Artwork posters are transparent; the existing card delegate supplies the asset
card background. Native file pickers and drag cursors retain OS behavior.
