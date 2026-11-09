# Mustache silhouette redesign

Windows validation, 2026-10-26.

The previous generator reused a lobed path with small modulo-based width/depth
changes and one shared curl. The 17 visible choices now use distinct solid
contours: thin Pencil, long English, upright Dali, angular Chevron, hanging
Horseshoe, heavy Walrus, short Painter, trapezoidal Lampshade, separated Split,
rounded lobes and independently drawn curled/fanned/shaggy variants. None remains
empty. The same upper-lip socket and anatomy-dependent horizontal scale keep
replacement parts fitted without changing their identity.

All vectors use Hair paint and have no contour borders. Profile views compress
the silhouettes horizontally; rear views omit them. Card framing includes tall
curls and hanging ends, and all 18 canonical mustache PNG previews were rebuilt
from the actual SVG contours. Runtime artwork remains original vectors.

Robot defaults now use neutral gray Hair paint rather than nearly matching their
dark visor. Explicit/custom paints and saved characters are not recolored. The
redesign applies to newly generated artwork; existing edited projects keep their
embedded sources.

Visual review sheets are under `build/mustache-review/`: Ren front, Milo front
three-quarter, Rin profile and Mallow with the final defaults. A compact six-style
comparison is `mustache-preview.png`. All sheets were inspected.

The mask regression removes each style's width/height differences before all 136
pairwise comparisons. The highest normalized silhouette overlap is approximately
0.847; the regression rejects overlap of 0.9 or higher. This checks geometric
difference rather than different SVG strings or scaled copies. Additional checks
cover every style and all five views on the five presets, preview bounds, owned
paint, hidden rear artwork, retained-option exclusivity, Undo, save/load and
actual creator card clicks without automatic checkbox selection.

Review: **9/10**, based on distinct normalized silhouettes, recognizable named
forms, preview framing, face projections, retained replacement and contrast.

Validation passed 72 broad regressions in `build/creator-mustache-regression.xml`
and 32 final checks after the robot default adjustment in
`build/creator-mustache-final.xml` (96 distinct tests). Ruff lint/format checks
passed for 354 Python files; mypy passed all 195 source files.
