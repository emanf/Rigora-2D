"""Resolve Python module subprocesses in source installs and native desktop bundles."""

import sys
from pathlib import Path


def module_command(module: str, *arguments: str) -> list[str]:
    """Use the bundled console peer on Windows so workers and MCP retain standard streams."""
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        executable = executable.with_name("RigoraCLI.exe")
    return [str(executable), "-m", module, *arguments]
