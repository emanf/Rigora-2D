# Local MCP setup

Install the `mcp` extra in the **same environment** as Rigora. Create the workspace
directory before starting the server. The desktop's **AI / Automation → Automation
& MCP…** window prepares paths and a client configuration; it does not start an
external server or expose your open unsaved editor document.

For a generic stdio client, replace these two paths with your installation and
existing project workspace:

```json
{
  "mcpServers": {
    "rigora": {
      "command": "E:/Rigora/.venv/Scripts/python.exe",
      "args": ["-m", "rigora.interfaces.mcp_server", "--root", "E:/RigoraWorkspace"]
    }
  }
}
```

Stdio opens no network listener. The server owns a separate canonical session;
open saved projects explicitly and save to new paths to return work to the editor.
Use `diagnostics`, `library_list`, `project_create`, `character_create`,
`motion_apply`, `frame_evaluate`, then `project_save`. Reuse IDs in structured
results. `workflow_run` accepts the documented batch contract, defaulting to a
dry run. The client must inspect `ok`/`error` as well as protocol validation errors.

The 39 typed operations match Python/CLI. The additional workflow tool groups
dependent calls; it is not an arbitrary Python or shell interface. All mutations
use the same validated commands. `dry_run` and `expected_revision` are supported.
MCP refuses overwrites unless both the host starts with `--allow-overwrite` and
the specific write supplies `approve_overwrite=true`. Read-only asset roots can
be added with repeated `--asset-root` options.

For a reproducible official-client check from the source release:

```powershell
python -m tools.release_smoke --root build/mcp-smoke-new --mcp
```

Use a fresh destination. This starts and closes its own stdio server, opens the
generated project, evaluates animation and checks a rejected invalid scalar.
`tests/test_mcp.py` additionally checks actual PNG queue output when codecs are
installed, protocol progress, authorization and authenticated HTTP behavior.

HTTP is optional and never starts by default. The exact host/token/origin policy,
command line and reverse-proxy limitations are in
[automation.md](automation.md#explicit-http-and-server-deployment). Keep credentials
in the host environment rather than client messages or project files. There is
no cloud dependency for local work.
