# Timeline title bar and property grouping

Validated on Windows, 2026-10-27. This is a focused timeline usability increment;
the animation model, evaluator and serialized channels remain unchanged.

Playback now occupies the shared dock title bar, including clip selection,
frame/end fields, speed and range/FPS information. The previous playback row is
removed. The controls retain their shared actions while docking, floating or
changing theme. The resize grip and normal dock controls remain available.

The playback buttons are centered between two equally expanding field zones:
clip/current frame on the left, end/speed/range on the right. Field gaps are
8 pixels; playback icons use 4-pixel gaps and the header groups use 12 pixels.
Dope-sheet controls, clip/marker forms, key details and motion-block controls
have explicit spacing rather than inheriting compressed toolbar spacing.
The range label reserves its fixed width in Qt's layout calculations so it
cannot overflow the timing group. Dark/light captures at 1280 and 1500 pixels
verify centering, field separation and complete label containment. Floating and
redocking retain the same playback actions and centered layout.

Object Editor defaults to one row per property across its internal parts:
Transform, Opacity, Visibility and the other authored properties. View → Group
property tracks restores the individual owner hierarchy. Scene keeps separate
named characters/Objects with their own property rows. Grouping never combines
serialized tracks or changes their values.

Search now filters actual members of grouped rows by owner ancestry, channel
label and canonical path. Multiple terms narrow the same channel, so head rotation
does not retain unrelated body transforms. Selected only also narrows group
members. Matching branches open temporarily in the individual hierarchy; clearing
the filter restores previous disclosure. Filtered locking/visibility uses only
matching members and remains one undo step. Checkbox edits are deferred until Qt
finishes using the changed item, avoiding reentrant deletion of its tree row.

View → Marker labels controls ruler names such as Action, Passing and Opposite.
Marker ticks, saved annotations, keys and playback remain intact. The menu arrow
is centered to the right of View, with reserved space in both palettes. Menu
states synchronize with the viewmodel. Onion/trail overlays render during animated
bone posing; retained comparison captures once and is not recaptured by unrelated
overlay toggles.

## Evidence

- `build/timeline-center-spacing-final.xml`: **35 tests passed** after centering
  the playback group and spacing all timeline pages. This includes timeline,
  selection and animation GUI interaction regressions. The updated header replay
  also checks both themes at 1280/1500 pixels and native floating playback.
- `build/timeline-centered-header.xml`: **1 test passed** for the centered header
  and spacing checks before the broader GUI regression.
- `build/timeline-title-final.xml`: **43 tests passed** across the new integration
  checks, existing timeline/selection GUI interactions, animation editor, channel
  services and playback. Three existing warnings use deprecated Qt drag-event
  test constructors.
- `build/timeline-header-final.xml`: **1 test passed** after final caption spacing
  refinement, checking full field containment, both themes, floating/redocking
  and actual playback clicks.
- Ruff lint and format pass for **357 Python files**. Strict mypy passes all
  **195 source files**.
- Integration uses premade Panda/Raccoon specimens from the creator pipeline,
  two-character Scene rows, native popup clicks, actual ghost-pose painting,
  grouped filtering, atomic lock/undo and document switches. Dark/light dock and
  menu captures are in `build/timeline-title-review/`.

Review: **9/10**, based on compact readable chrome, context-correct grouping,
accurate filtering, working menu feedback, preserved animation/undo semantics
and dock/floating behavior. Validation is focused on the affected workflow; it is
not a new whole-application release audit.

Centering/spacing review: **9/10**, based on balanced playback placement, visible
gaps between fields, complete label containment and consistency across timeline
pages, both themes and dock states.
