# Compact editor panels and zoom readouts

Scene and Object Editor display their current canvas zoom beside the viewport
zoom controls. Timeline displays its independent horizontal zoom beside its zoom
buttons; 100% means eight pixels per frame. Fit and context switches update the
readouts, and returning to Scene restores its previous zoom.

The Object Editor places the character name and view selector together. Parts
and Bones devote the panel to the layer tree, without the redundant column
caption or the former bottom form. Small Material Icon buttons provide image
import, folders, removal and binding actions. Bind/unbind also appear in the
main toolbar. Bone targets remain above the tree; the duplicate flip controls
and sidebar mesh/bone/spring editor launch buttons are removed. Existing toolbox
and menu entry points remain available. Other panel action rows use the same
compact buttons, with accessible names and tooltips.

Layer disclosure, selection and scroll survive document revisions, undo and
Scene/Object context switches. Stable identities also preserve a collapsed
Scene when its name changes. Appearance and motion cards preserve navigation
when edits rebuild their contents. These snapshots are transient presentation
state and do not alter project data.

## Validation

- `build/editor-compact-final.xml`: 53 passed, with one obsolete test assertion
  that expected an individual deformation track instead of the grouped default.
  The assertion was updated and its workflow passed in the recheck.
- `build/editor-compact-recheck.xml`: 12 passed, covering the new panel tests,
  centered timeline header in both themes and dock states, mesh surface dragging,
  and native-picker PNG/JPEG/SVG imports through the compact import control.
- `build/editor-navigation-final.xml`: 4 passed after adding stable synthetic
  Scene identities and the rename/disclosure regression.
- Across these reports, the latest result for each of **57 distinct tests** is
  passing. The broader run retains one existing deprecated Qt drag-event test
  constructor warning.
- Repository-wide Ruff lint/format pass (484 checked files); strict mypy passes
  all 197 source files. Two existing formatting issues in the asset export helper
  and a Python documentation example were normalized without behavior changes.
- Visual captures of Parts, Bones, Skin, Clothing, Motions and the full workspace
  are in `build/editor-compact-review/`.

Review: **9/10**, based on readable spacing, consistent compact controls,
accurate independent zoom readouts, working binding/import/undo operations and
preserved layer navigation. This is an affected-workflow review, not a new
whole-application release audit. Scroll offsets naturally clamp if the viewport
shrinks or the remaining content is shorter.
