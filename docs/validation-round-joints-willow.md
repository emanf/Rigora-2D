# Round character joints and Willow performance — 2026-10-21

## Character artwork

All 23 bundled character templates have revised SVG limb artwork and layer order.
Hands render above both arm segments. Shoes/paws render above both leg segments.
Forearms remain behind upper arms, and shins behind thighs; far-side limb groups
retain their depth behind the torso. Animation clips, parenting and skin ownership
are preserved.

Upper/lower limbs use tapered shapes tangent to circular caps centered on the
actual bone endpoints. The two parts meeting at a joint share a radius. Wrist
and ankle openings use the same radius as the connected forearm/shin. Limb and
joint outlines are removed while facial, garment, finger, shoe-lace and sole
details remain. Shoe details stay inside the new ankle silhouette.

`test_character_joints.py` measures exposed joint arcs in rendered SVG alpha at
4× resolution, including parent tips and child roots. Arc radii agree within
pixel rounding, match across each connected pair, remain unclipped and have no
dark center outline. The check covers elbows, wrists, knees and ankles/paws in
all 23 templates and verifies hand/foot layer order. Existing joint stress,
vector deformation, planted foot and gait-contact tests cover real skinned output.

Actual evaluated artwork was rendered again for all 23 characters with
`tools/review_templates.py`; results are under `build/joint-refresh/final/`.
`build/joint-refresh/connected-joints.png` isolates elbow, wrist, knee and ankle
connections at −110°, −65°, 0°, 65° and 110° bends. No global filter removes
outlines from unrelated imported artwork, and saved scenes retain their own assets.
Refresh Templates and place fresh instances to use the revised artwork.

## Willow diagnosis and changes

Willow contains 21 bones, 20 live spring rules and 22 SVG mesh objects. Before this
pass, every evaluated frame replayed the spring history from the beginning of
its bounded window. Each spring also recomposed its complete subtree, repeatedly
visiting shared descendants. Unprofiled evaluation at sequential frame 73 took
about 167 ms. Profiling confirmed simulation and subtree recomposition dominated.

The evaluator now retains one completed canonical 60 Hz integer tick and its
spring state. Forward playback within that same history window extends it only
through newly elapsed ticks. Fractional display samples use copied simulation
state, so asking for an intermediate time cannot affect the next integer tick.
Backward seeks, loops and shifted history origins reset the cursor. Transient
overrides bypass it. New compiled scenes/clips have new cursors. This is a pure
evaluation cache: authored transforms, undo history and saved files do not change.
Cursor memory is proportional to the rig, rather than the number of played frames.

Each spring pass now resolves the parent-first hierarchy once. Nonspring
descendants still inherit simulated ancestor transforms, and numeric validation
remains in place. Existing pinned bases, mirrored/nonuniform scales, nonzero
pivots, bounded axial strain and baking use the same solver.

Random/backward seeks still reconstruct at most the existing six-second history.
A shifted window in a long clip also reconstructs that history; this change does
not alter the original bounded-history solver convention. All bundled spring
example clips fit within a stable window. Bake through Secondary motion & physics
for long settling clips when ordinary FK keys are preferable.

## Measurements and reproducible checks

Seven-sample offscreen diagnostic medians at 1440×900 on this host:

| Willow operation | Median |
| --- | ---: |
| Hand pan with completed repaint | 2.93 ms |
| Pan with artwork selected | 3.07 ms |
| Sequential playback, including integration, skinning and painting | 11.30 ms |
| Cached repaint | 2.38 ms |
| Repeated frame evaluation | 0.88 ms |
| FK drag and paint | 16.23 ms |

Sequential engine-only frame 73 evaluation measured about 4 ms after the preceding
frame, versus about 167 ms before. These are host measurements, not universal
frame-rate guarantees. Reproduce the GUI workload with:

```text
.venv/Scripts/python.exe tools/benchmark_workspace.py --case willow --samples 7 --output build/willow-performance-final
```

The resulting record is `build/willow-performance-final/workspace.json`.
`test_spring_playback_performance.py` counts actual integration calls across 90
frames to prevent a history-replay regression without fragile timing thresholds.
Repeated integer samples do no integration. Cached results are compared with
uncached reconstruction across fractional times, backward seeks, loop restarts,
transient overrides and windows after six seconds. Existing dynamics tests also
verify editable bake parity and save/open behavior.

Preview/export forks retain compiled scene data but receive independent spring
cursors. A scratch seek cannot reset or advance the live document's simulation.
The focused fork/dynamics/workspace recheck passed all 23 tests.

## Final validation

The complete suite passed **513 tests**, with one existing Windows symlink
capability skip, in 519.87 seconds. Nineteen Qt drag-event deprecation warnings
remain. Records are `build/round-joints-willow-tests.log` and
`build/round-joints-willow-tests.xml`. Ruff lint/format checks pass for the full
repository, and strict mypy passes for all 131 source files.

Save current work and restart Rigora to load the engine changes. Refresh Templates
and place new character instances for the revised vector artwork/layer order.
Existing projects keep their embedded art and were not overwritten by validation.
