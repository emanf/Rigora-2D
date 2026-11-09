# Owner-authored hand pairs

Character Creation now uses only the nine left/right pairs in the owner's
`Untitled.svg`. All 18 groups and all 54 native paths were retained. A direct
comparison against the source verified every non-fill path attribute, including
IDs, coordinates, fill rules and order. Only the skin and cuff colors changed
to white; registration metadata fits each source hand to the wrist.

Each adjacent partner is used independently. The renderer no longer shares
one source hand across both sides, generates back surfaces, removes creases,
adds wrist patches or applies per-gesture flip corrections. Sketch mode also
preserves one intact hand rendering instead of adding a displaced outline copy.
View reflection, palette replacement and normal rig animation remain available.

The older generated Round hand, Mitten, Flat hand, Stop and Small fist cards
were retired to honor the source-only hand requirement. Old Creator recipes
resolve those choices to supplied Loose fist or Palm out art. Existing project
artwork remains embedded as saved.

Verification:

- **230 focused checks passed**, covering source fidelity, all views and styles,
  both partners, surface hints, reflection, colors, wrist registration, retained
  variants, shoulders and animation behavior.
- **Three real offscreen CC checks passed**, covering the current cards, all
  source actions, static/adaptive previews and measured playback/repaint.
- Ruff lint/format passed for 507 Python files; mypy passed for 272 source files.
- Artwork cache revision 32 completed all 545 preparation steps.
- The actual CC window and source pair sheets were inspected. Source comparison
  and timing records are in `build/owner-paired-hands-review/`.

Actual CC playback plus repaint measured 9.92–10.21 ms median over nine actions,
with a maximum observed frame of 11.79 ms. The benchmark samples 48 frames per
action on the basic preset on this host; these numbers are neither a speedup
claim nor a guarantee for every outfit.

Self-review: **9/10**, using preservation of supplied paths, correct pair
selection, white fills, stable wrist attachment, replaceability and measured
playback as the criteria. Artwork provenance and the original source digest
are recorded in `assets/characters/hands/NOTICE.md`.

Front-view Open, Fist, Point and Thumbs out use their viewer-left supplied source
on both limbs, with the viewer-right copy horizontally reflected at its wrist.
Back view uses the viewer-right supplied source for the same four gestures,
with a horizontally reflected copy at the viewer-left wrist. Other gestures
and views retain their source-pair policy.
All 129 focused hand checks passed, including complete raster comparisons for
the four Front and Back pairs in all four styles, alongside Ruff and mypy.
The inspected pair sheets are in `build/front-paired-review/front-pairs.png`
and `build/back-paired-review/back-pairs.png`.
Review: **9/10** for mirrored source matching, preserved vector geometry and wrist fit.

Front 3/4 Loose fist and Curled fist reflect only the viewer-right source at its
wrist. Fist uses its unreflected right source. All 141 focused hand checks
passed, including complete painted-art comparisons for all three gestures at
both wrists in all four styles. Ruff lint/format also passed.
The inspected render is `build/quarter-fist-review/front-quarter-fists.png`.
Review: **9/10** for requested reflection, source fidelity and stable wrist alignment.
