# Flat scene templates and catalog cleanup

Reviewed on 2026-10-29 in the owner's timezone. All GUI/application validation
uses the offscreen Qt platform and isolated preferences. No foreground windows
or OS pointer movements are used.

## Review: 8.5/10

| Criterion | Score | Evidence |
| --- | --- | --- |
| Visual clarity | 2/2 | Six distinct flat environments rendered through the actual application; open staging areas, cohesive palettes, no outlines or gradients |
| Editability and portability | 2/2 | Each Scene has five named independent SVG parts; each Background has one composed part; sources, meshes, parenting and ownership survive save/reopen |
| Placement and performance | 2/2 | Centered preview/drop placement and one-step Undo verified; two triangles per part, prebuilt PNG cards, no running physics or automatic animation |
| Catalog integrity | 2/2 | 487 entries across 18 packs; four obsolete aliases/demo entries and unused posters retired; working reusable packs retained; populated plugin/user categories remain dynamic |
| Platform/stress coverage | 0.5/2 | Windows offscreen checks; native input and Linux/macOS untested; one native fault in the initial combined diagnostic run was not reproduced in isolation or the later suite |

## Visual review

Each environment's layered Scene and single Background render within a mean
channel difference of 0.5/255 at 480 × 270, retaining full canvas coverage.
The reviewed contact sheet is `build/scene-template-review/contact-sheet.png`;
all twelve full template renders are alongside it.

| Environment | Visual score / 10 | Criteria |
| --- | --- | --- |
| Sunlit meadow | 9 | Clear depth bands, open path and soft foreground framing |
| Pine forest | 9 | Readable clearing, distant trunks and separate framing vegetation |
| Coastal cove | 8.5 | Distinct surf/beach/island bands and a clear staging area |
| Moonlit rooftops | 8.5 | Readable night silhouettes, window rhythm and open rooftop stage |
| Cozy room | 9 | Balanced furnishings, clear floor and independently editable decor layers |
| Desert canyon | 8.5 | Distinct mesas, winding trail and sparse readable foreground props |

These are static authored environments, without generated parallax behaviors or
tile streaming. Their layers can be animated independently using existing tools.
Canonical vectors live under `assets/scenes/`, with CC0 provenance and an offline
rebuild script. Packaged browsing loads PNG cards rather than evaluating scenes.

## Cleanup

Removed **Generic biped** and **Human side-view**, which duplicate Human landmarks;
**Dog structure**, which duplicates Cat / dog quadruped; and **Original prop
artwork**, the old study asset superseded by the authored Props collections.
The source generators no longer create them. Unused members are removed from the
starter archive and the four corresponding canonical posters are deleted.
`build/content-curation/original-starter.rigpack` retains the local recovery copy.
Internal deformation studies still use their required source artwork. Installed
user packs, existing project data and working character/motion collections are
not modified.

## Validation

The latest result for each of **52 tests passes**, including all twelve portable
template variants, six real render comparisons, catalog discovery/cleanup,
browser previews/installation, plugin content and Object/Scene workflows.
`build/scene-templates-verified.xml` consolidates the original report and the
Object/Scene recheck; both original reports remain available. The recheck selects
the retained Human landmarks template by exact name because metadata search
correctly also matches other human rig entries.

The initial combined run hit a native access violation after the 45-second
diagnostic dump began in an existing long character-performance preview test.
That test passed in isolation in 58.23 seconds. The later combined run used a
90-second diagnostic threshold and did not reproduce the native fault. The
cause of the first native fault is unconfirmed; it is not claimed fixed.

Ruff lint and format checks pass for changed source/generators/tests. Mypy passes
for all **212 source modules**. The source app passes **23 headless end-to-end
checks**, covering the previous Object, scene, binding, timeline, pivot and bone
workflows plus real scenery card discovery and both scenery drop variants.

`Build_Rigora.bat --no-pause` succeeded. The final bundle is
`dist/windows-amd64-20261028-230037-f7e717/Rigora/Rigora.exe`; keep its entire
bundle folder together. The host generates folder timestamps independently of
the owner's timezone used for the review date above.

The exact executable passed all **23 offscreen end-to-end checks**, exit code 0.
Evidence is `build/scene-templates-compiled-headless/run-1.json`; the reviewed
capture is `scene-templates-workspace.png` beside it. The bundled starter and
scenery packs match the canonical source bytes exactly, all 36 canonical scenery
SVG files are present, and the retired posters are absent. The temporary test
plugin/profile are outside the shipped app; owner preferences were not changed.
