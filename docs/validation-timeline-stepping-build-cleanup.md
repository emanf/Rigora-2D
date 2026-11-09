# Timeline stepping and rebuild cleanup validation

Validated on Windows on 2026-11-02 using the source environment. GUI checks ran
offscreen. No executable rebuild or cleanup of existing desktop bundles was run.

Clicking the timeline ruler gives it keyboard focus. Left and Right step one frame
through the shared playback model in Scene and Object Editor. Holding either key
repeats, playback stops, and stepping stays inside the playback range. Text fields
retain caret movement; modified arrow keys do not trigger frame stepping. Moving
the playhead does not edit the document or add undo entries.

The shared desktop builder removes old `build/desktop` and `dist` output before
checking free space or installing build dependencies. Successful builds also
remove their disposable compilation directory. Cleanup validates all requested
paths before deletion and rejects symlinks, Windows junctions, and paths outside
the generated output directories. Source assets, projects, plugins, the local
development environment, and other build reports are preserved. Cleanup tests
use temporary directories rather than the owner's existing bundles.

Validation results:

- 45 tests passed across `test_selection_timeline_gui.py`,
  `test_timeline_redesign_gui.py`, `test_playback.py`, and `test_desktop_build.py`.
  Evidence: `build/ruler-arrow-cleanup-final.xml`.
- The cleanup suite independently passed all 10 tests, including a real Windows
  junction rejection. Evidence: `build/cleanup-build-policy-final.xml`.
- Ruff lint and formatting passed for all 504 Python files; mypy passed for all
  266 application modules.

Review score: **9/10**, based on keyboard focus and stepping correctness, playback
bounds, document isolation, cleanup ordering, and path safety. Native Linux/macOS
builds and an actual Windows rebuild were not exercised; the owner has reserved
rebuilding for explicit requests. Three existing Qt drag-event deprecation
warnings remain in the regression suite.
