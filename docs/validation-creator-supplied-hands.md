# Supplied glove replacement

Character Creation now offers nine source gesture pairs and the five explicitly
approved simple styles. The supplied gestures are Relaxed, Open, Palm out,
Fist, Loose fist, Point, Thumbs out, Wave and Curled fist. Round hand, Mitten,
Flat hand, Stop and Small fist retain their prior geometry. Other previous
choices and their old generated contours have been removed from the catalog.

Both supplied SVGs were inspected. Their 18 outer contours match exactly.
The canonical asset combines the clean file's outline/interior paths with
the smooth file's unified wrist patches. All fills are white; outlines use
the character's ink color. Each hand is uniformly resized around an explicit
wrist anchor. The two source hands remain distinct rather than being replaced
by an identical mirrored contour. `assets/characters/hands/NOTICE.md` records
source digests and the registration metadata.

Front and Back retain paired handedness. In right-facing three-quarter and side
views, both thumbs face forward; the viewer-left hand uses the source outer
contour with an inset outline and no palm creases. Raster previews never become
character source art. The packaged SVG is parsed once per process; ordinary
animation playback uses the existing bound sources and does not read files.

Removed hand names in old Creator recipes resolve to an available gesture;
Simple fist resolves to Round hand and other removed choices to Relaxed.
Existing project artwork is not overwritten. Generated characters with supplied
hands carry their source notice and mixed-license metadata, without assigning
a new license to the owner's supplied art.

Verification includes wrist coverage, both source hands, all five views,
variant replacement during animation, palette independence, canonical/adaptive
cards and the real offscreen CC window. All 60 saved raster fingerprints of the
five preserved styles matched, covering both reflections, palm visibility and
three outline widths. All 18 imported outer contours exactly matched the
supplied files. The actual CC window and source contact sheets were inspected.

The final focused suite passed **204 tests**, including source generation and
publishing retained gestures into a project with undo. Two further production
CC GUI checks and the canonical/adaptive card-mode check passed separately.
Ruff lint/format passed for 507 Python files; mypy passed for 272 source files.
Artwork cache revision 29 completed all 550 preparation steps, and the generated
Template pack contains the supplied-art notices. Superseded task caches and
temporary test data were removed after validation.

Offscreen Creator playback plus repaint measured 10.10–10.30 ms median across
Walk, all seven runs and Jump, with a 12.23 ms maximum observed frame. These are
48 samples per action on the basic preset on this host, not a performance
guarantee for every outfit or a measured speedup. Evidence is retained under
`build/hand-replacement-review/`.

Self-review: **9/10**, using source fidelity, white fills, readable silhouettes,
stable wrist attachment, preserved approved styles, view consistency,
replaceability and measured playback as the criteria. Source registration and
gesture styling still allow future owner-directed art refinement.

## Matching hand follow-up

Relaxed, Palm out, Loose fist, Wave and Curled fist now reuse the intact
far-hand source on both limbs. These gestures retain their original interior
artwork instead of receiving the synthesized dorsal fill. Loose fist and Curled
fist receive the requested horizontal reflection before view-specific mirroring.
The other source gestures and the five approved simple styles retain their
existing policies and wrist attachments.

All **126 focused artwork/wardrobe checks** and both real offscreen CC GUI
checks passed. Five new regressions compare each matching pair, on both
surfaces, directly against its original SVG group with the requested reflection.
Ruff lint/format passed for 507 Python files; mypy passed for 272 source files.
Artwork cache revision 30 completed all 550 preparation steps.

Actual offscreen playback and repaint measured 10.33–10.50 ms median across
nine actions, with a 12.65 ms maximum observed frame on this host. Evidence,
including the inspected matching-pair sheet, is in `build/matching-hands-review/`.
These observations are not a speedup claim or a guarantee for every outfit.

Self-review: **9/10**, using identical source fills, requested fist reflection,
preserved attachment, view consistency and measured playback as the criteria.

The Loose fist orientation was subsequently corrected on the viewer-left limb
only (`hand.R`); the other limb retains its prior reflection. Both still use
the intact shared source fill. All 74 focused hand regressions passed, including
direct source comparisons for both limbs and surfaces. Ruff and mypy passed.
The inspected pair is in `build/loose-fist-left-review/loose-fist-pair.png`.
Review: **9/10** for the left-only reflection, preserved opposite-hand artwork
and unchanged wrist attachment.
