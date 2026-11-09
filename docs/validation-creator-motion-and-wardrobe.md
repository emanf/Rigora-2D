# Creator motion and wardrobe validation

Validated on Windows with the source application, PySide6 and offscreen Qt on
2026-11-04. No executable bundle was compiled and no visible application window
was opened during testing.

## Shoulder joins

Upper-arm artwork starts inside its shoulder socket instead of extending a
rounded cap behind the pivot. Upper sleeves taper into that socket and leave
the attachment edge unlined. Elbow overlap remains covered by the cuffs.
Joint positions, parenting, part replacement and bind matrices are unchanged.

Little was rendered with bare arms, a tee, shirt and jacket in a cross-body pose.
Raster tests check both shoulders in all five views and four SVG treatments.

## Appearance choices

| Category | Available choices | Changes |
| --- | ---: | --- |
| Hands | 26 | Six additional simple silhouettes, including two plain fists and a round hand without cuff or finger markings; 10 existing contours revised |
| Eyes | 15 | Almond, wide, half-lidded, sparkle, cross and heart styles; existing blink/wink registration retained |
| Glasses | 11 | Six additional frame styles; lenses follow eye positions, far-lens foreshortening and single-lens profile views |
| Pants | 15 | Cargo trousers, leggings, wide trousers, track pants, Bermuda shorts and cuffed jeans |
| Footwear | 11 | High tops, canvas shoes, dress shoes, ankle boots, rain boots and slippers; existing footwear redrawn with separate upper/sole details |
| Neckwear | 9 | Skinny/striped ties, cravat, long scarf and neckerchief; scarf folds, wrap and tails redrawn |
| Hair | 31 | Six additional curl/coil and ponytail styles; loose curls and tails retain separate animated hair bones |

Counts include empty choices where offered. New items use the existing
independent color, default selection and retained-alternative systems. Plain
hand choices preserve the same wrist anchor as the detailed gloves.

The cap has a closed, outlined crown and visor. Stubble follows the lower face
and renders below lip-sync mouths. Chinstrap geometry follows the jaw rather
than a narrow floating U under the mouth. Scarves sit on the neck, above coat
front panels and below a crossing near arm. Tests cover that placement explicitly.

The new hairstyles use secondary-motion bones. They do not automatically add a
Spring physics constraint; that remains an explicit authoring choice.

## Run and game jumps

The lower-body Run reference comes from Kay Lousberg's CC0 `Running_A` clip.
Jump and High jump use the CC0 `Jump_Full_Short` and `Jump_Full_Long` clips;
Hop adapts the short jump with lower height and faster timing. Research used
the [official animation catalog](https://kaylousberg.itch.io/kaykit-character-animations)
and the [official Adventurers repository](https://github.com/KayKit-Game-Assets/KayKit-Character-Pack-Adventures-1.0).

Pinned source URL, SHA-256, author notices and reproduction instructions live in
`assets/motions/kaykit-run/` and `assets/motions/kaykit-jump/`. Only 16,396 bytes
of numeric JSON are bundled across both references. No source models, textures,
3D runtime, executable or online service is needed by the application.

Rigora retargets ankle paths to fixed-length legs. Run has folded knee recovery,
flight, softened foot pitch, restrained torso lean and separately authored arm
opposition. Source weapon-carrying arm poses are not used. Fast Run and jump
recovery is baked at one-frame intervals into normal editable Bezier keys.

Jump includes planted anticipation, takeoff, flight and landing compression.
Hop, High jump, Crouch and Stretch bring Creator to 13 source actions. Reusable
Templates now contain 85 skeletal motions and 287 total entries. Jumps are
vertical performances in place; scene travel can be animated on the Object.
Animal variants retain fixed-length limbs and real changing poses.

Walk motion was compared against pre-change fingerprints at 49 phases for
17 designs across five views: **85 of 85 comparisons matched exactly**.

## Validation and timing

- Broad focused regression run: **418 passed**, including the motion library,
  root poses, wardrobe replacement, source/baked trajectories, loop seams,
  all expanded previews and actual Creator action selection.
- Fresh scarf and Creator-window checks: **23 passed**, including two new scarf
  cases, bringing distinct focused coverage to **420 cases**.
- Two performance checks passed, including an additional Walk/Run/Jump playback
  measurement. Ruff lint/format passed for 503 Python files; mypy passed for
  272 source files.

Final per-action timing includes actual playback and vector repaint, 48 samples
per action after preparation:

| Action | Median | 95th percentile | Maximum |
| --- | ---: | ---: | ---: |
| Walk | 13.88 ms | 15.93 ms | 18.61 ms |
| Run | 14.04 ms | 16.73 ms | 18.25 ms |
| Jump | 13.72 ms | 15.96 ms | 16.55 ms |

The broader interaction profile measured 5.99 ms median action selection and
15.45 ms median live color edits. These are host-specific observations, not a
guarantee of 60 FPS or an improvement claim for every editor workflow. The same
profile still has slower dense-mesh editing, outside these artwork changes.

Evidence is retained under `build/creator-review/` and
`build/interaction-performance/creator-expanded-final*`. Generated previews were
refreshed successfully at artwork revision 24, including 549 generation steps.
Temporary source models, test data and the two superseded caches from this work
were removed; custom user packs were preserved.

## Review

Self-review score: **9/10**. Criteria: shoulder and wrist attachment, visible
variant differences, view/layer consistency, editable fixed-length motion,
offline source provenance and measured Creator responsiveness. Rendered contact
sheets and the actual Creator window were inspected, and discovered issues
were corrected before the final checks.

Remaining scope limits: aesthetic approval is subjective; existing placed
characters keep their authored artwork and clips. Create a new character or
place a refreshed Template to use these generated sources. This change does
not silently overwrite existing project artwork or add Spring constraints.

## Tie attachment follow-up

Tie, skinny tie, striped tie, bow tie, cravat and neckerchief now attach at
the neck's base joint instead of nine units down the chest. The bow-tie source
sheet is centered on its knot. Scarves retain their higher neck wrap and existing
layer order. Parenting, binding, colors and animation evaluation are unchanged.

An actual raster regression failed at the joint before the correction. All
**118 focused checks passed** afterward, including six neckwear choices across
five views, scarf placement, shoulder sockets, retained variants and the real
offscreen Creator window. Ruff lint/format and mypy passed. Source contact-sheet
evidence is in `build/tie-anchor-review/ties-at-neck-joint.png`.

Review: **9/10**, using joint attachment, knot centering, preserved scarf height
and compatibility with existing wardrobe controls as the criteria. The generated
artwork revision is 25; existing placed artwork is not automatically replaced.

## Hand orientation follow-up

Right-facing Front 3/4, Side and Back 3/4 now use matching forward-thumb
orientation on both hands. Contours record their own thumb chirality, since
the relaxed and mitten source gestures face opposite directions before
reflection. Front and Back retain their established mirrored arrangement.
The near, viewer-left hand has a clean dorsal surface without palm creases;
its cuff and wrist attachment remain present. Directional up/down gestures
retain their vertical extent. The rule is also recorded in `AGENTS.md`.

All **150 focused regressions passed**, including all 26 gestures, five views,
three reference thumb silhouettes, wrist coverage, cuff preservation and
animated wardrobe swaps. Both production Creator GUI checks passed offscreen.
Ruff lint/format passed for 506 Python files; mypy passed for 272 source files.
The five-view reference outfit and all side-view glove pairs were visually
inspected in `build/hand-view-review/`.

Actual offscreen Creator playback and repaint measured 9.97–10.22 ms median
across Walk, seven runs and Jump, with a 13.38 ms maximum observed frame.
These host-specific samples are retained in `build/hand-view-review/playback.json`;
they are not a speedup claim or a guarantee for every outfit.
Artwork cache revision 27 completed all 562 preparation steps. Existing project
artwork stays authored as saved; newly created characters and refreshed Templates
use the corrected gloves.

Self-review: **9/10**, using reference orientation, front-view preservation,
clean dorsal surfaces, stable wrist/cuff registration, replaceable variants
and measured playback as the criteria. Artistic approval remains with the owner.
