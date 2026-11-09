"""Frozen desktop/CLI entry point with an offline, offscreen verification mode."""

import asyncio
import importlib
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import traceback
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path


async def mcp_self_test(root: Path) -> None:
    """Exercise the packaged stdio server with the official local client and isolated workspace."""
    from mcp import Client
    from mcp.client.stdio import StdioServerParameters

    from rigora.infrastructure.processes import module_command

    command = module_command("rigora.interfaces.mcp_server", "--root", str(root))
    parameters = StdioServerParameters(command=command[0], args=command[1:], env=dict(os.environ))
    async with Client(parameters) as client:
        tools = await client.list_tools()
        if "project_create" not in {tool.name for tool in tools.tools}:
            raise RuntimeError("The frozen MCP server did not expose authoring operations.")
        result = await client.call_tool("diagnostics", {})
        if not result.structured_content or not result.structured_content.get("ok"):
            raise RuntimeError("The frozen MCP server did not complete diagnostics.")


def bundle_self_test(report: Path) -> int:
    """Verify native codecs, exact bundled assets, Qt icons, UI startup and project persistence."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["RIGORA_SAFE_MODE"] = "1"
    result: dict = {"status": "failed"}
    try:
        import hashlib

        from PySide6.QtGui import QImage
        from PySide6.QtWidgets import QApplication

        from rigora.api import RigoraAPI
        from rigora.app.application import ApplicationRuntime
        from rigora.app.config import ApplicationConfig
        from rigora.infrastructure.processes import module_command
        from rigora.presentation.garbage_collection import GuiGarbageCollector
        from rigora.presentation.icons import IconProvider
        from rigora.presentation.viewmodels.main_window import MainWindowViewModel
        from rigora.presentation.views.main_window import MainWindow
        from rigora.resources import application_root, asset_path

        for module in (
            "PIL.Image",
            "resvg_py",
            "psd_tools",
            "pypdfium2",
            "mediapipe",
            "mcp",
            "shapely",
        ):
            importlib.import_module(module)
        from resvg_py import svg_to_bytes

        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
            '<rect width="16" height="16" fill="red"/></svg>'
        )
        raster = svg_to_bytes(svg_string=svg)
        if QImage.fromData(raster).isNull():
            raise RuntimeError("The frozen SVG rasterizer returned an invalid image.")
        # Check against the builder's inventory, without using any source-tree fallback.
        assets = application_root() / "assets"
        if not (application_root() / "plugins").is_dir():
            raise RuntimeError("The application plugin folder is missing.")
        if (Path(__file__).parent / "rigora" / "assets").exists():
            raise RuntimeError("The bundle contains a duplicate private asset tree.")
        inventory = json.loads((Path(__file__).parent / "asset-inventory.json").read_text())
        for relative, digest in inventory.items():
            path = asset_path(relative)
            if (
                not path.is_relative_to(assets)
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest
            ):
                raise RuntimeError(f"Missing or changed bundled asset: {relative}")
        with tempfile.TemporaryDirectory(prefix="rigora-bundle-check-") as temporary:
            root = Path(temporary)
            os.environ["RIGORA_PREFERENCES_PATH"] = str(root / "preferences.json")
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            cli = module_command("rigora.interfaces.cli.main", "--headless", "--safe-mode")
            diagnostic = subprocess.run(
                cli, capture_output=True, text=True, timeout=30, check=True, creationflags=flags
            )
            if json.loads(diagnostic.stdout).get("status") != "ok":
                raise RuntimeError(
                    "The bundled console companion did not return valid diagnostics."
                )
            worker = subprocess.run(
                module_command("rigora.sdk.worker"),
                input="{}",
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                creationflags=flags,
            )
            if worker.returncode != 1 or "error" not in json.loads(worker.stdout):
                raise RuntimeError("The bundled plugin worker did not return a protocol error.")
            api = RigoraAPI(root)
            try:
                api.execute("project_create", {"name": "Bundle check"})
                actor = api.execute("character_create", {"content": "Bolt · Stick robot"}).data
                api.execute(
                    "motion_apply", {"content": "Natural · Walk", "target_id": actor["rig_ids"][0]}
                )
                expected = api.document.animation.evaluate(6)
                if expected.warnings or not expected.meshes:
                    raise RuntimeError("The packaged character did not evaluate cleanly.")
                selected_clip = api.document.selected_clip_id
                api.execute("project_save", {"path": "check.rigora"})
                saved_project = api.document.project
                api.execute("project_open", {"path": "check.rigora"})
                if api.document.project != saved_project:
                    raise RuntimeError("Packaged project persistence changed authored data.")
                if selected_clip is not None:
                    api.document.select_animation_clip(selected_clip)
                if api.document.animation.evaluate(6) != expected:
                    raise RuntimeError("Packaged project persistence changed the evaluated pose.")
                api.execute("frame_render", {"path": "check.png", "frame": 6})
            finally:
                api.close()
            asyncio.run(asyncio.wait_for(mcp_self_test(root), timeout=45))
            application = QApplication(["Rigora bundle check"])
            collector = GuiGarbageCollector(application)
            with ApplicationRuntime(ApplicationConfig(safe_mode=True)) as runtime:
                icons = IconProvider()
                if icons.icon("play_arrow").pixmap(20, 20).isNull():
                    raise RuntimeError("The packaged Material Icons font did not render.")
                window = MainWindow(MainWindowViewModel(runtime.info, plugins=runtime.plugins))
                try:
                    window.show()
                    application.processEvents()
                    if window.grab().isNull():
                        raise RuntimeError("The packaged desktop did not render offscreen.")
                finally:
                    window.close()
                    collector.close()
                    application.processEvents()
        result = {
            "status": "passed",
            "assets": len(inventory),
            "checks": [
                "codec imports",
                "SVG rasterizer",
                "asset hashes",
                "public data folders",
                "console companion",
                "plugin worker routing",
                "MCP stdio round trip",
                "animated character",
                "save/reopen",
                "PNG export",
                "Material Icons",
                "offscreen desktop",
            ],
        }
    except Exception:
        result["error"] = traceback.format_exc()
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    """Dispatch bundled diagnostics and known Python module entry points, or open the desktop."""
    multiprocessing.freeze_support()
    # GUI bootloaders on Windows omit standard handles; libraries may still log to them.
    with ExitStack() as streams:
        if sys.stdout is None:
            streams.enter_context(redirect_stdout(streams.enter_context(open(os.devnull, "w"))))
        if sys.stderr is None:
            streams.enter_context(redirect_stderr(streams.enter_context(open(os.devnull, "w"))))
        return dispatch()


def dispatch() -> int:
    """Route only supported embedded adapters; unknown Python interpreter options fail closed."""
    if sys.argv[1:2] == ["--bundle-self-test"]:
        if len(sys.argv) != 3:
            return 2
        return bundle_self_test(Path(sys.argv[2]))
    if sys.argv[1:2] == ["-m"]:
        entry_points = {
            "rigora.sdk.worker": "main",
            "rigora.interfaces.mcp_server": "main",
            "rigora.interfaces.cli.automation": "automation_main",
            "rigora.interfaces.cli.main": "main",
        }
        if len(sys.argv) < 3 or sys.argv[2] not in entry_points:
            return 2
        module = sys.argv[2]
        sys.argv = [module, *sys.argv[3:]]
        return getattr(importlib.import_module(module), entry_points[module])()
    from rigora.interfaces.cli.main import main as cli_main

    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
