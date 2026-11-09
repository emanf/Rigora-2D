# Workspace performance validation — 2026-10-20

The performance pass targets shared input paths, not a reduced-detail character variant.
Original art, meshes, editable bones, animation keys and project files are retained.

## Follow-up: hand panning, detailed scenes and multiple projects

The follow-up removes camera translation from part rasterization, retains mesh editor
overlays, indexes bone/scene lookups and avoids describing hidden vertex channels.
Built-in deformation retains one immutable result per mesh, keyed by sampled values,
weighted-bone/object matrices, image-area pins and bind-reference validity. Unrelated
motion reuses geometry; custom deformer plugins continue to execute on every evaluation.
Spring preview reuses the existing deformation compilation when topology is unchanged.

Artwork pixels are cached per part in zoomed scene space. Small camera changes move
those pixels; zoom/DPI, actual source, geometry and wireframe changes invalidate them.
Large parts retain a padded visible window and refill exposed areas as needed. Up to
1,024 parts share a 64 MiB pixel budget. Admission protects parts awaiting their paint
so over-budget scenes avoid a cascade of cache misses. A separate full-view composite
handles unchanged repaints. Original SVG renderers remain the source at each resolution.
Source arrival invalidates only parts using it; unrelated thumbnail arrival does not
redraw scene artwork. Mesh dots/topology retain their own native picture and pixel layer.

Each project keeps a source cache. The active tab retains its existing 128 MiB raster
budget; at most three inactive caches share 64 MiB, with a separate renderer-count cap.
Closed tabs release source caches and selection state; a weak-reference regression
checks document reclamation. Source descriptors and external base paths guard stale
worker results. Only two passive decodes run at once, placing current-scene assets
ahead of unused thumbnails; a new tab takes the next free worker. Inactive playback
stops. Shutdown drains image/library workers before releasing GUI signal ownership.

Seven-sample medians, same host, Qt offscreen, 1440 × 900 shell, fully decoded sources.
The final tool registers the normal Windows text font when offscreen discovery cannot
find it, so scene labels and UI text are included:

| Workload | Triangles / parts | Hand pan ms | Selected-art pan ms | FK drag + paint ms | Cold paint ms |
|---|---:|---:|---:|---:|---:|
| Boy | 3,346 / 16 | 2.50 | 2.69 | 15.10 | 37.95 |
| Girl | 5,436 / 16 | 2.61 | 2.79 | 16.66 | 61.18 |
| Three characters, in memory | 12,128 / 48 | 4.61 | 4.86 | 23.60 | 93.13 |
| Ten characters, in memory | 43,910 / 160 | 11.14 | 12.07 | 56.10 | 299.30 |
| Density 32 / Alignment 10 | 6,626 / 1 | 2.20 | 2.43 | 8.31 | 26.43 |

Dense mesh **editing** with visible vertex dots/topology takes **2.38 ms** per hand-pan
update. An earlier diagnostic measured 56.61 ms after the artwork-only pan fix. The early ten-character
case exposed the old 128-part ceiling and its sequential cache churn. The final scene has
170 bones and retains full-detail source geometry. No proxy or automatic detail reduction
was introduced.

Cycling three populated project tabs, including UI binding and completed paint, takes
**42.51 ms median / 44.47 ms maximum** after warm-up, with **zero redundant decodes**,
18.0 MiB of cached raster previews and no inactive playing sessions. Each document's
history, selection, playhead, camera and original SVG renderer remain independent.

The repeated `evaluate` measurement samples the same frame and benefits from memoization.
The changing-frame measurement varies time and includes evaluation plus paint: 44.41 ms
for the boy, 71.58 ms for the girl and 83.67 ms for the ten-character fixture. Only the
selected clip's targets animate in multi-character fixtures; these numbers do not imply
that all characters animate simultaneously at that cost. A cold ten-character paint
takes about 300 ms. Fully changing dense artwork remains CPU bound.

**Storage scope:** boy, girl and dense fixtures serialize to approximately 2.77, 4.17
and 2.55 MiB of current formatted metadata. The three-character and ten-character scenes
are **in-memory stress fixtures**, with 9.71 and 34.69 MiB metadata; they exceed the
existing 8 MiB metadata cap and are not claimed as saveable/openable package workloads.
The tab workload uses separate individually bounded projects. Storage limits were not
raised; larger project storage is an explicit next feature proposal.

Reproduce the full workload or one case:

```powershell
.venv/Scripts/python.exe tools/benchmark_workspace.py --samples 7 --output build/performance/verified-readable-ui
.venv/Scripts/python.exe tools/benchmark_workspace.py --case tabs --samples 7
```

Raw final measurements are in `build/performance/verified-readable-ui/workspace.json`.
Earlier pan measurements are in `build/performance/pan-before/workspace.json`; the early
ten-character stress result is in `build/performance/large-scenes-final/workspace.json`.

Validation: **488 passed, 1 existing Windows symlink skip** in the complete suite;
**64 passed** in the final focused run after source-cache/channel-picker refinements;
**25 passed** in a final cache-lifetime/rendering run, including collection of evicted SVG renderers;
**16 passed** in the final navigation/source-cache run at 200% display scaling.
Ruff lint/format and strict mypy passed. Pixel comparisons check revealed offscreen art,
fractional panning, oversized-window refills and original vector rendering. Work-count
tests cover 160 retained parts, overlapping large parts, precise hit geometry, all three
pan gestures in scene/bone/mesh modes, cache invalidation and plugin solver behavior.
Canonical character pack SHA-256 remains
`1954d4fb2326b917ce5abfab9222ba17324c27c2afc0104c5027771abc4c0720`.

See [professional feature priorities](professional-feature-priorities.md) for GPU rendering,
diagnostics, larger storage, foot contacts, source revisions and optional playback proxies.

## Changes verified

- Entity traversal follows schema fields that can actually own records, skipping UV/triangle scalars.
  Fixed record schemas and UUID normalization are cached; duplicate IDs and graph references remain validated.
- Bone solvers stage only the transform graph. Standard live poses use transient local overrides in the same
  evaluator; keys are published together on release. Springs, sampled tracks and layered blends retain the
  full authored-key preview path. Scratch sessions share immutable compilation with separate transport.
- Mesh previews evaluate once per actual input change. Fully applied deformers avoid redundant blends,
  and stable geometry/UV/pin metadata is compiled once.
- Rigid SVG/raster meshes render once through their real mesh boundary, including holes.
  UV inverses and unique wireframe edges are cached. SVGs still use original vector renderers.
- One screen-resolution art layer avoids repainting textures on cursor/selection updates. Independent
  part tiles reuse unchanged artwork during bone edits. The initial cache had a 128-part ceiling;
  the follow-up above replaces that limit and corrects panning/source invalidation.
- Scene outlines and hit tests avoid rebuilding all mesh polygons when nothing drawable is selected.
- Subdivision retains the last completed preview while one worker prepares the latest requested settings.
  Slider changes are coalesced at a bounded cadence; live preview is not restricted to mouse release.
- Hidden content-library specimens stop animating, including hidden browsers created by shelf application.

## First-pass measurements

Run from the repository root with the installed GUI dependencies:

```powershell
.venv/Scripts/python.exe tools/benchmark_workspace.py --samples 7 --output build/performance/final
```

Qt runs offscreen at a 1440 × 900 window size. These are seven-sample medians on this host,
after warm-up and asset discovery. FK drag varies the angle, evaluates real skinned geometry and paints it.
Changed-frame paint includes engine evaluation; cold paint explicitly clears retained artwork.
These are diagnostic measurements, not timing assertions or a promise for every machine.

| Workload | Triangles | Hover ms | Retained repaint ms | FK drag + paint ms | Changed frame ms | Cold paint ms |
|---|---:|---:|---:|---:|---:|---:|
| bones | 0 | 0.23 | 1.45 | 2.45 | 1.52 | 1.47 |
| sources | 864 | 0.26 | 1.47 | 3.30 | 1.66 | 4.12 |
| boy | 3346 | 0.51 | 1.81 | 20.95 | 46.27 | 37.83 |
| girl | 5436 | 0.51 | 1.83 | 25.02 | 74.08 | 61.98 |
| three-characters | 12128 | 2.64 | 3.69 | 46.13 | 65.78 | 99.19 |
| dense-wireframe | 6626 | 0.24 | 1.49 | 7.31 | 1.71 | 28.72 |

The dense case uses **Density 32, Alignment 10**, with 6,626 triangles and 12 bones.
Its initial unchanged-geometry repaint measurement was about 167 ms; retained updates are now about 2 ms.
The original boy diagnosis found about 3.7 seconds per drag under cProfile, dominated by repeated graph
walks and project/key validation. That profiled number is not directly comparable with this unprofiled table.

## First-pass validation and practical limits

The full regression run passed **456 tests**, with one existing Windows symlink skip, in 578.25 s.
Additional focused runs covered the new transient-pose, cache invalidation, hidden preview and dense live
subdivision checks, plus existing scene selection, FFD, rigging and template workflows. Ruff lint/format
and strict mypy passed. The new tests check work counts and correctness rather than brittle wall-clock limits.

The source/rendering path is still CPU based. A cold, fully changing high-detail character or scene can
take longer than a simple edit; the table exposes this cost rather than claiming universal 60 fps.
Dense subdivision generation is asynchronous and can take longer than its subsequent repaint. No graphics
backend, dependency, project format or quality-reduction toggle was added. Restart an already-running
Rigora instance to load the revised Python modules.

## Vector template refresh — 2026-10-21

The reference characters now use independent SVG parts with 136/144 triangles,
instead of dense partitions of a shared full-body PNG. A seven-sample rerun
measured 6.72 ms changed-frame painting for the boy and 9.81 ms for three characters;
three-character hand panning measured 4.61 ms. Three populated tabs switched in
59.94 ms with no redundant decodes or inactive playback. See
[the template validation](validation-vector-templates-and-springs.md) for final
counts, evidence and limitations. Older measurements above describe the previous
artwork workload rather than the current vector templates.

## Willow spring playback — 2026-10-21

Willow exposed repeated history reconstruction and repeated subtree recomposition
inside the spring solver. Incremental canonical ticks and one parent-first spring
pass now give an 11.30 ms median for sequential late-clip playback including
skinning/painting, and 2.93 ms for hand panning on this host. See
[the focused validation](validation-round-joints-willow.md) for measurements,
determinism checks and the remaining bounded-history seek behavior.
