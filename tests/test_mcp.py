"""Official MCP SDK schemas, real stdio workflows and authenticated optional HTTP mode."""

import asyncio
import os
import shutil
import sys

import pytest

pytest.importorskip("mcp")

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from starlette.testclient import TestClient

from rigora.api import RigoraAPI
from rigora.interfaces.mcp_server import create_server, http_app


def test_official_client_schema_errors_and_memory_workflow(tmp_path):
    """The official client discovers typed tools and runs validated edits with stable IDs."""

    async def run():
        """Use the SDK's in-memory transport to test tool validation and structured results."""
        api = RigoraAPI(tmp_path, allow_overwrite=False)
        server = create_server(api)
        async with Client(server) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"project_create", "character_create", "frame_render", "workflow_run"} <= names
            assert not any("shell" in name or name == "eval" for name in names)
            invalid = await client.call_tool("project_create", {"width": True})
            assert invalid.is_error
            created = await client.call_tool("project_create", {"name": "MCP character"})
            assert created.structured_content["ok"]
            actor = await client.call_tool("character_create", {})
            assert (
                len(actor.structured_content["result"]["data"]["mesh_ids"])
                == len(api.document.scene.meshes)
                > 0
            )
            error = await client.call_tool("project_save", {"path": "../outside.rigora"})
            assert error.structured_content["error"]["code"] == "path_outside_root"
            snapshot = await client.call_tool("project_inspect", {})
            dry = await client.call_tool("object_create", {"name": "Transient", "dry_run": True})
            assert dry.structured_content["result"]["dry_run"]
            after = await client.call_tool("project_inspect", {})
            assert (
                snapshot.structured_content["result"]["revision"]
                == after.structured_content["result"]["revision"]
            )

    asyncio.run(run())


def test_stdio_agent_workflow_uses_official_sdk(tmp_path, catalog_cache_root):
    """A genuine stdio subprocess renders and saves a portable character with no GUI process."""
    from rigora.application_services.illustration_cache import cached_catalog

    source = cached_catalog(catalog_cache_root)
    shutil.copytree(source, tmp_path / ".rigora-automation" / "cache" / "content" / source.name)

    async def run():
        """Launch Rigora through the SDK transport and exchange structured MCP tool messages."""
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "rigora.interfaces.mcp_server", "--root", str(tmp_path)],
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        async with Client(params) as client:
            await client.call_tool("project_create", {"name": "Stdio offline"})
            actor = await client.call_tool("character_create", {})
            rig = actor.structured_content["result"]["data"]["rig_ids"][0]
            motion = await client.call_tool(
                "motion_apply", {"content": "Natural · Walk", "target_id": rig}
            )
            assert motion.structured_content["ok"]
            progress = []

            async def reported(completed, total, message):
                """Collect real protocol progress notifications from the stdio render worker."""
                progress.append((completed, total))

            rendered = await client.call_tool(
                "frame_render",
                {"path": "frame.svg", "frame": 6},
                progress_callback=reported,
            )
            assert rendered.structured_content["result"]["data"]["status"] == "completed"
            assert progress == [(1, 1)]
            saved = await client.call_tool("project_save", {"path": "character.rigora"})
            assert saved.structured_content["ok"]
            forbidden = await client.call_tool(
                "project_save", {"path": "character.rigora", "approve_overwrite": True}
            )
            assert forbidden.structured_content["error"]["code"] == "approval_required"
            import importlib.util

            if importlib.util.find_spec("resvg_py") is not None:
                job = await client.call_tool(
                    "render_submit",
                    {
                        "path": "queued.png",
                        "frames": [0, 1],
                        "width": 64,
                        "height": 64,
                    },
                )
                key = job.structured_content["result"]["data"]["job_id"]
                for _ in range(100):
                    state = await client.call_tool("render_status", {"job_id": key})
                    data = state.structured_content["result"]["data"]
                    if data["status"] in ("completed", "failed", "cancelled"):
                        break
                    await asyncio.sleep(0.02)
                assert data["status"] == "completed", data
                assert data["completed"] == 2

    asyncio.run(run())
    assert (tmp_path / "frame.svg").stat().st_size > 100
    assert (tmp_path / "character.rigora").exists()


def test_http_authentication_precedes_session_creation(tmp_path):
    """Explicit HTTP mode rejects absent/wrong tokens before the SDK touches project state."""
    token = "a" * 48
    api = RigoraAPI(tmp_path, allow_overwrite=False)
    server = create_server(api)
    app = http_app(server, token)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.post("/mcp", json={}).status_code == 401
        assert (
            client.post("/mcp", headers={"Authorization": "Bearer wrong"}, json={}).status_code
            == 401
        )
        initialized = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200
        assert "Rigora" in initialized.text
        rejected = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}", "Host": "outside.example"},
            json={},
        )
        assert rejected.status_code == 421
    assert api.document.project is None
