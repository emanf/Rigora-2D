# Development and repository maintenance

Rigora uses Python and PySide6 with MVVM. Domain/engine code stays Qt-free;
presentation, command-line, Python and MCP clients use shared application
services. See the [foundation](architecture/0001-foundation.md) and
[extension-host architecture](architecture/0012-extension-host.md).

## Source layout

| Path | Ownership |
| --- | --- |
| `src/rigora/domain/` | Immutable authored records and validation |
| `src/rigora/engine/` | Evaluation, constraints, deformation and playback |
| `src/rigora/application_services/` | Authoring commands, transactions, imports, exports and plugins |
| `src/rigora/presentation/` | Qt views, ViewModels, widgets and editor coordination |
| `src/rigora/interfaces/` | CLI and MCP adapters |
| `src/rigora/sdk/` | Public extension contracts and scaffolding |
| `assets/` | Canonical vectors, fonts, icons, templates and notices |
| `plugins/` | Complete optional app-local plugin examples |
| `examples/` | Small workflows and developer plugin starters |
| `tests/` | Automated numerical, service and GUI checks |
| `tools/`, `packaging/` | Asset generation, benchmarks, build and release tools |
| `docs/` | User guides, API contracts, architecture and dated validation |
| `.github/workflows/` | Manually dispatched native release workflow |

## Set up and validate

```sh
uv sync --locked --extra gui
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync mypy
```

Run focused pytest files for a change. Set `QT_QPA_PLATFORM=offscreen` for GUI
tests so they cannot move the desktop pointer or take focus from another app.
Use temporary preferences rather than the normal user profile. Windows has
`Test_Rigora.bat --no-pause` for the combined source gate.

Document public modules, classes and functions with their purpose, inputs,
results and ownership. Keep comments about design constraints, not conversation
history. Use canonical services for edits, retain one Undo step per gesture,
and test failures that could corrupt data or break bindings. Read `AGENTS.md`
for the project-specific collaboration and visual contracts.

Compilation is a separate operation. Use `Run_Rigora.bat` or
`uv run --no-sync rigora` during development; compile only when a native bundle
is actually needed. [Desktop builds](desktop-builds.md) explains the scripts.

## Keep generated files out of Git

Do not commit `build/`, `dist/`, virtual environments, package caches, bytecode,
personal settings, imported working projects, credentials or private prompt/task
notes. `.gitignore` excludes the known generated directories. `uv.lock`, assets,
plugin sources, tests, documentation and `.github/` belong in the source snapshot.

`build/` contains test fixtures, render results, diagnostics and isolated compiler
environments. `dist/` contains distributable outputs. Both can be removed after
retaining any exports you personally need. `.venv-build/`, `.uv-cache/`,
`.npm-cache/`, `.mypy_cache/` and `.ruff_cache/` can also be regenerated.
Keep `.venv/` if you want the source launcher to keep working immediately.

Close tests/builds before removing their temporary directories. Verify the full
resolved path before a recursive delete. Do not replace this with a wildcard
delete of the repository. Removing a dependency cache is safe for existing
installed environments, but the next dependency installation may need a download.

The reference prompt directory and old task notes remain local and ignored;
they are not required to run or package Rigora. Do not remove canonical artwork
because a simple text search cannot find it: catalogs, content packs and plugins
also reference assets dynamically.

## Before uploading a source snapshot

1. Read the [provenance notes](provenance.md). No top-level source license has
   been selected; owner-supplied bone/reference artwork has separate terms.
   Preparing the repository does not grant redistribution rights.
2. Review `git status` and the files staged for the initial commit. Exclude
   local credentials, working animations, output archives and private notes.
3. Run the source checks relevant to your changes. Keep generated evidence in
   `build/`; retain a concise validation summary in documentation when useful.
4. Keep `uv.lock` synchronized with `pyproject.toml`. Removing an optional codec
   solely because it is not installed locally would remove a supported feature.
5. Follow [GitHub releases](github-releases.md) to upload the repository and run
   the release workflow. No workflow runs merely because a local file exists.

Native bundles must retain their full runtime, license notices, assets and
plugins. Public release testing, signing and notarization are separate from
repository housekeeping.
