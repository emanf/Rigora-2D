# CLI reference

All commands run locally. Entry points are installed with the wheel; from the
checkout use `.venv\Scripts\COMMAND.exe`. Global options precede subcommands.
`--help` is the authoritative offline list for the installed version.

| Command | Purpose |
| --- | --- |
| `rigora` | Desktop; optional `--safe-mode`, `--log-level LEVEL` |
| `rigora --headless` / `rigora-headless` | Startup diagnostics without Qt |
| `rigora-headless --evaluate PATH --frame 6` | Canonical pose JSON; optional `--clip UUID`, `--loop` |
| `rigora-automation` | Validated operations, JSON results and batch workflows |
| `rigora-mcp` | Official MCP stdio server; [setup](mcp-setup.md) |
| `python -m rigora.sdk init DIRECTORY --id org.author.name --kind tool` | Generate an original plugin project; kinds tool/deformer/content |

## Automation options

`rigora-automation [OPTIONS] OPERATION --args JSON_OBJECT`

| Option | Behavior |
| --- | --- |
| `--root DIRECTORY` | Existing writable workspace, default current directory |
| `--asset-root DIRECTORY` | Additional allowed read-only import root; repeatable |
| `--project PATH` | Open a saved project before the operation |
| `--dry-run` | Execute on a scratch session without publishing files |
| `--save PATH` | Save after the operation/batch |
| `--approve-overwrite` | Approve replacement of that `--save` destination |
| `--progress` | JSON progress lines on stderr |
| `--encoder PATH` | Explicit compatible local FFmpeg executable for MP4, WebM, ProRes MOV or FFV1 MKV |

Use `batch FILE.json` for dependent steps. The
[original agent workflow](../examples/agent-workflow.json) contains working
references to IDs returned by earlier steps. Native argument quoting differs
between Windows shells; batch files avoid stripping quotes from inline JSON.
See [automation.md](automation.md) for batch reference syntax, error codes,
filesystem authorization and transaction rules.

The 39 operation names are the Python names below with underscores replaced by
hyphens. `--args` fields keep their Python underscores. Complete typed signatures
can be printed using the [Python API example](python-api.md).

| Area | Operations |
| --- | --- |
| Projects | project_create, project_open, project_inspect, project_validate, project_save, project_export |
| Media | asset_import, sequence_import, sequence_place, spritesheet_import, layered_import, layered_place, audio_import, asset_pack_install |
| Authoring | object_create, object_edit, character_create, rig_create, mesh_create, weights_assign |
| Content | template_apply, pose_apply, motion_apply, deformer_apply, library_list |
| Animation | clip_create, clip_edit, keyframe_set, timeline_inspect, frame_evaluate |
| Output | frame_render, render_submit, render_status, render_cancel, output_formats |
| Session | plugin_list, diagnostics, undo, redo |

`render-submit` waits for owned jobs before the CLI exits; its final result reports
completion. Long-lived queue polling/cancellation is useful through Python or
MCP sessions. A separate CLI process cannot inspect another process's queue.
Output formats, settings and limits are in [asset-pipeline.md](asset-pipeline.md).

Automation stdout is one `{"ok":true,"result":...}` or
`{"ok":false,"error":...}` object. Exit codes: 0 success, 2 usage, 3
validation/approval, 4 I/O, 130 cancellation. Desktop/headless startup uses 1
for missing GUI dependencies or evaluation failure and 2 for usage/config errors.
Help exits 0; optional progress and application diagnostics go to stderr.
