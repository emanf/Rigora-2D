# Game character creator redesign

Validation on Windows, 2026-10-25. Implementation stays offline in the current
chat; the owner explicitly requested one independent character quality reviewer.
The existing application services, MVVM presentation and Qt-free rig/engine
remain the implementation path for the creator, library and Object Views.

## Artwork and replacement contracts

Ren, Rin, Mina, Milo and Mallow have Front, right-facing Front 3/4, Side,
Back 3/4 and Back views. Original front artwork remains under `assets/characters/`;
`views/` contains assembled complete SVGs. Five small game-cast content packs
retain editable vector parts, skinning, wardrobe choices and independent actions.
Packs remain within existing storage limits rather than raising archive limits.

The creator exposes 307 anatomical/face options, 222 garments/accessories,
33 coordinated sets, 22 styles, 5 character presets and 13 eye/hand states.
All 602 option cards and 18 action cards are prebuilt PNG previews. SVG sources,
never thumbnails, remain deformation and export inputs.

Individual garments have independent primary paints. Saved alternatives can
remain inactive; a dress suppresses shirts and bottoms while preserving their
saved choices. Dress bodices, sleeves and hip-bound skirts remain replaceable
parts. Garments and saved skins use card grids in Object Editor; skin cards
show saved palette colors. Clothing coverage hides bare forefeet beneath shoes
and thigh/shin pieces beneath opaque long skirts. Removing a garment restores
the covered pieces; appearance keying uses the same visibility channels.

## Review and regression evidence

`tools/review_character_creator.py --motion` checks and renders:

- 25 new cast turnarounds.
- 42 animals in 210 presentations.
- 60 household objects in 300 presentations.
- 32 scenery designs and 18 vehicles in their authored views.
- 15 reference-cast ready/walk/run loops sampled at 16 phases each, with finite
  evaluated transforms, no evaluation warnings and matching loop endpoints.
- All 613 canonical SVG sources parse and render, including the 144 standalone
  props, whose two packs were rebuilt with the same flat filled-shape treatment.

The resulting contact sheets, timed GIFs, UI captures and numeric report are in
`build/creator-cast-review/`. Inspection found and corrected front-only clothing
details on rear views, three-quarter shoe direction/coverage, and undersized
garment bounds. Filled-shape borders are removed across the creator catalogs;
intentional detail lines remain. The four vector creator packs were rebuilt.

The independent reviewer compared all five originals, all 25 new views and all
15 game loops, with additional actual-build samples for clothes, facial hair,
styles and all 18 foot choices. Seven reported defect areas were fixed and
rechecked: flat-shoe openings, facial-hair coverage, visible robot hinges, bob
length continuity, long-dress skin penetration, ponytail export bounds and bare
foot coverage. The review report and before/after evidence are in
`build/creator-cast-review/reviewer/quality-review.md`.

Object Editor foot movement was reproduced: the part transform changed while
the standing contact held the visible foot. Part edits now carry the relevant
contact target. Pin creation now inverts evaluated triangle coordinates and
captures the displayed anchor position, avoiding rejected clicks or jumps on
posed artwork. Clicking another bound part can target that part directly.
Regression checks include undo restoration and preservation of ordinary weights.
Legacy actors with empty explicit part lists now resolve their bone-bound images
through the same membership service, so Object Editor includes those images in
evaluation. Exact-name searches take priority over shorter names matched through
tags, distinguishing the new Milo from the existing Milo · Boy templates.
Mesh IDs are normalized to their owning object when entering composition, so
mesh editing retains the correct local timeline and playhead. Bare rig controls
are framed after dock layout settles. Project JSON uses compact serialization
so the complete editable action catalog fits the existing metadata bound.

The final focused creator/editor run passed **108 tests**. Ruff lint and format
checks pass for the whole workspace, and mypy passes all **183 source files**.
A complete six-batch suite sweep was followed by rechecks of every reported
failure; their result is recorded below. An initial single-process suite attempt
terminated in native Qt, so that attempt is not reported as a successful full run.
GUI tests use offscreen Qt and
isolated preferences; they do not restart or focus the owner's running app.

All **31 previously failing cases passed** the final recheck
(`build/creator-final-rechecks.xml` and `.log`). The separate final project
save/load and release-reliability check passed **27 tests**. These counts overlap
the broader suite and are not added together as a full-suite total. The only
skipped case in the complete sweep requires Windows Developer Mode for symlinks.

## Practical limits

Views are explicit representations, not an automatic 3D turn. Dresses are
editable cutout cloth with a hip-bound skirt, without fabric collision or physical
cloth simulation. Large poses may require artist-adjusted layer order or weights.
Front/back locomotion uses foreshortening and vertical foot travel; side and
quarter views give a stronger walking/running silhouette.
Stand · Still remains an unanimated pose; Stand · Ready is the subtle game loop.
The existing identity-specific choreography supplies distinct editable game
performances; the redesign does not claim motion capture or simulation.

## Animation preview responsiveness, 2026-10-26

Selecting an animation exposed a Windows scheduling stall during background
assembly. A worker was running, but its CPU-bound assembly steps could starve
GUI input. An unprofiled measurement still recorded an **1813 ms** heartbeat gap
after duplicate preview importing had been removed. Cooperative cancellation
checkpoints now yield briefly between assembly steps. The final real-window
measurement, using the desktop garbage-collection policy, recorded a longest
gap of **119 ms**. First preparation took **3.84 seconds** with the UI available;
subsequent action changes took **16–23 ms** on this host.

The builder can populate an explicitly supplied empty scratch document, avoiding
serialization, validation and fresh-ID remapping solely to reconstruct its own
preview. Existing projects are rejected as scratch destinations. The creator
keeps one full prepared appearance and filters included actions on its worker,
reusing the rig and decoded sources when only checkboxes change. Include-none
and include-all took **39 ms** and **106 ms**, without another character build;
published templates still contain exactly the checked actions.

Playback follows the authored frame rate rather than requesting 60 evaluations
per second for a 24 fps character. It advances by actual elapsed time and requests
deformation only for currently visible parts. Visibility keys, bones and tracks
still sample normally. Original SVG sources remain the rendering inputs; hidden
geometry remains available in normal editing and export evaluation. Tests compare
the optimized visible geometry exactly with the corresponding full evaluated pose.

Validation passed **10 GUI tests** and **96 core tests**. The GUI group includes
real animation selection/playback, all-action switching, wardrobe changes,
template export, closing during preparation, checkbox caching and an event-loop
heartbeat. The core group covers character assembly, playback/deformation and
the existing foot and whole-Object movement regressions. Reports and timing
measurements are in `build/creator-preview-review/`. Ruff lint/format checks pass
for 351 Python files under `src`, `tests`, `tools` and `examples`; strict mypy
passes all 195 source files.

Review score: **9/10**, based on responsiveness, bounded/reused preparation,
identical visible geometry, correct action inclusion and safe cancellation.
These are isolated offscreen Windows measurements, not a cross-platform latency
guarantee. Initial assembly still takes several seconds; it remains cancellable
and does not mutate the destination project.
