# Prompt 1 implementation and validation

Date: 2026-10-17. Milestone: project foundation. Application version: 0.1.0.

## Delivered behavior

The installable `rigora` package launches a minimal MVVM desktop status window or
runs a Qt-free headless startup diagnostic. Configuration validates log levels;
structured JSON logs use stderr, while diagnostic JSON uses stdout. Runtime
lifecycle and logging ownership are explicit. Console scripts and package
execution report the same version. This milestone provides no animation tools.

See [ADR 0001](architecture/0001-foundation.md) for architecture decisions and
[limitations](limitations.md) for the exact feature boundary.

## Changed files

- Project configuration: `pyproject.toml`, `uv.lock`, `.python-version`, `.gitignore`.
- Metadata and module entry point: `src/rigora/__init__.py`, `__main__.py`, `py.typed`.
- Composition/configuration/lifecycle: `src/rigora/app/{__init__,bootstrap,application,config}.py`.
- Logging: `src/rigora/infrastructure/{__init__,logging}.py`.
- CLI: `src/rigora/interfaces/__init__.py` and `interfaces/cli/{__init__,main}.py`.
- Presentation: `src/rigora/presentation/__init__.py`,
  `presentation/viewmodels/{__init__,main_window}.py`, and
  `presentation/views/{__init__,main_window}.py`.
- Tests: `tests/test_cli.py`, `test_config.py`, `test_runtime.py`, `test_gui.py`.
- Documentation: `README.md`, `docs/architecture/0001-foundation.md`,
  `docs/development.md`, `docs/limitations.md`, and this validation record.

The original project brief and all sixteen prompt files were read and preserved.
No Git repository was initialized. Generated environments, caches, build scratch,
and distribution artifacts are ignored.

## Commands and results

The Windows development environment used uv 0.12.13, CPython 3.12.14, PySide6/Qt
6.12.0, pytest 9.1.1, pytest-qt 4.5.0, Ruff 0.17.1, mypy 1.20.2, and Hatchling 1.32.4.
The checked-in lock includes hashes and exact transitive versions. Direct pins
also appear in `pyproject.toml`.

Commands below were executed from the repository root; the installed uv executable
was invoked by its full path where it was not on PATH. `UV_CACHE_DIR` was set to
the local `.uv-cache` during setup/build.

| Command/check | Result |
| --- | --- |
| `uv lock` | Resolved 20 packages; exact direct pins then locked. |
| `uv sync --locked --extra gui` | Installed the editable package and GUI/development dependencies. |
| `python -m pytest --basetemp build/pytest-tmp` using `.venv` and `QT_QPA_PLATFORM=offscreen` | 20 tests passed. |
| `.venv/Scripts/ruff.exe check .` | Passed. |
| `.venv/Scripts/ruff.exe format --check .` | 24 files already formatted. |
| `.venv/Scripts/mypy.exe` | No issues in 16 source files. |
| `uv lock --check --offline` | Passed; resolved lock remains consistent. |
| `uv build --offline` | Wheel and source distribution built successfully. |
| Wheel/source archive inspection | No virtual environment, package cache, or build scratch included. |
| Separate no-Qt environment, installed wheel offline with no dependencies | Headless diagnostic, version, logging suppression, and missing-GUI advice passed. |
| Native Windows hidden-window image capture | Readable Segoe UI text and correct minimal status window verified visually. |

The independent review agent reran pytest, Ruff lint/format, and mypy successfully
and reported no remaining Prompt 1 code blockers. The coordinating agent performed
the independent no-Qt installed-wheel checks and native Windows visual inspection.

The suite covers blocked Qt imports in headless startup; no-display execution;
import side effects; metadata/entry points; CLI errors/version/help; configuration
precedence; lifecycle idempotency, error cleanup, log filtering, and root-logger
isolation; and real GUI event-loop startup/shutdown in a subprocess.

## Host-specific setup observations

The inherited proxy pointed to an unavailable local endpoint. Approved dependency
setup temporarily cleared proxy variables in that command process, without
changing user/system settings. The first metadata build preceded README creation
and was retried after completing metadata inputs. These setup failures were fixed.

Windows sandbox-token ACLs prevented pytest from reading its private temporary
directories. The full suite passed outside that sandbox; see the development
guide. Offscreen Qt on this Windows host exposes no installed fonts, so automated
offscreen tests verify behavior and native Windows rendering verifies text.
The package has not been validated on Linux/macOS or other Python minor versions.
