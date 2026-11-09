# Python API 1

`rigora.api` is the supported validated integration facade. It exports `RigoraAPI`,
`AutomationError`, `OperationResult`, `API_VERSION` and `OPERATIONS`. The underlying
service methods are typed authoring APIs; immutable domain records are not intended
for direct mutation. No Qt application is needed. See [automation.md](automation.md)
for argument contracts, revision checks, dry runs and transactions.

Whole-Object pickups and releases use `scene_attach` / `scene_detach`; named grips
use `attachment_point_save` / `attachment_point_remove`. These preserve internal
rig binding and share the [Scene attachment editor's services](scene-attachments.md).

```python
from pathlib import Path
from rigora.api import RigoraAPI

root = Path("my-workspace").resolve()
root.mkdir(exist_ok=True)
api = RigoraAPI(root)
try:
    api.execute("project_create", {"name": "First character"})
    actor = api.execute("character_create", {"content": "Iris · Woman · Front"}).data
    api.execute("motion_apply", {"content": "Natural · Walk", "target_id": actor["rig_ids"][0]})
    api.execute("frame_render", {"path": "walk.svg", "frame": 6})
    api.execute("project_save", {"path": "walk.rigora"})
finally:
    api.close()
```

Use fresh output names. `approve_overwrite` is explicit per operation; the host
can prohibit it with `allow_overwrite=False`. `root` must exist; read-only
`asset_roots` are additional authorized import directories. Operations return
owned JSON-compatible results; use the returned IDs for further edits. `close()`
cancels unfinished owned rendering work, so poll jobs to completion before closing
if their output is required. Queue jobs render snapshots, never live editor state.

All supported operations and complete Python signatures are inspectable offline:

```python
import inspect
from rigora.api import RigoraAPI, OPERATIONS

for name in OPERATIONS:
    print(name, inspect.signature(getattr(RigoraAPI, name)))
```

Lifecycle/objects/rigging/meshes/keys/content share `DocumentService` and its undo
history. Numeric evaluation shares `SceneEvaluator`. Media and export contracts,
limits, host-configured encoders and trusted exporter injection are documented in
[asset-pipeline.md](asset-pipeline.md). Executable plugin activation is a separate
host responsibility; automation only inspects manifests in safe mode.

Errors expose a stable `.code` and user-facing message; callers should catch
`AutomationError` and handle conflicts rather than retrying mutations blindly.
`expected_revision=result.revision` rejects stale authored state. Read/validate
before save; file effects are not undone by project Undo. A failed in-memory
transaction restores records and embedded asset ownership, but cannot reverse
already-published files. Keep saves/renders outside transactions.

Runnable examples: [automation_workflow.py](../examples/automation_workflow.py),
[agent-workflow.json](../examples/agent-workflow.json),
[asset_pipeline_workflow.py](../examples/asset_pipeline_workflow.py). The release
smoke also demonstrates a trusted generated plugin and official MCP client.

Prompts 13–16 add `motion_retarget`, `face_create`, `face_controls`, `lip_sync_set`,
`audio_waveform`, `dynamics_configure`, `dynamics_bake`, `bounce_apply`,
`squash_apply`, `character_parts_import`, `character_rig_generate`,
`character_mesh_generate`, `character_bind` and `character_template_save`.
These are also discoverable CLI/MCP operations. Retargeting accepts editable ID
mappings/corrections and an optional authorized source project path. Lip-sync cues
use `{"seconds": 0.2, "phoneme": "AH"}` rows. In-memory operations support
scratch dry runs; template export validates the authorized output and skips writes
in a dry run. The typed services provide additional detailed authoring methods.

`bindings_inspect` returns stable connection rows (`id`, `kind`, `source`, `target`).
`binding_create(sources, target, rigid=False)` binds artwork to bones, parents bones,
or links solid artwork to another image/shape/folder. Sources and artwork targets
accept mesh or object IDs. `binding_remove` accepts either `sources` or the exact
`relationships` IDs returned by inspection. It preserves endpoints and removes
detached bones' live physics through the same service as the desktop. These three
operations are available through Python, CLI and MCP, with ordinary dry-run,
revision and Undo behavior. Plugins can use `request.service("bindings")`.

`tracking_apply` accepts local detector observations without opening hardware:

```python
api.execute(
    "tracking_apply",
    {
        "target_id": face_or_character_id,
        "start": 24,
        "smoothing": 0.35,
        "samples": [
            {"seconds": 0, "face": {"jawOpen": 0}, "angles": {"head": 0}},
            {"seconds": 0.2, "face": {"jawOpen": 0.8}, "angles": {"head": 12}},
        ],
    },
)
```

The first observation supplies neutral calibration. Up to 600 increasing samples
become one undoable take; existing keys outside the captured intervals survive.
See [camera performance](camera-performance.md) for supported channels and limits.

## Production authoring and export checks

`media_rig_import` creates the same editable rig/action as the desktop's
[Media to Rig](video-to-rig.md) workspace. It accepts authorized video, stills, image sequences and
model paths, an optional normalized subject region, sampling/confidence/smoothing
settings and optional reference cutout extraction. It never downloads implicitly;
dry runs analyze a scratch project without publication. The guide includes a
complete example and the current body/animal reconstruction limits.

The following operations share Python, CLI and MCP implementations. Inspect the
public Python method signatures above or CLI help for exact optional parameters:

| Operation | Purpose |
| --- | --- |
| `asset_replace` | Replace an authorized artwork file while preserving IDs, UVs, bindings and Undo revisions. |
| `audio_tracks`, `audio_track_edit`, `audio_track_remove` | List/edit/remove independently trimmed, faded and gained PCM placements. |
| `event_set` | Author a typed marker with bounded non-executable JSON payload. |
| `motion_layer_edit` | Set arranged-action layer order, weight, fades, mask, Override/Additive and Mute/Solo. |
| `path_motion`, `path_artwork` | Author original cubic Object/camera paths or editable SVG controls. |
| `game_region_edit`, `particle_emitter_edit` | Create/edit owned hit/hurt regions and deterministic seeded vector emitters. |
| `camera_shots`, `camera_shot_edit`, `camera_follow` | Inspect/edit camera shots, transitions and target following. |
| `state_machine_define`, `state_machine_sample` | Save validated Object states/conditions and evaluate a read-only parameter preview. |
| `export_preflight` | Check every requested sample/source, budgets and explicit native adapter capabilities. |

```python
report = api.execute(
    "export_preflight",
    {
        "format": "godot-2d",
        "frames": list(range(25)),
        "width": 512,
        "height": 512,
        "fps": 24,
    },
).data
if not report["ready"]:
    print(report["findings"])

api.execute(
    "event_set",
    {
        "name": "Left foot",
        "frame": 8,
        "event_type": "footstep",
        "payload": {"surface": "stone", "gain": 0.7},
    },
)
```

Preflight is read-only and writes no destination. A report describes its captured
revision and requested samples, not every possible project state. Event seconds
retime through explicit output samples; source `frame` remains authored timing.
Godot native 2D uses format `godot-2d`; other engine capability differences and
manual integration requirements are in [engine exports](game-engine-export.md).

Direct Python service clients can additionally use `ContactEditingService` for
foot intervals/removal/FK baking, `RecoveryStore` for portable checkpoints and
`StateMachinePreview` for a persistent forward parameter preview. These modules
remain Qt-free. GUI workers always operate on a document fork and adopt results
only against the captured revision/context.
