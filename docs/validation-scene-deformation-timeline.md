# Scene deformation timeline validation

Validated on 2026-11-03 against the source application.

Scene-authored deformer and vertex tracks were evaluated correctly but excluded
by the timeline's top-level Object filter. Those channels now resolve through
their mesh/artwork ancestry to the owning Scene Object. FFD control keys appear
on its Deformation lane; direct vertex keys appear on Mesh deformation.
The existing compound row retains every canonical track and key identity.

Add Track discovers deformation stages on nested artwork using the shared
Object-to-mesh resolver. Dense raw vertex enumeration remains in the local
editing workspace. First FFD clips use the common clip factory, preserving Scene
or Object ownership metadata and the separation of their animation workspaces.
Previously saved keyframes are retained without conversion.

## Validation

- **202 focused tests passed**, covering all creative presets, numeric channel
  editing and four offscreen deformation-timeline regressions.
- A real portable FFD pack drop into a new project exposes every control track
  and its grouped keys. Selected-only filtering preserves the visible lane.
- Retiming, Undo and save/reopen preserve the editable channels and geometry.
- A targeted FFD motion on nested artwork is visible under its Object, and
  Add Track offers the actual stage controls.
- Direct vertex keys remain visible under the Object's Mesh deformation lane.
- A first Object Editor FFD action stays in its Object timeline when returning
  to Scene.
- Ruff lint/format checks and mypy passed for the changed code; mypy checked
  267 source files. No executable bundle was compiled.

The real source-window and cropped timeline images were rendered offscreen and
visually reviewed in ignored `build/scene-deformation-review/`.

## Review

**9/10**, based on channel visibility, correct ownership, editing/persistence,
selection filtering and bounded discovery. No blocking finding remains in this
increment. The selected clip determines which animation is displayed; private
Object source actions are not flattened into unrelated Scene timelines.

## Named FFD actions

Scene template drops now retain a named, editable Object action and place a linked
instance on the Scene Animation row. The action is listed in Object Editor's
Motions page and timeline clip selector. It uses the same source synchronization
as skeletal actions: source key edits update placed instances without duplicating
their timing. The source starts at frame zero; the Scene window retains the drop
frame, speed-adjusted duration, repetition and continuous loop endpoint.

Applying FFD inside Object Editor still layers into the selected local action.
Legacy unseparated clients retain direct-key behavior. Existing Scene-only tracks
are preserved, without silently rewriting a saved project on Object Editor entry.

The follow-up passed **226 focused tests**, including all 20 built-in FFD motions,
24/30/60 FPS source timing, nonzero placement, edited-source synchronization,
named animation discovery, Undo and project reload. This run overlaps the earlier
202 checks. Ruff lint/format and mypy passed. The actual named card, selected clip,
editable deformation keys and linked Scene interval were visually verified in
the offscreen source window. Review remains **9/10** for visibility, ownership,
source editing, timing and persistence; no blocking finding remains for new drops.
