# Development guide

Follow README setup commands before running checks. uv installs `rigora` editable:
changes under `src/rigora` are visible without rebuilding. After packaging metadata
changes, refresh the lock with `uv lock` as needed, then run
`uv sync --locked --extra gui`. Version reporting comes
from `src/rigora/__init__.py` and Hatchling uses that same version for distributions.

On Windows, `Run_Rigora.bat` starts the local environment's installed application,
and `Test_Rigora.bat` runs the full validation sequence. They anchor all paths to
their own directory, including project paths containing spaces. The launcher
passes application arguments through unchanged after an optional first
`--no-pause`; the test runner accepts only that flag. Without the flag, the
launcher pauses on errors, and the test runner pauses after any result for
double-click use. `RIGORA_NO_PAUSE=1` disables pauses in both. No script downloads
or installs dependencies; missing environments/tools produce setup instructions.
The separate [desktop build scripts](desktop-builds.md) do install their required
tools into an isolated build environment.
Use `call` when invoking a batch file from another batch file so control returns.

Configuration is resolved at startup. `load_config()` accepts an environment
mapping for deterministic tests; no settings are read at import time. Empty or
invalid log levels produce a usage error. The CLI exits with 0 for success, 1 for
missing GUI dependencies or project-evaluation errors, 2 for invalid
arguments/configuration, or 130 for a
handled desktop KeyboardInterrupt. Qt initialization and unexpected failures retain
their diagnostic errors rather than being reported as successful startup.

`ApplicationRuntime` supports context management. `start()` and `shutdown()` are
idempotent. An exception inside the context logs a failure and still releases
owned handlers. Caller-owned streams and root logging handlers remain open.

The headless command supports diagnostics and `--evaluate PATH --frame NUMBER`.
The latter calls `DocumentService.animation.evaluate()`, exactly as desktop
playback uses `AnimationSession`. Domain/engine/services remain Qt-free. Do not
add a second domain model or implement project mutation in a widget/CLI callback.

The Qt-free `DocumentService` is the shared lifecycle and mutation entry point.
Use `execute()` with immutable deltas and `transaction()` for compound changes.
`WorkspaceService` owns independent sessions and tab selection. See `project-format.md` and ADR 0002. `RIGORA_PREFERENCES_PATH` selects an
explicit workspace preferences file; tests use it to isolate settings. Canonical
media live in root `assets/` and are included in installed wheels.
See [workspace layout](workspace-layout.md) for the default arrangement, in-preview
Tools strip and saved panel/channel placement.

`engine/` compiles a scene hierarchy and key indices once, then evaluates a fresh
immutable pose at any absolute frame. `AnimationSession` owns transient playback.
The Qt ViewModel supplies monotonic elapsed seconds; engine tests supply explicit
time. See [ADR 0003](architecture/0003-animation-engine.md) and the
[evaluation contract](animation-engine.md). Run
`python tools/benchmark_animation.py --bones 1000 --tracks 1000 --keys 100`
to measure compilation and random-access evaluation separately from fixture
construction. Counts and `--curve linear|bezier` are configurable; no timing
assertions depend on machine speed.

For a repeatable offline check after dependencies are installed:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
uv run --offline --locked --extra gui pytest
uv run --offline --locked --extra gui ruff check .
uv run --offline --locked --extra gui ruff format --check .
uv run --offline --locked --extra gui mypy
```

Build artifacts with `uv build`; wheels and source archives appear in `dist/`.
The [release process](release.md) adds distribution/source audits, a hash manifest,
installed-package smoke checks and workload profiling. This is Python package
distribution. The [native desktop builder](desktop-builds.md) additionally creates
an executable/application bundle for the host OS, without creating an installer.

The owner's current preference is a single agent, as recorded in root `AGENTS.md`,
to reduce token usage. Implement, review, and test in the current chat; use
subagents only when explicitly requested. Update documentation and report what
passed and what remains. Preserve milestone scope until the next requested task.

Extension API 2 development uses the existing environment and no new dependencies.
Run `python -m rigora.sdk init DIRECTORY --id org.author.plugin --kind tool` for
an independently packaged example. Source loading, manifests, callback contracts,
safe mode and subprocess jobs are documented in [plugin-sdk.md](plugin-sdk.md).
Three original working projects are in `examples/plugins/`. See
[validation-prompt9.md](validation-prompt9.md) for installed-package acceptance.

Prompt 10 adds `rigora.api.RigoraAPI`, `rigora-automation`, and the optional official
MCP SDK extra. Use `uv sync --locked --extra gui --extra mcp` to include MCP protocol
tests; core and GUI-only installs skip them. The API and SVG renderer remain Qt-free.
See [automation.md](automation.md) for local examples and explicit server deployment.

Prompt 11 adds optional `render` and `psd` extras. For the full media/output gate,
use `uv sync --locked --extra gui --extra mcp --extra render --extra psd` before
`Test_Rigora.bat --no-pause`. Media tests skip without their codecs. See
[asset-pipeline.md](asset-pipeline.md) for imports, rendering and cancellation.
The optional encoder test uses `ffmpeg` on PATH; application exports require
explicit host configuration and never locate/download an encoder automatically.

On restricted Windows execution hosts, a sandbox token may be unable to access
Python's private temporary-directory ACLs. This host required running pytest
outside that sandbox with `--basetemp build/pytest-tmp`. This is an execution-host
permission issue; normal user-run tests do not require administrator privileges.
Pytest's cache is kept under the ignored `build/` directory.

Document source APIs with purpose-focused class and function docstrings. Explain
validation, ownership and side effects; inline comments clarify design constraints
without narrating requests or edit history. Structural schemas are generated with
`python tools/export_schema.py`; `examples/create_authoring_example.py` creates a
portable data-contract sample. Include `tools/` in source distributions.

Prompt 6 uses `MeshService`, `SkinService`, `DeformationService` and
`DeformationMotionService` for image/geometry authoring. See
[`deformation.md`](deformation.md) and ADR 0005 for ownership/evaluation contracts.
Generate original editable studies with
`python examples/create_deformation_examples.py` (defaults to `build/examples/`).
Run `python tools/benchmark_deformation.py` for a Qt-free 1,089-vertex / 64-control
FFD measurement. Sources in `assets/examples/` are included in installed wheels.

Run `python tools/benchmark_workspace.py` with the GUI extra for offscreen measurements
of hand panning, selection/mesh overlays, changing bone poses, cold/cached artwork painting,
maximum-density wireframes and switching three populated project tabs. `--case ten-characters`
is an in-memory engine stress case; its metadata exceeds the current package metadata cap.
The benchmark uses isolated documents and preferences and leaves open user projects alone.
Results and the current CPU-rendering limits are documented in
[workspace performance validation](validation-workspace-performance.md).

For a warm benchmark, pass `--catalog-cache PATH` to a completed content cache
root. The benchmark rejects unfinished content discovery instead of silently
mixing preparation stalls into warm editor timings. Character fixtures use the
current Creator and spring sources. `tools/benchmark_preparation.py` compares
Qt heartbeat gaps during real cold generation in a thread and in a spawned
process, with cooperative cancellation and staging cleanup.

The independent Source quality workflow checks pushes and pull requests on
Windows, Linux and macOS without creating executable bundles. It runs locked
source dependencies, Ruff, mypy and offscreen tests and retains JUnit output.
Native release builds remain separately triggered. Remote matrix execution and
native engine validation must be verified before a release claim.

See [catalog fixture migration](test-catalog-migration.md) for retired test data
and replacement coverage, and [raster color policy](color-management.md) for
the precise bounds of import color/orientation handling.
