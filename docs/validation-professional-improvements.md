# Professional workflow validation

Validated on Windows from source on 2026-11-06. All GUI automation ran offscreen.
No executable was rebuilt, no user project/preferences were changed, and no
additional agent or Graphify service was used. This workspace has no Git metadata.

## Implemented behavior

- Catalog preparation runs in a cancellable spawned process, keeping its CPU
  work outside the GUI interpreter. Startup failures, cooperative cancellation,
  child shutdown and abandoned staging are covered. Warm discovery reuses the
  completed generation.
- Undo/Redo retention is configurable, with a default of 500 commands and atomic
  command groups. Explicit cache maintenance recognizes only completed generated
  revisions and preserves current/protected generations, recent data and user
  packs. No maintenance operation was run against the owner's cache. Command
  counts are reported; they are not a retained-byte memory measurement.
- Timeline value edits retain native rows, selection and expansion. Structural
  edits still rebuild correctly. Asset placement uses a ViewModel command and
  the existing shared services.
- Creator has persisted per-view hand mirrors and a source-vector turnaround
  comparison. Approved supplied hand geometry and default orientations remain
  intact. Export-motion inclusion changes reuse the ready preview; resizing the
  window preserves its viewed center, zoom and pan.
- Graph points support keyboard navigation/nudging and native numeric controls,
  including time-order limits, fixed endpoints and Undo. These controls provide
  an accessible editing alternative; painted graph points do not yet expose
  individual virtual accessibility children.
- Tagged raster imports normalize ICC colors to sRGB and apply orientation while
  preserving alpha and original source bytes. Invalid/oversized inputs fail
  atomically. Existing project assets are not rewritten. Engine export choices
  describe their actual adapter limitations.
- Regression fixes cover dense Bézier insertion, recipe cycle FPS conversion,
  authored-vector rebinding, Scene-to-Objects drops, clearing Object contents
  without deleting the protected root, visible mesh controls, audio binding
  retries and large scene-package sharing. Scene JSON is a bounded pack member;
  manifest/member/archive limits have not been increased.
- Bone overlay profiling identified repeated SVG outline expansion. Editor-only
  tiles now reuse the supplied source at twice display pixel density, bounded
  to 128 tiles / 8 MiB per viewport. Placement and rotation reuse tiles; length,
  width, tint and DPI changes invalidate them. Large or externally scaled bones
  retain direct vector drawing. Selection uses the original silhouette, and
  character SVG deformation continues to render from original vectors.
- Shared separators use a subtle neutral divider palette in both themes.
  Toolbar gradients and thick idle dock gutters are removed. Timeline has one
  thin visible top divider. Splitter hit targets remain six pixels; its custom
  height grip remains eight pixels. Floating panels and dialogs retain visible
  outlines, hover feedback and normal resizing.

## Regression evidence

The complete sweep executed **2,272 tests in four isolated pytest processes**:
2,261 passed, ten failed and one was skipped. The failures were repaired and
rechecked; none was excluded from the current collection. Two additional
regressions cover full-scene package export and bone display-cache reuse.

The current **2,274-test inventory** was reconciled by exact test ID against the
complete sweep and subsequent repaired-case/changed-code JUnit results:
**2,273 passed, one platform skip, zero outstanding failures/errors**. This is
cumulative verification, not a claim that a second clean full-suite invocation
ran after every repair. The Windows skip requires permission to create symlinks.

Additional focused results include 36 bone drawing/interaction checks and 46
shared chrome, timeline, theme and workspace checks. Final splitter interaction
was also exercised in both themes: channel width changed from 260 to 295 pixels
by dragging; all splitter targets measured six pixels. Timeline keyboard resize
increased height by 32 pixels in both themes. These focused counts overlap the
inventory and must not be added to it.

Ruff lint passes; Ruff formatting passes for **752 files**; strict mypy passes
for **277 source files**. The source quality workflow covers push/PR checks on
Windows, Linux and macOS; remote CI was not run from this workspace.

Actual source release-smoke checks passed PNG rendering, save/reopen, plugin
enable/disable, CLI and official MCP stdio operation with 48 source assets.
Both documented asset-pipeline and extended-authoring examples completed using
real services, including atlas/runtime export, retargeting, dynamics baking,
face authoring, package sharing and guided rigging. Native Godot contract checks
passed on this host; this does not validate every engine/platform combination.

Ignored local evidence is retained in `build/`: the complete gate's four JUnit
files, `improvements-verified-inventory.json` (each current ID and its result
source), focused JUnit/logs, source smoke reports and performance JSON. Completed
test workspaces and disposable example projects may be removed after validation;
the reports, selected screenshots and shared warm test catalog are retained.

## Serial performance measurements

These are diagnostic timings on this host, with no other validation workload
running. They are not portable timing guarantees. Workspace rows use 31 samples
after preparation/warm-up; changing-frame measurements include evaluation and
completed painting. The character comparison keeps bone overlays enabled.

| Workload | Comparison | Result |
| --- | ---: | ---: |
| Cold-generation Qt heartbeat, median | Thread 18.005 ms | Process 5.026 ms |
| Cold-generation Qt heartbeat, p95 / maximum | Thread 19.956 / 86.278 ms | Process 6.449 / 7.641 ms |
| Timeline refresh, 64 channels / 128 keys, median | Forced rebuild 8.996 ms | Incremental 5.082 ms |
| Three characters, pan and paint, median / maximum | 43.797 / 45.028 ms | 6.455 / 7.170 ms |
| Three characters, changed-frame paint, median / maximum | 46.451 / 50.365 ms | 9.244 / 11.298 ms |
| Three characters, retained paint, median / maximum | 42.241 / 44.496 ms | 4.559 / 5.203 ms |
| Three characters, FK drag and paint, median / maximum | 58.547 / 63.281 ms | 21.716 / 25.613 ms |
| Source scene, changed-frame paint, median / maximum | Final source | 3.374 / 3.954 ms |
| Dense mesh, 6,626 triangles, edit-mode pan, median / maximum | Final source | 1.583 / 2.080 ms |

Cold-generation comparisons used two separate fresh-cache ten-second samples;
both cancelled without an error or abandoned staging. The three-character
workload contains 60 bones and 286 triangles. Its cold artwork paint still costs
25.097 ms median, and move/paint reached 41.206 ms maximum. Dense changed-frame
paint reached 21.909 ms maximum despite a 4.271 ms median. These tails and FK
drag costs remain above a 16.67 ms frame budget.

Actual Creator action switches measured 5.29–6.72 ms; evaluation measured
1.87–2.08 ms and painting 10.23–10.86 ms in the focused run. Character preparation
took 2.17 seconds, including binding, with a 124.94 ms worst heartbeat gap.
Export-inclusion filtering took 207–253 ms to finish asynchronously while
retaining the same preview and image cache. Preparation is not stall-free.

## Review scores and remaining limits

**Overall engineering readiness: approximately 7.3/10**, using the original
review's weighted criteria:

| Criterion | Weight | Score | Evidence and limit |
| --- | ---: | ---: | --- |
| Responsiveness | 30% | 7.5 | Measured preparation, timeline and overlay improvements; large/cold/FK latency tails remain |
| Correctness/data safety | 20% | 8 | Current inventory and roundtrip/Undo checks pass; not exhaustive field validation |
| Architecture | 15% | 7 | Qt-free services and narrower MVVM boundary retained; large coupled UI modules remain |
| Regression/release gates | 15% | 8 | Complete sweep plus reconciled repairs and source CI; remote matrix not executed |
| Workflow/accessibility | 10% | 7.5 | Numeric/keyboard graph controls and visual Creator improvements; native assistive/DPI QA pending |
| Distribution/interchange | 10% | 4 | Color bounds and adapter contracts documented; native release prerequisites remain |

**Separator/UI pass: 8.5/10**, with equal criteria: divider thinness 9,
dark/light contrast 8, shared visual consistency 8.5, preserved resize/float
interaction 8.5. Dark/light main-window, floating Assets, About dialog and
direct-vector/cached-bone comparisons were inspected offscreen. This does not
replace native multi-monitor, 125–200% DPI or screen-reader verification.

Before production release, source licensing/provenance decisions, signing,
actual native Unreal runtime/audio, non-Windows native QA and remote CI still
need evidence. No credentials, license choice, engine certification, HDR/OCIO
pipeline or universal 60 fps performance is implied by this increment.
