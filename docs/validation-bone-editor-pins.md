# Bone Editor pin placement — 2026-11-02

The 2026-11-04 follow-up adds Object-root anchoring, explicit targets and visual
setup controls. See [current pin validation](validation-artwork-pin-editor.md).

The pin tool previously used ordinary scene selection to find its target. A bone
control or selection filter could hide the intended artwork from that picker,
leaving the previously selected mesh as the target. Clicking another part then
failed or pinned the wrong mesh.

Pin targeting now uses the existing painted-mesh picker directly. Bone controls
and scene selection filters do not block artwork targeting. Transparent gaps,
locked parts and empty space cannot fall back to the previous mesh. Binding
validation still belongs to `SkinService`. Bare rigs show an explanation instead
of arming a tool that cannot place artwork anchors.

Validation used the source application offscreen on Windows:

- The new multipart regression failed before the fix and passed afterwards.
- Real mouse clicks place pins on a different bound part with bones-only
  selection, using either a selected bone or the automatic character root.
- Anchors retain their displayed position during child rotation; release and
  undo preserve the other artwork and original document.
- A character assembled through Character Creator accepts a pin on the clicked
  part and restores its previous document through Undo.
- The related rigging, spring, subdivision and tool-lifecycle regression run
  passed 37 tests: `build/pin-final-20261102.xml`.
- After adding bare-rig feedback, the focused placement and tool-toggle run
  passed all 5 tests: `build/pin-feedback-final-20261102.xml`.
- Ruff lint/format and mypy passed. No executable build was run.

Review: **9/10**, based on correct part targeting, anchor behavior, undo safety,
tool lifecycle and visible failure feedback. Native Linux/macOS interaction was
not exercised. These are image-area pins: artwork must be bound to bones before
it can receive an anchor.
