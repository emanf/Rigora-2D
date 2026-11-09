# Python, CLI and MCP automation

Prompt 10 exposes the editor's existing document, rig, mesh, skin, content and
animation services through `rigora.api.RigoraAPI`. Domain, engine, API and CLI
imports do not require Qt. No cloud account or network is used by local tasks.

## Install and discover

The base package includes Python automation and the CLI. MCP is an optional extra:

```powershell
uv sync --locked --extra gui --extra mcp
.venv\Scripts\rigora-automation.exe --help
.venv\Scripts\rigora-mcp.exe --help
```

After installation, local tasks work offline. `rigora automation ...` and
`rigora-headless automation ...` also dispatch to the same CLI. Module entry points
are `python -m rigora.interfaces.cli.automation` and
`python -m rigora.interfaces.mcp_server`.

In the editor, **AI / Automation → Automation & MCP…** inspects the active document
and prepares a local connection configuration. It does not start a server. An MCP
process owns its own document session; save the desktop project and call
`project_open` to work on that file. **File → Export SVG preview…** renders the
current evaluated frame in a background worker using an isolated document fork.

## Python session and transactions

The public `rigora.api` facade exposes `API_VERSION="1"` and the immutable
`OPERATIONS` catalog. `diagnostics` reports that API version separately from the
package version. See [python-api.md](python-api.md) for offline signature discovery.

```python
from pathlib import Path
from rigora.api import RigoraAPI, AutomationError

api = RigoraAPI(Path.cwd())  # Existing authorized workspace directory.
api.execute("project_create", {"name": "My character"})
actor = api.execute(
    "character_create",
    {
        "content": "Bolt · Stick robot",
        "x": 750,
        "y": 300,
    },
)
rig_id = actor.data["rig_ids"][0]
with api.transaction("Prepare walk"):
    api.execute("motion_apply", {"content": "Natural · Walk", "target_id": rig_id})
    api.execute("clip_create", {"name": "My walk", "duplicate": True})
api.execute("frame_render", {"path": "output/walk.svg", "frames": [0, 6, 12, 18]})
validation = api.execute("project_validate")
api.execute("project_save", {"path": "output/character.rigora"})
```

Use `execute(operation, arguments, dry_run=False, expected_revision=None)` as the
validated adapter entry point. The typed methods on `RigoraAPI` document each
operation's parameters. Results are `OperationResult` values with `operation`,
`data`, `warnings`, `dry_run`, `can_undo` and `revision`; `to_dict()` produces owned
JSON data. Entity UUIDs survive save/load; use returned IDs instead of guessing
names. Content entries also have namespaced IDs from `library_list`.

Pass `expected_revision` from a previous result to refuse an edit against changed
authored state. `AutomationError.code` is a stable machine code, with a concise
message for the user. Typical codes are `invalid_arguments`, `validation_error`,
`path_outside_root`, `approval_required`, `revision_conflict`, `unsaved_changes`
and `io_error`. Expected validation failures do not expose Python tracebacks.

`transaction()` groups in-memory edits into one Undo item and rolls back edits and
embedded assets if a nested call fails. Save and render are separate file effects:
perform them after the transaction. They cannot be undone by authoring Undo.
`undo` and `redo` use the same command history as the desktop. Do not share a
GUI-owned document with another thread; the GUI export command forks it first.

A single-operation `dry_run=True` executes against an asset-owning fork and writes
no files. Use a batch dry run for dependent operations; one scratch session carries
their temporary IDs forward. Scratch IDs are disposable and will differ from the
real run's IDs. Dry runs do not reserve paths or grant overwrite permission.

## Supported operations

| Area | Operations and useful arguments |
| --- | --- |
| Lifecycle | `project_create(name, width, height, fps)`, `project_open(path)`, `project_save(path, approve_overwrite)` |
| Inspection | `project_inspect(kind)` where kind is summary/full/scenes/bones/clips/objects/meshes/rigs/assets; `project_validate()` |
| Artwork and objects | `asset_import(path, place=False)`, `object_create(name, x, y, parent_id)`, `object_edit(object_id, transform, visible, locked, name)` |
| Characters and rigs | `character_create(content, x, y)`, `rig_create(template)` or `rig_create(start=[x,y], end=[x,y], parent_id)` |
| Mesh and skin | `mesh_create(asset_id, columns, rows)`, `weights_assign(mesh_id, bone_ids, weights=None)`; explicit weights map vertex IDs to bone IDs and numeric influences |
| Content | `template_apply(content, target_id, mesh_id, x, y)`, `pose_apply(content, target_id)`, `motion_apply(content, target_id)`, `deformer_apply(content, mesh_id)` |
| Animation | `clip_create(name, duplicate)`, `clip_edit(clip_id, name, in_frame, out_frame, loop)`, `keyframe_set(owner_id, property_path, frame, value, interpolation, delete)` |
| Evaluation | `timeline_inspect()`, `frame_evaluate(frame, clip_id)`, `frame_render(path, frame, frames, width, height, bones, approve_overwrite)` |
| Sharing | `project_export(path, format, approve_overwrite)` with project-json / rigaction / rigpack |
| Discovery and history | `library_list(category)`, `plugin_list()`, `diagnostics()`, `undo()`, `redo()` |

Import registers an embedded original source; `place=True` also creates an
instance. `mesh_create` places an independent mesh from a registered asset using
Full triangles by default; supplying columns or rows explicitly requests a grid.
Transform keys use paths such as `transform.x`, `transform.rotation` and `opacity`;
inspect `timeline_inspect` for valid owners/paths. Explicit weights normalize to
four influences and respect protected vertices. Templates, poses and motions
retain the existing anatomy/topology compatibility rules. Original Ari, Nova
and Bolt import layered SVG parts, semantic skeletons and skin bindings together.

An active project cannot be silently replaced: creating requires an empty session,
and opening refuses unsaved changes. Use a separate session when appropriate.
Automation plugin inspection lists the workspace's installed plugin manifests in
safe mode. It does not activate code or inspect arbitrary development directories.

## CLI and offline batch example

Global options precede the operation. Operations use hyphenated names and an
`--args` JSON object. Arguments are validated against the same Python signatures.

```powershell
.venv\Scripts\rigora-automation.exe --root . diagnostics
.venv\Scripts\rigora-automation.exe --root . library-list --args '{"category":"Characters"}'
.venv\Scripts\rigora-automation.exe --root . --dry-run batch examples/agent-workflow.json
.venv\Scripts\rigora-automation.exe --root . --progress batch examples/agent-workflow.json
.venv\Scripts\rigora-automation.exe --root . --project output/agent-character.rigora project-inspect --args '{"kind":"bones"}'
```

Some Windows PowerShell versions strip literal JSON quotes passed to native
executables. The JSON batch file avoids command-line quoting differences. The
same acceptance workflow is available as
`python examples/automation_workflow.py --root . --dry-run` and without `--dry-run`.

The included [agent workflow](../examples/agent-workflow.json) creates a project,
imports the original Ari character, applies a landmark rig template, creates a
walk clip and key, renders four real SVG frames, validates, then saves
`output/agent-character.rigora`. All steps run offline through the GUI services.
Existing output files stop the workflow until explicit overwrite approval is
added to the affected step. Rendered SVGs preserve original vector sources and
evaluated mesh deformation; raster artwork retains its original raster pixels.
Prompt 11 adds image/video/atlas exporters and media imports; see the
[asset/output guide](asset-pipeline.md).

Workflow format is `{"version":1,"steps":[...]}`, at most 128 steps and 1 MiB of
JSON. Each step has `operation`, optional `arguments`, and an optional unique
simple `id`. `$actor.rig_ids.0` references earlier result data by dictionary keys
and list indices; it never evaluates code. Steps are sequential, not a cross-file
transaction. A failed step reports its index/ID; earlier successful steps and
files remain available. A batch dry run writes nothing.

`--project` opens before the operation. `--save PATH` saves afterward; add
`--approve-overwrite` to approve replacing that save destination. Individual file
operations take their own `approve_overwrite` JSON argument. Standard output is a
single `{"ok":true,"result":...}` or `{"ok":false,"error":...}` object; optional
render progress is JSON lines on stderr. Exit codes: **0** success, **2** usage,
**3** validation/approval, **4** I/O. Help is human-readable and exits 0.

## MCP clients

The optional adapter uses the [official Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk),
pinned to `mcp==2.3.0` in the lock. It publishes the same 39 typed operations plus
`workflow_run(workflow, dry_run=True)`. Tools return structured `ok/result` or
`ok/error` data. Each task also accepts `dry_run` and `expected_revision`.
`frame_render` sends per-frame MCP progress when the client supplies a progress
token. No arbitrary shell execution or Python evaluation tools are exposed.

Use the editor's generated stdio configuration, replacing executable and root
with the actual installed paths. A generic client configuration looks like:

```json
{
  "mcpServers": {
    "rigora": {
      "command": "E:/_Projects/GitHub/Rigora 2D/.venv/Scripts/python.exe",
      "args": ["-m", "rigora.interfaces.mcp_server", "--root", "E:/MyRigoraWorkspace"]
    }
  }
}
```

The workspace must already exist. Stdio starts no network listener. MCP refuses
all existing-file overwrites by default, even if a client supplies approval.
The host must start it with `--allow-overwrite`, and the caller must also supply
`approve_overwrite=true` for the specific write. Do not enable this just to bypass
an unexpected existing file; choose a new destination where suitable.

## Authorized files and bounded rendering

All output paths stay inside `--root`. Inputs may also come from explicitly
provided `--asset-root DIRECTORY` roots and Rigora's bundled canonical assets.
Absolute paths are accepted only within those roots. Resolved symlinks/junctions
cannot escape the boundary. Pack discovery checks the same roots before reading.
External project assets must resolve within their saved project directory.
Output names reject device/stream/traversal forms. Source artwork is data-only;
self-contained SVG validation rejects scripts and external references.

Requests allow at most 1 MiB of operation arguments. A synchronous preview allows 1–60 frames,
1–4096 pixels per side, 20,000 triangles, 16 MiB source bytes per frame, 32 MiB
output per frame and 128 MiB output per job. All destinations are checked before
rendering. Queued exports allow up to 600 frames. Rendering/encoding stages privately;
cancellation discards staging. Each file publishes atomically, but a publication
I/O error can leave earlier files. Results include paths, frames and progress.
No credentials or environment dump appears in diagnostics. Python callers can
provide `progress(completed, total)`; CLI and MCP route the same callback.

## Explicit HTTP and server deployment

HTTP is disabled unless selected. Provide a host-owned random bearer token of at
least 32 characters in `RIGORA_MCP_TOKEN`, then run:

```powershell
.venv\Scripts\rigora-mcp.exe --root E:/MyRigoraWorkspace --transport streamable-http --host 127.0.0.1 --port 8765
```

Clients connect to `http://127.0.0.1:8765/mcp` with
`Authorization: Bearer <host-provided token>`. Wrong/missing tokens are rejected
before session creation. The token is not printed. The server limits requests to
2 MiB and active MCP sessions to eight. SDK transport host validation remains on.

For an optional service, install `rigora[mcp]` under a dedicated OS account, create
a dedicated workspace, supply the token through the service's protected environment,
and use the same command as its startup process. A non-loopback listener also
requires `--allow-remote` and explicit `--allowed-host` entries (for example,
`--allowed-host rigora.example.org`). Add `--allowed-origin https://rigora.example.org`
for browser clients from that origin. Put remote integrations behind an HTTPS reverse
proxy and forward the allowed host and Authorization header. Mount/authorize only
the intended workspace and read-only asset roots. Keep overwrite permission off
unless the service owner explicitly enables it.

One process owns one document, shared by its authenticated clients. Calls serialize
through its session lock; use revisions for competing editors. Use a separate
process, root and token per independent workspace. This milestone does not add
multi-user identities, a hosted account service, database collaboration or a cloud
dependency. Deployments and listeners are never started automatically by the GUI.

## Scene cameras

New scenes include Main Camera. `camera_list`, `camera_create`, `camera_edit`,
`camera_activate`, and `camera_delete` use the desktop camera services. Supply
`frame` to `camera_activate` for an exclusive stepped cut; omit it to choose a
default. Camera transforms use the ordinary animation channels. SVG, raster and
video frames use the active evaluated camera. See [Cameras](cameras.md).
