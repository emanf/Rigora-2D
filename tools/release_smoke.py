"""Exercise installed canonical workflows offline; run with python -m tools.release_smoke."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from rigora.api import API_VERSION, OPERATIONS, RigoraAPI
from rigora.application_services.deformation import DeformationPreset, DeformationService
from rigora.application_services.plugins import PluginManager
from rigora.infrastructure.preferences import PreferencesStore
from rigora.sdk.scaffold import generate_plugin


async def mcp_smoke(root: Path) -> None:
    """Use the official stdio client against a separate local Rigora session and validate errors."""
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "rigora.interfaces.mcp_server", "--root", str(root)],
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    async with Client(params) as client:
        opened = await client.call_tool("project_open", {"path": "character.rigora"})
        assert opened.structured_content["ok"]
        evaluated = await client.call_tool("frame_evaluate", {"frame": 6})
        assert evaluated.structured_content["ok"]
        invalid = await client.call_tool("frame_evaluate", {"frame": True})
        assert invalid.is_error


def run(root: Path, *, mcp: bool = False, raster: bool = False) -> dict:
    """Create only fresh artifacts, test undo/reopen/plugin/CLI, and optionally test MCP/codecs."""
    root.mkdir(parents=True, exist_ok=False)
    api = RigoraAPI(root)
    manager = PluginManager(PreferencesStore(root / "isolated-workspace.json"))
    try:
        assert api.execute("diagnostics").data["api_version"] == API_VERSION == "1"
        assert len(OPERATIONS) == len(set(OPERATIONS))
        assert {
            "project_create",
            "frame_render",
            "motion_retarget",
            "face_create",
            "lip_sync_set",
            "dynamics_bake",
            "character_rig_generate",
            "character_template_save",
        } <= set(OPERATIONS)
        api.execute("project_create", {"name": "Release smoke", "width": 800, "height": 600})
        actor = api.execute("character_create", {"content": "Dash · Runner", "x": 350}).data
        api.execute("motion_apply", {"content": "Natural · Walk", "target_id": actor["rig_ids"][0]})
        baseline = api.document.project
        api.execute(
            "deformer_apply", {"content": "Soft breathing", "mesh_id": actor["mesh_ids"][0]}
        )
        deformed = api.document.project
        api.execute("undo")
        assert api.document.project == baseline
        api.execute("redo")
        assert api.document.project == deformed
        expected = api.document.animation.evaluate(6)
        assert not expected.warnings
        selected_clip = api.document.selected_clip_id
        sources = {a.id: api.document.read_asset(a.id) for a in api.document.project.assets}
        api.execute("project_save", {"path": "character.rigora"})
        copy = RigoraAPI(root)
        copy.execute("project_open", {"path": "character.rigora"})
        copy.document.select_animation_clip(selected_clip)
        assert copy.document.animation.evaluate(6) == expected
        assert all(copy.document.read_asset(key) == value for key, value in sources.items())
        copy.close()
        api.execute("frame_render", {"path": "preview.svg", "frame": 6})
        if raster:
            api.execute("frame_render", {"path": "preview.png", "frame": 6})
        package = generate_plugin(root / "original-plugin", "org.rigora.release", "deformer")
        manager.discover((package,), installed=False)
        assert not manager.contexts
        # This smoke owns and just generated the original executable example being trusted.
        manager.trust("org.rigora.release")
        manager.enable("org.rigora.release", persist=False)
        manager.attach(api.document)
        DeformationService(api.document).add(
            actor["mesh_ids"][0],
            DeformationPreset("Smoke wave", "org.rigora.release.wave", {"amount": 12}),
        )
        plugin_pose = api.document.animation.evaluate(6)
        assert not plugin_pose.warnings and plugin_pose.meshes != expected.meshes
        manager.disable("org.rigora.release")
        manager.attach(api.document)
        assert api.document.animation.evaluate(6).warnings
        cli = subprocess.run(
            [
                sys.executable,
                "-m",
                "rigora.interfaces.cli.automation",
                "--root",
                str(root),
                "--project",
                "character.rigora",
                "project-validate",
            ],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert cli.returncode == 0, cli.stderr + cli.stdout
        assert json.loads(cli.stdout)["result"]["data"]["valid"]
        if mcp:
            asyncio.run(mcp_smoke(root))
        assert not any(name.startswith(("PySide", "PyQt")) for name in sys.modules)
        return {
            "status": "passed",
            "root": str(root),
            "source_assets": len(sources),
            "undo_reopen": "passed",
            "plugin": "passed",
            "cli": "passed",
            "mcp": "passed" if mcp else "not requested",
            "png": "passed" if raster else "not requested",
        }
    finally:
        manager.shutdown()
        api.close()


def main() -> None:
    """Select an empty destination and explicitly opt into optional dependency checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="New artifact directory")
    parser.add_argument("--mcp", action="store_true")
    parser.add_argument("--raster", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args.root.resolve(), mcp=args.mcp, raster=args.raster), indent=2))


if __name__ == "__main__":
    main()
