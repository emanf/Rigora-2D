# Painted artwork picking — 2026-11-02

Pointer selection now checks painted coverage after the mesh broad phase.
Transparent pixels, SVG holes and empty canvas margins pass through to the next
eligible object in the evaluated render order, including Depth (Z). Scene maps
the picked part to its owning Object; Object Editor retains part selection.
Hover, double-click entry, context menus and template targets use the same rule.

`presentation.artwork.mesh_contains` renders the evaluated geometry and styled
source into a bounded 3×3 device-pixel probe. Only the center pixel determines a
hit. The renderer is shared with the viewport, so original SVG curves, source
alpha, UV mapping, mirroring and nonuniform deformation participate in picking.
SVG thumbnails are never used as hit masks. The screen-geometry cache indexes
meshes by owner and unions bounds when one owner has multiple meshes.

The content-drop fallback also uses painted coverage, preventing a transparent
front rectangle from becoming an unintended binding target. Missing source art
has no painted coverage until decoding finishes; hierarchy selection remains
available throughout loading. An existing test fixture now waits for decoded
artwork before asserting a painted hit.

## Verification

Automated checks run with `QT_QPA_PLATFORM=offscreen`, using real Qt rendering and
mouse events. Coverage includes:

- Raster/SVG holes and margins over a second object, in Scene and Object Editor.
- Rotated/skewed and mirrored geometry at normal and high device pixel ratios.
- UV flips, deformed meshes and thin SVG detail beyond thumbnail resolution.
- Evaluated opacity, visibility, editing locks and multi-mesh owners.
- Actual template, import and reusable-Object drops, including Depth (Z) ordering.
- Existing camera borders, rig-only Objects, scene context and transform pivots.
- Navigation, pointer selection, artwork rendering and mesh-editing regressions.

The regression run passed **61 tests**, with no failures or skips. The report is
`build/paint-picking-integration-final.xml`. Eight existing Qt drag-event
constructor deprecation warnings remain in the test fixtures. Ruff lint/format
checks and mypy passed against the current source.

A separate offscreen profile used an original Character Creator character with
59 meshes and 144 pointer queries over its bounds. Median query time was
1.33 ms, the 95th percentile 2.56 ms, and the maximum 7.37 ms on this Windows
machine. This is a representative local profile, not a cross-platform performance
guarantee. The raw record is `build/paint-picking-review/performance.json`.

## Review and limits

Review: **9.3/10**. Criteria: painted-coverage correctness 9.5 (40%), interaction
consistency 9.5 (30%), observed responsiveness 9.0 (20%), and edge-case coverage
8.5 (10%).

Effective alpha below 8/255 is treated as visually negligible. Opaque foreground
art still wins over fully hidden artwork. Explicit transform handles, camera
borders, empty Object markers and rig-only controls retain their own hit targets.
Marquee and Mesh Edit intentionally select geometry rather than source pixels.
Only Windows has a native runtime validation record for this change.
