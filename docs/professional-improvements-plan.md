# Professional workflow consolidation

Scope authorized on 2026-11-05: implement the findings in
`professional-readiness-review-2026-11-05.md`, preserving source-only development,
offscreen verification, the Qt-free engine and current character artwork.

Implementation order and acceptance:

1. Regression gate: migrate retired content fixtures to current equivalents;
   collect/run all maintained tests; repair UTF-8/formatting; add source CI.
2. Preparation: measure cold catalog generation and event-loop stalls, isolate
   the measured blocking work, retain progress/cancellation, and make benchmarks
   reject incomplete preparation.
3. Resource retention: configurable bounded Undo and safe generated-cache pruning;
   preserve current/in-use data and user packs.
4. Editor updates: narrow timeline invalidation and move asset-placement commands
   behind a ViewModel; verify unchanged selection, scrolling and Undo.
5. Character attachments: persist per-view local hand reflection, expose both
   hands visually in CC, retain all currently approved orientations by default.
6. Graph editing: keyboard point selection/nudging and numerical accessible
   controls; retain endpoint/time-order constraints and one-step Undo.
7. Output: explicit sRGB/EXIF normalization and alpha/color roundtrips; surface
   verified target capabilities and document native validation requirements.
8. Final gate: source checks, representative offscreen workflows, measured frame
   times, review score with criteria, and cleanup of disposable test artifacts.

External release prerequisites: source-license/provenance decisions, signing
credentials, actual native Unreal and non-Windows runtime verification. Do not
claim these complete without their evidence; do not select an artwork license or
produce an executable bundle as a substitute.

Completed on 2026-11-06:

- Source CI, UTF-8 and format repairs pass. The complete sweep and repaired-case
  rechecks cover every current test ID. Remote CI has not run from this
  workspace, which has no Git metadata.
- Cold generation uses a cancellable spawned process. Final serial Qt heartbeat
  measurements improved from 18.01 ms median / 86.28 ms maximum in the thread
  comparison to 5.03 / 7.64 ms in the process case, with clean cancellation.
- History retention and explicit generated-cache maintenance pass isolated
  retention/Undo tests. Cleanup has not been run against the owner's cache.
- Timeline structure descriptors retain rows on value-only edits; the final
  64-channel comparison measured 9.00 ms median with forced rebuilding versus
  5.08 ms incrementally. Selection, expansion and key updates pass rechecks.
  Asset placement orchestration now lives behind a ViewModel command.
- Per-view wrist-local hand mirrors, original-vector contact sheets and native
  graph point controls have focused coverage. Existing approved glove defaults
  are retained. Plugin recipe providers are reconnected to the new Creator grid.
- Tagged raster color/orientation correction passes pixel, alpha, original-byte,
  save/reopen and atomic-rejection checks. Export choices now expose important
  engine adapter limitations. Native engine/platform prerequisites remain open.
- Regression work also repaired unsupported-clip audio retries, retired default
  automation/example identities, unnecessary Creator preview reconstruction
  when changing exported actions, and recipe loop-period FPS conversion.

The complete sweep executed 2,272 cases; all ten reported failures were repaired
and passed targeted rechecks. Added regression
coverage verifies large scene-package export and source-derived bone-overlay
cache reuse. Ruff, formatting and strict mypy pass. The final validation records
the full sweep separately from subsequent repairs and measurements; no failed
case was excluded to obtain a passing result.

Serial measurements confirmed 5.03 ms median cold-generation heartbeat gaps
(18.01 ms in the thread comparison), 5.08 ms incremental timeline refresh
(9.00 ms forced rebuilding), and 9.24 ms three-character changed-frame painting.
Profiling also exposed repeated bone-outline rendering: a bounded display-only
cache reduced median pan-and-paint from 43.80 to 6.46 ms, preserving source
silhouettes and leaving vector artwork/deformation unchanged. Representative FK
drag still exceeds a 16.67 ms budget; full results and release limits belong to
the final validation, not a universal responsiveness claim.

The subsequent separator pass is also complete: shared subtle neutral dividers,
transparent dock gutters and one thin Timeline top edge, preserving generous
resize targets and floating-window outlines. Forty-six existing GUI checks pass;
final dark/light pointer and keyboard checks confirm actual resizing.

See [final validation and scored review](validation-professional-improvements.md)
for exact test accounting, performance evidence and remaining release limits.
