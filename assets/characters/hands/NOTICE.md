# Owner-supplied paired vector hands

The project owner supplied `Untitled.svg` for Character Creation. Its source
SHA-256 is `d8d7a005447a2397fbff0b609a6fe4c187aada2752ec60124d24a428a76c8d26`.

`cartoon-gloves.svg` preserves all 18 hand groups and all 54 original vector
paths, including their IDs, path coordinates, fill rules and drawing order.
Only the flesh and brown cuff fills were changed to white. The original dark
outline fill remains the palette's ink source. No paths from previous hand
sheets, wrist overlays, synthesized back surfaces or generated contours are used.

Adjacent groups form the provided left/right pairs: hand-01/02 through hand-17/18.
The first goes to hand.R (viewer-left in the rest pose), the second to hand.L.
Each group's `data-bind-transform` registers its original sheet coordinates
to the rig wrist using uniform scale, rotation and orientation reflection.
View reflection and animated wrist transforms do not alter any path geometry.
Preserve these registration attributes when replacing a group.

The SVG is loaded once from the packaged assets. Generated characters embed
their own vector hand sources; PNG previews are disposable caches. Runtime
operation never depends on the owner's Downloads folder.

This is owner-supplied artwork. Importing it does not assign it a new CC0 or
third-party stock-art license.
