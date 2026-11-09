"""Offline command-line generator for public Rigora plugin projects."""

import argparse
from pathlib import Path

from rigora.sdk.scaffold import generate_plugin


def main() -> int:
    """Generate a tool, deformer or content project without installing or executing it."""
    parser = argparse.ArgumentParser(prog="python -m rigora.sdk")
    parser.add_argument("command", choices=("init",))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--id", required=True, dest="plugin_id")
    parser.add_argument("--kind", choices=("tool", "deformer", "content"), default="tool")
    args = parser.parse_args()
    try:
        package = generate_plugin(args.directory, args.plugin_id, args.kind)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Cannot create plugin: {error}\n")
    print(f"Created plugin source: {package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
