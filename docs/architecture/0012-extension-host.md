# ADR 0012: Declarative extension host and shared command boundary

Status: Accepted. Date: 2026-10-27.

## Problem

The original plugin adapter concentrated commands in a single menu/toolbar and
rebuilt every panel when any registration changed. Command adaptation lived in
the main window ViewModel, character recipes were fixed creator choices, and
there were no named editor surfaces or normal lifecycle notifications.

## Decision

Use one versioned declarative registry with API 1 compatibility. Registrations
describe action locations, named widget surfaces, hooks, creator recipes and
portable content packs. Dynamic registrations and removals update the same
registry as startup registration. Generic engine contributions retain the
existing canonical records/evaluator.

`PluginCommandService` owns Qt-free permission-scoped dispatch and undo grouping.
`PluginRequest.service` constructs existing application services for the current
document. `ExtensionViewModel` translates application/selection state into
immutable request snapshots and notifications. `DesktopExtensionHost` and
`PluginWorkspace` mount owned Qt controls and diff registrations by identity.
The optional `PluginHost` protocol supports desktop navigation without requiring
domain/engine code or headless jobs to import Qt.

Views publish stable layout/toolbar IDs. A view's destruction withdraws its
surfaces. Widgets can publish further surfaces, so integrations do not need a
growing collection of hardcoded plugin-specific window branches. Actions share
one command identity across placements. Unchanged docks retain their instances.
Code outside Qt ownership uses explicit plugin shutdown callbacks.

The installer inspects bounded portable ZIP files on a worker and publishes a
complete package without executing code, granting trust or overwriting files.
Discovery retains unchanged contexts, unloads changed origins and their active
dependents, and requires renewed code trust. Expected validation errors remain
recoverable; unexpected callback failures are quarantined.

## Scope and consequences

Preserve the existing workspace, file format, domain records and animation
engine. This is an extension-boundary refactor, not a second application model.
Creator recipe providers reuse current component renderers; custom geometry,
characters, poses and motions use packs, and new creation workflows can publish
widgets/commands. Built-in categories remain default seeds; new library category
names are data rather than an application-code enumeration.

Hooks are notifications, not interceptors for every low-level function. Trusted
Python can access process resources; this API does not claim OS sandboxing or
native DLL plugin ABI support. Heavy work must leave the GUI thread. Source and
native bundle behavior require tests through the same public contracts.
