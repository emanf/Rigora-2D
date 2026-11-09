# Interactive performance validation

Validated on 2026-11-04 using Python 3.12, PySide6 6.12 and the source application
with Qt's offscreen platform. No executable bundle was built. Performance is the
highest product priority in `AGENTS.md`.

## Changes

Bone drag planning no longer publishes reusable-object definitions from temporary
solver documents. Actual release still publishes linked changes through the normal
document command and records one undo step. Rest and animated preview evaluators
reuse compatible deformation compilation. Animation switches reuse that compilation
only while its geometry, deformation stages and solver registry still match.

Dense SVG meshes with a localized edit render the large unchanged affine region
with one boundary clip, then render changed triangles normally. Boundary extraction
preserves holes; ambiguous topology falls back to ordinary triangle rendering.
Original SVGs remain the rendering source at the current output resolution.
Native Qt transforms map mesh points for paint and picking, and topology markers
use grouped native point drawing while retaining selection, weight and pin styles.

Creator color previews no longer generate discarded portraits or full artwork just
to calculate framing. Temporary appearance documents skip reusable-object
publication. Rig preparation remains debounced and card preparation stays off-thread.

## Measured results

Each row uses the median of 12 warmed operations, except color changes, which use
six. Changing-frame measurements include synchronous viewport repaint, not just
cached static painting. These are host-specific timings rather than universal
frame-rate guarantees. Baseline and final runs used the same representative scenes.

| Operation | Before | After | Speedup |
| --- | ---: | ---: | ---: |
| Animated character bone solve | 38.5 ms | 9.4 ms | 4.1x |
| Rest-pose character bone solve | 26.3 ms | 5.6 ms | 4.7x |
| Rest-pose bone solve plus repaint | 37.2 ms | 16.5 ms | 2.3x |
| Dense mesh edit plus repaint | 82.7 ms | 31.9 ms | 2.6x |
| Creator action switch | 8.5 ms | 4.4 ms | 1.9x |
| Creator immediate color preview | 19.4 ms | 11.5 ms | 1.7x |

The character was the current Nova preset with its default actions. The mesh was
a skinned SVG with 1,089 vertices and 2,048 triangles, with one vertex changing each
sample. Creator measurements used its actual window, action selection, playback
tick and live palette update paths. Raw JSON and cumulative profiles remain in
`build/interaction-performance/` (`baseline` and `latest`).

Creator changing playback frames remained around 11 ms; this change does not
establish a playback speedup. Mesh evaluation alone remained around 3 ms. Dense
changing-frame mesh drawing still exceeds the 16.7 ms budget for 60 fps in this
offscreen case. Topology painting and deformation evaluation remain measurable
costs. Broad deformation, larger scenes, cold asset loading and physical desktop
presentation require separate profiling; this report does not claim those are
all smooth.

## Verification

The focused suite passed **70 tests**. Expanded rendering and coordinate cases
passed **12 tests**, including six already in that suite: **76 unique tests**.
Coverage includes isolated preview planning, linked publication on commit, undo,
deformation-plan reuse/invalidation, fresh-evaluator equivalence, native mapping,
localized vector edits at corners/interior, alpha, topology holes, artwork caches,
pan/picking alignment, dense mesh previews, Creator card modes and root workflows.
Optimized vector pixels were compared against the ordinary triangle renderer with
a difference bound of 0.5% of the output image to allow clip-edge rounding.

Ruff lint and formatting passed for all 489 Python files. Mypy passed for all 267
source files. The interaction benchmark is reproducible with:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_interaction_performance_gui.py -q -s --basetemp build/interaction-benchmark
```

Use a fresh temporary-directory name if the host's test-folder ACLs require it.
`RIGORA_PROFILE_PHASE` changes the output prefix; the default is `latest` and does
not overwrite the recorded baseline. Timing is diagnostic, while bounded work,
geometry equivalence and document semantics are enforced as regression assertions.

Review score: **8.5/10**, based on measured latency reductions, bounded preview
work, preserved vector quality, document/undo correctness and regression coverage.
The remaining gap is dense-mesh frame time and lack of a physical display timing
measurement.
