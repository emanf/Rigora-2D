# Object Editor foot editing validation

Windows validation, 2026-10-26.

## Correction

Creating Milo, entering Object Editor and rotating `foot.L` reproduced the
problem: authored rotation changed while the evaluated foot remained fixed.
The generated standing contact copied its target transform over the new pose.

The application services now recompose deliberate foot edits from the displayed
pose and carry the generated contact target with them. Rest edits publish bones
and targets atomically. Animated gestures and numeric pose edits key both controls
in the active action, retaining the source skeleton and enabled constraints.
Gesture patches include Group targets as well as object targets and bones.

Ordinary custom constraints retain their existing behavior. Explicit edits to a
contact target take precedence, and inactive FK standing contacts are not added
to generated animation keys. Characters without actions also retain their Object
coordinate space during live preview, matching the released artwork.

## Validation

- **10 new service regressions** passed, covering Milo, Mina and Mallow: foot
  movement, rotation, numeric keys, rest editing, the unchanged opposite foot,
  save/load, independent walking actions, live preview and one-step Undo.
  An additional check covers a creator character without animation actions.
  Report: `build/foot-editor-final-core.xml`.
- **3 new real-window regressions** passed. Each inserts Milo through Character
  Creation, enters Object Editor and uses viewport mouse events to move the
  visible shoe, move its bone or rotate its tip. Shoe movement is checked against
  its exact world-space displacement. Reports: `build/foot-editor-pointer.xml`.
- **127 existing regressions** passed across rig editing, constraints, bone
  animation, creator assembly, whole-Object movement, part editing, transform
  properties and bundled standing/walking performances.
  Report: `build/foot-editor-regression.xml`.
- **18 existing gesture regressions** passed for bone handles, selection scopes,
  animation keys and Undo. Report: `build/foot-editor-gestures.xml`.
- Ruff lint and formatting passed across `src`, `tests`, `tools` and `examples`
  (350 Python files). Strict mypy passed all 195 source files.

Review score: **9/10**, based on direct foot control, preview/release consistency,
action isolation, preserved standing contacts, persistence and reversible edits.
The GUI checks use isolated offscreen Qt on Windows; other platforms were not
tested. No existing project files are rewritten by this fix.
