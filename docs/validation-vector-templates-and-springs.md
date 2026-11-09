# Vector templates and spring examples — 2026-10-21

## Delivered content

The offline catalog contains 145 entries, including 23 complete layered vector
characters and six live spring studies. Existing catalog identities remain stable.
The human collection covers 11 identities across 17 templates/views; six animal
templates bring the character total to 23. Every character has three editable
full-body performances, for 69 clips. Spring examples add 12 driver clips.

Human faces, proportions, hair and clothing were redrawn as independent SVG parts.
Nico/Poppy add short preschool bodies. Ari/Nova/Bolt now have their own clips.
The blue/red reference kids use 17/18 SVG parts instead of reusing a full raster
master on each mesh. They are stylized interpretations of the references and retain
their separate provenance. Heads overlap necks. The subsequent joint revision
puts hands/shoes above their limbs, with matching circular caps and no dark joint
outline; forearms/shins stay behind upper arms/thighs. See
[round joints and Willow performance](validation-round-joints-willow.md).
Original vector source bytes remain embedded.

Each identity has separate standing acting and a different gait profile, including
cadence, contact timing, stride, lift, arm/elbow carriage and torso response.
Standing locks full shoe/paw transforms. Locomotion keys release those locks and
solve from the actual proportions and vector sole support hulls. These remain
in-place cutout animations, without automatic world translation, view turning,
facial expression switching, cloth collision or continuous muscle deformation.

Daisy, Sunflower, Berry bush, Willow, Windsock and Mushroom have separate SVG
parts, skinned bones, named Spring Editor groups, stationary supports and two
editable driver clips. Their follow-through is evaluated through the real spring
solver. Mushroom also uses axial elasticity. Spring Editor opens their collection
directly and initially selects a loaded example's first existing spring group.

## Format and responsiveness

Detailed scene JSON lives in bounded archive members rather than inline catalog
metadata. Preview/Apply/drop all hydrate through `content_project`; legacy inline
scene packs continue to work. Clip choices reference validated source IDs and are
remapped along with all other imported identities. No archive extraction occurs.
The scene-member limit at this increment was 8 MiB. It is now 32 MiB to retain
larger editable action catalogs, matching the archive member bound. See the
current [content format](content-library.md) and
[production validation](production-workflow-plan.md).

People catalog metadata is 17.3 KiB for eight entries; the compressed pack is
1.10 MiB. Reference kids are a 0.24 MiB pack. The boy has 153 vertices/136 triangles;
the girl has 162/144. Their SVG deformation uses original vectors at output
resolution, not catalog thumbnails.

Seven-sample diagnostic medians from `tools/benchmark_workspace.py`, offscreen at
1440×900 on this host:

| Case | Triangles | Hand pan | Changed frame + paint | FK drag + paint | Cold paint |
| --- | ---: | ---: | ---: | ---: | ---: |
| Reference boy | 136 | 2.66 ms | 6.72 ms | 8.06 ms | 5.17 ms |
| Three reference characters | 416 | 4.61 ms | 9.81 ms | 17.88 ms | 13.14 ms |

Three populated tabs switch and paint in a 59.94 ms median, with zero redundant
decodes, 2.05 MiB of decoded raster cache and no inactive document playing.
These are measurements, not universal frame-rate guarantees. Records are under
`build/vector-refresh/performance-boy/`, `performance-three/` and `performance-tabs/`.

## Review and checks

`tools/review_templates.py` rendered all 23 character templates and six spring
studies using real application/export services, with portraits, eight-pose sheets
and 16-frame animated WebP previews for every clip. Review artifacts are under
`build/vector-refresh/final/`. Review identified and corrected over-crouched side
gaits, weak frontal arm projection, disappearing frontal shoes and overly long
spring settling pauses.

A 193-sample contact audit across all 17 human templates/views found maximum
standing foot-matrix drift of `3.42e-13` and maximum gait sole-contact error of
0.202 scene pixels. The contact record is
`build/vector-refresh/final/contact-audit.json`. Reference regression tests also
stress bent neck/elbow/wrist/knee joints in rasterized output and measure contact
between keys. Numerical contact checks complement visual review; they do not
claim physically exact motion capture.

The complete 512-test run finished with 507 passing, one existing Windows symlink
capability skip, and four stale catalog/mesh-count expectations. Those expectations
were updated and all four integration tests passed on recheck. Final spring
tuning additionally passed both spring-example tests, including actual response
against a spring-disabled baseline, visible movement in both axes, anchored bases,
connected roots, save/open parity and the Spring Editor example/preset workflow.
Thus all 511 runnable tests have passing results against the final implementation.
There are 19 existing Qt drag-event deprecation warnings.

Ruff lint and format checks pass for `src`, `tests` and `tools`; strict mypy passes
for all 131 source files. Regression coverage includes content preview/selection,
placement, Undo, persistence, automation/MCP/plugin access, tool lifecycle, dense
wireframes, navigation and multi-document caching.

## Using revised templates

Save current work and restart Rigora for Python/UI changes. Refresh Templates,
then place a fresh character to use the new art/clips. Existing placed instances
keep their saved embedded artwork. Search `young-child` for Nico/Poppy or
`reference` for the blue/red kids. Choose Performance before Apply/drag, or change
clips in Timeline. For springs, open Spring Editor → Open SVG spring examples,
or search `spring-example` under Props & accessories; choose Breeze/Strong gust
and Play, then edit a named group. Validation used isolated projects/preferences
and did not replace the owner's open project.
