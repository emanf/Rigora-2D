# Character Creator controls and replaceable parts

Windows validation, 2026-10-26.

## Result

- Character preparation displays an animated indeterminate progress bar. It is
  hidden after completion or failure; no fabricated percentage is shown.
- The preview action dropdown is removed. Animation cards select the action.
  Play/Pause and Repeat are Material icon buttons in a fixed canvas overlay.
  Its background does not propagate pointer drags to the canvas.
- Creator checkboxes are 24 pixels and retain alternatives independently from
  the active default. Clothing, eyes, mouths, eyebrows, noses, hair, mustaches,
  beards, eye poses and hand poses are supported. Recipe save/load retains them.
  Required blink/speech/action states remain available when optional poses are
  omitted. Facial styles remain replaceable through Object Editor's cards.
- Appearance previews preserve the SVG viewBox origin in rig coordinates. Both
  lightweight and rigged previews use an anatomy-based frame and a consistent
  sole anchor. Clothing bounds no longer recenter the character; manual zoom and
  pan survive appearance changes. Explicit Fit and window resizing use the same
  stable stage frame.
- Open/fist/point hand articulation uses the selected hand proportions and one
  wrist socket. Single-handed actions keep the other hand's rest pose;
  celebrations use both hands. Generated visibility keys select one pose per
  slot. Evaluated garment coverage prevents keyed bare hands appearing beneath
  gloves. Twenty-five hand anatomy/pose card previews were regenerated directly
  from the original vectors.

Facial style and pose controls use separate visibility levels. Mouth visemes
retain ordinary scene-object control identities for lip-sync and tracking; eye
poses expose owned visibility controls while styles select their leaf artwork.
The shared appearance matcher handles these gated alternatives in the Inspector
and Object Editor. Normal clothing retains its existing all-parts match policy.
No project format version or Qt dependency was added to the domain/engine.

## Evidence and review

**155 distinct focused tests passed** across the broad regression, actual GUI
and final assembly recheck groups. Overlapping cases are counted once in
`build/creator-controls-review/test-summary.json`. The reports are
`build/creator-controls-regression.xml`, `build/creator-controls-gui-final.xml`
and `build/creator-controls-final-core.xml`.

New checks cover retained face styles, exclusive blinking and speech shapes,
camera eye-pose mappings, Undo, save/load, limited-pose retention, all five preset
hand proportions and child/robot hand replacement during gestures. Real-window
checks include progress while a worker is held, fixed transport geometry, large
checkboxes, preset/clothing alignment and creation into Object Editor with the
correct facial-style card checked. Existing regression coverage includes the
previous foot/scene fixes, audio, facial animation, tracking and deformation.

Screenshots of loading, the complete creator, a wave and checked eye alternatives
were inspected under `build/creator-controls-review/`. The animation performance
regression also passed with the new controls and original SVG rendering inputs.
Ruff lint/format checks passed for 352 Python files in `src`, `tests`, `tools`
and `examples`; strict mypy passed all 195 source files.

Review score: **9/10**, based on loading feedback, clear selection, stable layout,
retained-part persistence, facial animation compatibility and hand replacement.
Tests use isolated offscreen Qt on Windows. Existing saved artwork is preserved;
the hand redesign applies to newly generated characters rather than rewriting
the owner's edited projects.

## Independent checkbox and wink follow-up

Facial and eye/hand pose card artwork selects the visible default without changing
any checkboxes. Their indicators can toggle the current default off and on;
clicking another indicator retains that option without changing the current card.
Explicit checked alternatives survive recipe restoration independently from the
default. Required/default artwork remains available for character assembly.
The shared card view consumes checkbox press/release gestures so Qt does not
also select their card. Clothing keeps its existing wear/wardrobe policy.

Winks reuse the exact original vector for the eye that stays open, including its
shape, iris, highlights and lashes. The closed eye uses the same socket, width
and tilt. All human eye styles and three front/side projections are checked
across the four human presets. Seven affected eye-pose/feeling card previews
were regenerated from vectors. The visual comparison is
`build/creator-checkbox-review/winks.png`.

Loading now occupies a three-pixel, full-width strip at the bottom edge of the
preview. Its neutral indeterminate animation is mouse-transparent, stays attached
when resized and hides on completion/failure. It does not change the layout.
GUI checks cover the parent, thickness, width and bottom alignment during loading
and resizing, alongside actual pointer gestures and retained-option restoration.

Follow-up validation: 74 regression tests passed in
`build/creator-checkbox-wink-final.xml`; the two final GUI rechecks passed after
moving the loading strip in `build/creator-loading-edge-final.xml`. Ruff lint,
format checks (352 files) and mypy (195 source files) pass. Updated loading and
wink screenshots were inspected. Review: **9/10**, based on independent pointer
selection, saved checkbox state, exact open-eye preservation, loading placement
and resize behavior. Saved character artwork is not rewritten by regeneration.
