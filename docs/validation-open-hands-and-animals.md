# Open hands and animal attachment artwork

Windows validation, 2026-10-26.

## Open hand

The old open pose had four similar extensions on a rectangular palm and no
separate thumb. The new vector has a tapered palm, four graded round fingers,
an opposed thumb and a light thumb crease. Middle/ring/index/little reach is
ordered, and the finger roots overlap the palm instead of leaving disconnected
islands. Both hands keep the same round wrist sockets as their closed poses.
Raised palms use the correct mirrored thumb side; folded/pointing gestures share
that handedness. Open, Wave and Splayed anatomy choices use the same construction.

Checks cover all 18 profiles on all five presets: connected masks, five digits,
four separated finger tips, ordered reach, anatomical thumb sides, mirrored
coverage and unchanged proximal wrists. Raster comparisons allow less than 0.2%
coverage error for reflected SVG edge antialiasing. Existing size, hand visibility,
glove coverage, save/load and animation responsiveness checks remain passing.
Twenty-five hand anatomy/pose card previews were rebuilt from original vectors.

Five presets were assembled with Wave and rendered at five phases. The review
sheet and wrist/hand closeups are in `build/open-hand-review/`. Visual inspection
of the raised palms caught and corrected their thumb side before the final checks.
Review: **9/10**, based on anatomy, game-scale readability, wrist continuity,
pose proportions and correct replacement during playback.

## Animals

Animal components retain neutral outlines through lightweight previews, rigged
creation and export. Humans and other vector catalogs keep their existing border
policy. Filled leg sockets have no contour stroke. Their separate open paths
outline the sides and soles, leaving the top edge open into the body. Neck side
outlines also omit end caps. Round toe details retain clear foot silhouettes.

All legs of a specimen use matching paint; Panda and Sheep use their darker limb
paint consistently. Fore/hind attachment points sit inside the body silhouette.
Leg reach accounts for the root's vertical offset so standing feet share a ground
plane. Side and three-quarter presentations group their near/far leg pairs at the
front and rear of the body; bird legs use narrower body-relative spacing.

Bird beaks are separate head-parented vector parts. Front bills center below the
eyes; three-quarter/profile bills attach at the projected face edge and point
right. Duck/goose/swan front bills are symmetric; long/hooked bills retain their
species shape and front-view foreshortening. Rear views hide beaks. Their head
parent keeps them attached during Idle/Walk/Run/Jump/Fly actions.

Owl uses a compact bill socket aligned with each view's facial bridge. The
three-quarter presentation shifts the bridge and bill right, compresses the right
facial disc, and makes the whole right eye 18% smaller, including its pupil and
highlight. Blink lids share the same eye coordinates and projected widths. The
profile has one visible disc and a short bill projecting from the face edge.
Opaque-mask checks verify eye clearance and compact bounds in all three visible
views. `build/owl-beak-review/perspective-after.png` records the final closeups;
the earlier `after.png` is superseded. The animal pack, 42 cards and five bird view
sheets include this change. The left eye and facial disc draw over the right
ones in three-quarter view; lids use the same stacking order. The latest visual
is `build/owl-beak-review/layer-order-after.png`. Layer-order review: **9/10**
for left-over-right overlap, preserved proportions and matching blink placement.
Pack validation compares embedded SVG sources against
the current creator output to catch stale library artwork.

The 42 animal cards and `assets/library/creator-animals.rigpack` were rebuilt.
The builder supports `--kind Animals` to regenerate this catalog independently.
`tests/test_animal_anatomy.py` covers all 42 animals in five views, uniform limb
fills, open root outlines, source borders, rest-ground alignment, beak attachment
and the bundled pack. Four representative bird builds exercise animated head
inheritance across every action. The broader vector catalog and real creator
interaction checks also pass. Before/after and five-view sheets are under
`build/animal-fit-review/`; `preview.png` shows the final animal treatment.

Review: **9/10**, based on joint continuity, visible outlines, consistent limb
paint, grounded standing poses and view-specific beak positioning. Existing saved
artwork is preserved; newly created or reapplied library specimens use the update.

## Shared animal eye projection and layering

All paired three-quarter animal faces now paint the smaller right eye first,
followed by the left eye. White, pupil and highlight scale together; closed lids
share the same coordinates, widths and stacking order. Owl retains its fitted
facial bridge. Panda and Raccoon eye patches, plus Frog eye sockets, use the
matching projection and paint order. The Fish's existing single visible eye is
preserved. Front and profile eye geometry remains unchanged.

All 42 creator cards and the animal library pack were rebuilt. Embedded SVG
sources are compared with fresh creator output for every library animal. Face
review sheets for all 42 designs in front, three-quarter and profile views are in
`build/animal-face-layer-review/`; `preview.png` shows six representative designs.
Ten whole-character view sheets under `build/animal-fit-review/` were refreshed.
Review: **9/10**, based on near-eye stacking, far-eye proportions, patch/socket
alignment, blink consistency and preservation of each species' silhouette.

Panda and Raccoon muzzles now paint after their eye patches, with nose and mouth
details above the muzzle. This preserves their geometry while hiding patch
contours beneath the projecting nose area. Front, three-quarter and profile
closeups are in `build/panda-raccoon-nose-review/after.png`. Review: **9/10** for
correct overlap, unchanged placement and retained left-over-right eye order.

## Final validation

The panda/raccoon nose-layer recheck passes **61 tests** covering animal artwork,
all packaged animal sources and creator GUI integration. Its report is
`build/panda-raccoon-nose-final.xml`. Ruff lint/format and mypy remain clean.

The shared animal layering regression passes **69 tests**, including all 42 eye
projections, matching blinks, every packaged animal's current SVG sources, catalog
animation evaluation and creator GUI integration. The current report is
`build/all-animal-eye-layers-final.xml`. Ruff lint/format checks pass for all 356
Python files, and mypy passes all 195 source files.

The broad hand regression passed 80 tests; the final orientation/replacement
group passed 22, and the anatomical thumb/socket recheck passed 10. The combined
animal/catalog/creator/hand suite passed 46. After the owl correction and asset
rebuild, the animal/catalog/creator recheck passed 27. The final perspective,
eye/blink and packaged-source recheck passed 28. These reports contain **108 distinct
passing tests**, with no failures. Reports are `build/open-hand-regression-final.xml`,
`build/open-hand-orientation-final.xml`, `build/open-hand-sockets-final.xml` and
`build/animal-hand-final.xml`, plus `build/owl-animal-final.xml` and
`build/owl-perspective-final.xml` for the owl corrections.
Ruff lint/format checks pass for 356 Python files;
mypy passes all 195 source files.
