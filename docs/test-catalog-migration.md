# Current catalog regression fixtures

The maintained suite targets the original SVG stick-character catalog and the
owner's paired glove vectors. Tests must not require removed source packs,
procedural replacement hands or the retired PNG Character Creation generator.
Imported PNG artwork remains supported and tested independently.

## Fixture policy

`catalog_cache_root` prepares real immutable content once per test cache. Each
test retains separate preferences, projects, history and installed user packs.
`current_pack` reads these actual packs. Tests that explicitly supply a cache
root retain cold-generation behavior. Automation test injection authorizes only
that generated fixture directory in addition to its normal workspace roots;
the production API boundary is unchanged. The CLI test copies a prepared catalog
inside its authorized workspace, rather than timing a cold catalog render with
a short process timeout.

Behavior checks use small authored SVGs where catalog identity is irrelevant.
Real template drag, vector decoding, animation and ownership tests continue to
exercise the generated packs. Catalog counts now describe the current 287 items,
not the removed 487-item inventory. Creator and Templates identities remain
separate. Legacy contact and pin fixtures remain explicit compatibility tests.

## Replacement coverage

| Retired fixture assumptions | Maintained coverage |
| --- | --- |
| Removed `character_art` assembly, old human/animal/robot cast and source packs | `test_current_catalog_compatibility`, `test_character_creation`, `test_creator_visual_options`, `test_creative_library`, current template drag/track tests |
| Generated open-hand contours, hair caps and old facial-part topology | Supplied-vector `test_creator_gloves_feet`, `test_hand_attachment_mirrors`, `test_creator_expanded_wardrobe`, `test_creator_sprigs`, current expression tests |
| Old 18-items-per-family catalog quotas | Actual option-source uniqueness and nonempty rendering in `test_creator_visual_options`; all current template parts/serialization in catalog compatibility |
| Old eye sprite groups | Current independent authored eyes and continuous blink channels; legacy descriptors remain accepted where present |
| Old wizard slot/list controls | Actual square cards, separate default/retention actions, isolated preview transport and publish workflows |
| PNG Character Creation parity | SVG-only format validation; imported-raster palette animation, color/orientation and source-byte preservation remain tested |
| Removed scene/prop/vehicle projection packs | Authored backdrop/ball selection, depth, drag/drop, pivot and deletion regressions; current object sources are parsed/rendered |
| Old spring-example pack paths | Canonical `spring_presets`, continuous/random-seek spring evaluation and editable templates |
| Legacy floor controls and skinned membership | `test_legacy_managed_contacts` and retained posed-pin/legacy Object Editor tests in `test_creator_game_cast` |
| A drawn bone was the skeleton's first/only root | Explicit protected Rig Root plus deforming chains, selectable root silhouettes, branch deletion preserving the master, whole-Object cascade and native Godot root export |
| Every premade carried a default saved skin and all hand gestures | Tests author named palettes and retain explicit supplied-hand alternatives before exercising saved-look cards and scene keys |
| Library insertion automatically opened Object Editor | Scene insertion stays in Scene; tests explicitly enter Object Editor when needed |
| Rectangular source rows and arbitrary painted preview pixels | Shared square-card dimensions, evaluated placement anchors and actual visible-artwork selection |

These migrations do not authorize excluding current failures. A collection pass
alone is insufficient; report full execution separately from targeted checks.

The migration also exposed real regressions, repaired in the shared implementation:
authored SVG parts could not be rebound without import-grid metadata; inserting a
key between dense Bézier samples could leave unordered time handles; Objects card
viewports rejected Scene drops; Select All/Delete included a protected root and
blocked clearing Object contents; and revealing Edit Mesh could leave almost no
room for its controls. These retain actual pointer, service, pixel and Undo coverage.

The final complete sweep also identified animal tests targeting removed species,
an assumed 24-frame Puppet walk and a spring rejection aimed at the first drawn
bone. These now exercise every current animal and turnaround, the action's actual
FPS-adjusted period, and the protected Rig Root. Loop checks use repeating playback
and numerical pose tolerances. Full-scene package sharing additionally stores its
project JSON as a bounded member rather than overflowing the lightweight manifest;
its regression preserves every source byte and project record on roundtrip.
