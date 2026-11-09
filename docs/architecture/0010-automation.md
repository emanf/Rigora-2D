# ADR 0010: Task automation over existing application services

Status: Accepted for Prompt 10. Date: 2026-10-18.

## Decision

`rigora.api.RigoraAPI` owns an authorized `DocumentService` session and delegates
to the same content, scene, rig, mesh, skin and animation services as the editor.
`execute` validates operation signatures and JSON types, serializes access, checks
optional authored-state revisions and returns structured results. It introduces
no second project model or evaluation engine.

CLI, stdio MCP and explicitly enabled HTTP MCP are adapters. The optional official
MCP SDK generates schemas from concrete service signatures; strict scalar annotations
prevent approval coercion. The standard-library CLI retains JSON output and a
bounded, data-only workflow format. Python and CLI need no Qt or MCP installation.

Resolved input/output boundaries are owned by the session, not by individual
clients. MCP existing-file overwrites require host permission plus per-write
approval. HTTP also requires bearer authentication and explicit host/origin
allowlists. No shell/eval operations or automatic plugin activation are exposed.

The Qt-free SVG renderer uses canonical evaluated mesh positions, UVs, object
matrices and original image bytes. Shared affine regions use union clips to avoid
internal triangle seams; opacity applies to the mesh group. SVG remains vector
artwork. Dimensions, triangle count, source bytes, frame count and output bytes
have explicit bounds. Video/codec and raster production exporters remain Prompt 11.

## Ownership and failure semantics

Ordinary edits retain `DocumentService` command history. `transaction()` uses its
existing nested command groups for rollback and one-step undo. Lifecycle commands
cannot run inside authoring transactions. File rendering/export are independent
effects and should follow successful authoring transactions. Each file publishes
atomically; a sequence is not a filesystem transaction.

Single-operation dry runs fork the document and embedded asset map. Batch dry runs
carry one fork across dependent tasks, never publishing files. Preview/export from
the GUI forks on the GUI thread before background execution. An MCP process owns
a separate document from an open desktop process. Multiple authenticated clients
share that process's serialized session; use separate processes for independent
workspaces and revisions for competing edits.

The [automation guide](../automation.md) defines public commands, schemas through
typed methods, examples, approval rules, offline behavior and server deployment.
