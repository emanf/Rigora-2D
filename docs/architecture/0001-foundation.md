# ADR 0001: Foundation and dependency boundaries

Status: Accepted for Prompt 1. Date: 2026-10-17.

## Context

Rigora needs one desktop application and a future shared animation/service core
that can also be used offline from Python, CLI, and MCP. The first milestone must
provide a working, testable foundation without pretending later features exist.

## Decisions

- Python 3.12 is the development baseline. `src/rigora` keeps imports tied to an
  installed package rather than accidentally importing the working directory.
- PySide6 is the optional `gui` extra. No Qt dependency belongs to the core
  installation. Only the desktop composition function imports presentation.
- The desktop uses MVVM from the first window: a QObject ViewModel owns displayed
  application state, and a QMainWindow displays its read-only properties. Future
  mutable UI state will use notifying Qt properties/signals and commands.
- `app/bootstrap.py` is the composition root. `ApplicationRuntime` explicitly owns
  its configuration, metadata, logger, and shutdown. No application, handler,
  database, directory, or GUI is created during import.
- The initial CLI uses standard-library argparse. It needs only startup options,
  version, help, and diagnostics. A larger command framework can be evaluated when
  Prompt 10 introduces actual application services and commands.
- Frozen dataclasses represent the small configuration/metadata value objects.
  Validated project-domain serialization remains a Prompt 3 decision; there is no
  mixed domain-model strategy in this milestone.
- JSON logs go to stderr; diagnostic JSON results go to stdout. Each runtime uses
  a standalone logger and removes only its own handlers, preserving host logging.
- Hatchling builds wheels/source distributions. uv provides editable development
  setup and a committed transitive lock; direct dependencies and the build backend
  are pinned in configuration. pytest/pytest-qt, Ruff, and strict mypy are the
  validation tools.

Dependency compatibility was checked against the primary package metadata for
[PySide6](https://pypi.org/project/PySide6/),
[pytest](https://pypi.org/project/pytest/),
[pytest-qt](https://pypi.org/project/pytest-qt/),
[Ruff](https://pypi.org/project/ruff/), [mypy](https://pypi.org/project/mypy/), and
[Hatchling](https://pypi.org/project/hatchling/). Resolution and actual installed
versions are recorded in `uv.lock`; see the validation record for the tested host.

## Layout and dependency direction

```text
src/rigora/
  app/                 composition, configuration, runtime lifecycle
  infrastructure/      structured logging adapter
  interfaces/cli/      console argument parsing and output
  presentation/
    viewmodels/        Qt presentation state; no widget imports
    views/             desktop widgets
tests/                 core and isolated GUI checks
docs/                  decisions, development, limitations, validation
```

The CLI invokes the composition root, which constructs the runtime and, only for
desktop mode, the Qt presentation. Views depend on ViewModels. Shared metadata
and configuration are plain Python values. The logging adapter consumes the
configuration value without importing runtime composition.

Future domain, engine, application services, storage, plugin, and automation
modules will be added when they have real behavior. Domain and engine code must
remain Qt-free; GUI, CLI, Python API, and MCP will call the same service layer.
No empty future modules are created just to reproduce the brief's sample tree.

## Consequences

Headless installation and execution require no Qt or display server. Desktop
bootstrap deliberately owns one QApplication/event loop and rejects an existing
QApplication rather than hijacking another application's loop. Embedded desktop
hosting is not currently supported. Tests use subprocesses for full startup and
pytest-qt for widget checks. No persistent settings, user project schema, global
service locator, or speculative plugin API is introduced.

