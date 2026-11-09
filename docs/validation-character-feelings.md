# Expandable creator categories and feelings

Validated on Windows, 2026-10-25.

The right option browser has one scrollbar. Expanded category grids resize to
show every card; closing a category releases its space and retains its choices.
Wheel input over cards routes to the surrounding browser. Checks cover all
visible wardrobe grids, collapse/reopen, compact layout and wheel delivery.

The Feelings category provides 16 coordinated expressions through the normal
eyebrow, eye, mouth and eye-pose choices. Individual choices stay editable and
one preset click creates one appearance Undo step. Existing recipes remain
compatible. Mouth has 30 styles; Teary eyes include vector tear contours.
All 631 option posters are bundled assets and are rebuilt by
`tools/build_component_posters.py`.

The focused creator, feeling, wardrobe and choreography regression run passed
**71 tests**. Ruff lint and formatting checks pass for the workspace; mypy passes
all **183 source files**. The test report is
`build/creator-feelings/tests.xml`.

`tools/review_character_creator.py --feelings` renders **160 faces**: 16 feelings
on all five reference identities in Front and Side views. The five contact
sheets, review count and real UI screenshots are in `build/creator-feelings/`.
Visual inspection covered these sheets and corrected profile mouth fit. These
are editable expression presets, not emotion recognition or procedural facial
motion.
