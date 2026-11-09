# Rigora professional-readiness review

Reviewed 2026-11-05, from the current source workspace. This was an assessment;
application code, dependencies, saved projects and executable bundles were not changed.
There is no Git checkout metadata in this workspace to identify a reviewed commit.

**Provisional production-readiness score: 6/10.** Criteria: responsiveness (30%),
correctness/data safety (20%), architecture (15%), regression/release gates (15%),
workflow/accessibility (10%), distribution/interchange (10%). This is an engineering
assessment, not certification or a complete audit of every advertised feature.

| Criterion | Score | Basis |
| --- | --- | --- |
| Responsiveness | 7/10 | Healthy small warm-workspace measurements; large fresh-cache spikes and incomplete representative coverage |
| Correctness/data safety | 7/10 | Immutable records, command transactions, save conflict handling, and passing focused core checks; full suite unavailable |
| Architecture | 7/10 | Qt-free core and shared services; UI orchestration and invalidation remain heavily coupled |
| Regression/release gates | 3/10 | Full pytest collection and documented format gate fail; no automatic PR workflow in this snapshot |
| Workflow/accessibility | 6/10 | Current cards and shared chrome are coherent; custom graph keyboard and accessible point interaction are incomplete |
| Distribution/interchange | 4/10 | Packaging/export infrastructure exists; licensing decisions and native platform/engine validation remain open |

**What already works as a sound foundation**

The source contains 272 Python modules and approximately 84,895 lines, plus 232
Python test modules. The important foundation is present: a canonical project model,
stable IDs, immutable revisions, reversible service commands, a shared evaluator,
background project I/O with revision-aware save completion, recovery checkpoints,
and versioned extension contracts. The current dependency-boundary regression passes.

Current main-workspace and Character Creation windows were opened and inspected
offscreen. Creator prepared successfully without changing the scene. The shared
neutral styling, square cards and distinct default/include states are worth retaining.
Screenshots are local review artifacts under `build/professional-audit-ui/`.

**1. High priority: restore a trustworthy full test gate**

The complete `pytest -q` invocation stopped during collection with eight errors:

- `test_animal_anatomy.py`: removed `vector_creation.armature` import.
- `test_bundled_asset_compatibility.py`: missing `assets/library/starter.rigpack`.
- `test_creator_game_cast.py`, `test_creator_hair.py`,
  `test_creator_mustaches.py`, `test_creator_open_hand.py`, and
  `test_human_controls.py`: removed `infrastructure.character_art` imports.
- `test_vector_creator_gui.py`: removed `vector_catalog.ENVIRONMENT` import.

A separate core subset stopped with **92 passed, one failed**: the plugin example
test at `tests/test_plugins.py:50` still expects one bone after an operation that
now creates a protected Rig Root plus the drawn bone. That assertion is stale
relative to the adopted root model; it is not evidence that the extra root is wrong.

A later explicit current-contract subset passed **182 tests**, covering release
reliability/dependency direction, rig roots, binding, multiple scenes and supplied
hands. These passes do not make the complete suite green. A broader GUI-inclusive
attempt was interrupted after repeated fixture setup errors and is not counted
as completed verification.

Remedy: migrate still-relevant behavior tests to the current catalog and root
contracts; retire only tests for intentionally removed features. Do not recreate
obsolete assets or skip failures merely to get green. Exit criterion: the documented
full test command collects and finishes successfully from a clean setup.

**2. High priority: make quality checks automatic and repair their current failures**

`ruff check .` and strict mypy pass. `ruff format --check .` does not:
`docs/extensions.md`, `docs/plugin-sdk.md` and `docs/video-to-rig.md` have unformatted
Python examples, and `docs/creative-templates.md` is not valid UTF-8 (first invalid
byte at offset 2585). `Test_Rigora.bat` includes that exact format check.

The only checked-in workflow is `.github/workflows/release.yml`. It is manual-only;
its application verification input defaults to false. Compile-only local builds
are the owner's intentional workflow and can stay separate from testing.

Remedy: fix the gate, then add a separate push/PR workflow for source checks,
offscreen smoke tests and selected deterministic/work-count performance checks.
Keep native packaging independently triggered. GitHub supports these separate
[workflow events](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows).
No branch protection or remote workflow execution was inspected.

**3. High priority: target first-run content preparation before replacing the renderer**

Two fresh-cache `sources` workspace runs showed roughly 306–310 ms worst samples
in paint/drag paths. The first run overlapped other checks; the second did not.
The benchmark waits at most 30 seconds for discovery, then can proceed while
content is still busy when source images are already decoded. Consequently these
are fresh-cache/preparation measurements, not steady-state viewport timings.

A separate run injected the already-complete local template catalog, avoiding
regeneration and testing the warm workspace. It measured 31 samples of a
three-object, 12-bone, 864-triangle scene:

| Operation | Median | Maximum |
| --- | --- | --- |
| Pan and repaint | 5.54 ms | 5.76 ms |
| Changed-frame paint | 6.05 ms | 6.24 ms |
| Bone preview move and repaint | 7.86 ms | 8.47 ms |
| FK preview rotation and repaint | 7.87 ms | 10.35 ms |
| Document UI refresh | 1.45 ms | 1.62 ms |

The serial Qt-free stress benchmark used 1,000 bones, 1,000 tracks, 100,000 Bezier
keys and 61 random/backward seeks: **7.77 ms median, 8.56 ms p95**, excluding
painting, with **210.54 ms** evaluator construction. These are single-host
diagnostics, not a universal frame-rate guarantee or an optimization comparison.

Remedy: profile content generation and GUI heartbeat together, including native
SVG rendering/GIL behavior, before choosing chunking or a process worker. Keep
progress and cancellation. Distinguish cold preparation from warm editor benchmarks;
fail or label incomplete readiness rather than silently mixing both workloads.
Add current CC, multi-character, dense FFD, cold seek and large-library workloads.
Start with a provisional 16.7 ms total interactive-frame target and track p95/p99
and long stalls separately. Qt recommends separating expensive work from the GUI
thread, but threading alone is not proof of responsiveness:
[Qt thread guidance](https://doc.qt.io/qt-6/threads-qobject.html).

**4. Medium priority: make model invalidation narrower**

`presentation/widgets/timeline.py:538` uses scene identity in its rebuild key;
the rebuild clears the complete tree at line 595. Immutable edits produce new
scene identities even when track structure is unchanged. Scene tree reconstruction
also clears and repopulates items (`presentation/scene_workspace.py:124`).
State restoration already exists, but rebuilding and restoring is additional work.

Remedy: distinguish structural, value, selection, appearance and transport changes.
Update existing rows by stable ID; rebuild only when structure changes. A
`QAbstractItemModel` with delegates is a reasonable direction for growing trees,
not a requirement to replace every small `QTreeWidget`. Compare refresh time and
allocation counts on realistic projects before and after the change.
[Qt model/view guidance](https://doc.qt.io/qt-6/model-view-programming.html).

**5. Medium priority: finish the project's own MVVM boundary**

`presentation/views/main_window.py` has 3,392 lines; timeline has 1,824 and composer
editors 1,774. Size is an inspection signal, not by itself a correctness defect.
More concretely, `MainWindow.place_asset()` constructs and calls application services
directly, and `content_applied()` resolves domain ownership and changes editor
state across several subsystems. UI behavior therefore bypasses a consistent
ViewModel command boundary in some workflows.

Remedy: move asset-placement and editor-context transitions into focused ViewModel
commands while keeping services canonical. Views should bind controls and render
state. Refactor one tested workflow at a time; a wholesale rewrite is unnecessary.
This is drift from Rigora's explicit MVVM requirement, not a claim that Qt mandates MVVM.

**6. Medium priority: bound long-session memory and disposable disk caches**

`application_services/commands.py:164` retains unbounded undo/redo lists. Some
commands preserve immutable project revisions; sharing reduces duplication but
does not bound retained memory. No exhausting-memory incident was reproduced.

The local generated content cache currently holds **12 revisions / 67.08 MiB**;
the current revision uses **11.47 MiB**. `illustration_cache.py` replaces the same
version and cleans failed staging, but does not retire older version directories.

Remedy: add configurable history retention with a clear policy, memory reporting,
and safe pruning of generated caches that are no longer in use. Preserve imported
user packs, sources and current references. No owner cache was deleted in this review.
Qt's [Undo framework](https://doc.qt.io/qt-6/qundostack.html) is a reference for
limits/macros; Rigora can retain its Qt-free command implementation.

**7. Medium priority: provide keyboard and assistive access to custom editing widgets**

An offscreen probe of `CurveCanvas` selected the middle of three graph points.
Right Arrow did not move it. Its accessible interface exposed zero children, so
the individual graph points were not represented as accessible controls.
`accessibleName` on the overall canvas is useful but insufficient for those edits.

Remedy: add keyboard selection/nudging of points, numerical equivalents for precise
editing, announced point values and accessible point actions. Test actual Windows
screen-reader use separately; offscreen inspection is not full assistive QA.
This is a concrete gap against [Qt accessibility guidance](https://doc.qt.io/qt-6/accessible.html).

The main toolbar is also visually dense at 1,440 px. Consider contextual transform
fields with explicit labels, and verify 1,280 px layouts and 125–200% DPI scaling.
CC has an 1,100 x 700 minimum: smaller available work areas need explicit testing.
These layout recommendations are visual judgments/risks, not reproduced native-DPI failures.

**8. Medium priority: make character attachment orientation editable data**

Hand source selection/reflection is currently encoded as gesture/view conditionals
inside `infrastructure/illustration.py:273`. The existing result follows the owner's
approved source rules and tests; the concern is future authoring and extensibility.

Remedy: preserve the supplied vectors, wrist anchors and current results, then
represent source partner and local mirror transform in per-view attachment data.
Offer visual left/right mirror controls and a small multi-view contact sheet in CC.
This reduces the need for code changes for each new gesture correction. It is a
workflow recommendation, not a universal standard for hand orientation.

**9. Before a production release: close the documented integration boundaries**

`docs/limitations.md` explicitly records absent production color management,
unverified Unreal native compilation/runtime/audio, cross-platform native QA,
and unresolved distribution decisions. The README remains honest about development
status; those limits should also be evident where users choose an output target.

Remedy: first establish an explicit sRGB import/preview/export policy, normalize
image orientation, and use visual roundtrip fixtures for alpha, colors and camera
output. Full film-oriented OCIO support is an optional later scope decision;
[QColorSpace](https://doc.qt.io/qt-6/qcolorspace.html) already provides ICC and
color-space conversion foundations. Verify native engine adapters in the actual
engines before advertising production support for them. Decide the source license,
asset redistribution provenance and signing/distribution policy before public release.

**What does not need replacing just to look professional**

The Qt-free engine, custom command history, explicit Rig Root, trusted Python
plugins and shared custom title bars are legitimate design choices. In-process
plugins need clear trust boundaries and diagnostics; they are not automatically a
bad extension architecture. Root/rest-pose behavior should remain explicit and
tested rather than be redesigned from a feature comparison. A GPU renderer is a
candidate only after measured workloads show that painting is the limiting stage.

**Recommended order**

1. Restore full pytest collection and the format gate; add automatic source CI.
2. Profile fresh-cache preparation, repair benchmark readiness, then address the
   measured stalls. Add history/cache budgets and realistic performance fixtures.
3. Narrow UI invalidation and move the busiest orchestration into ViewModels.
4. Add attachment orientation controls, graph keyboard/accessibility and DPI QA.
5. Validate color/output roundtrips and native engine/platform distributions.

The next increment should be consolidation and predictable editing, with measured
acceptance criteria, rather than another large batch of unrelated features.
