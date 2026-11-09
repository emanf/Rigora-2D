"""Standard-library desktop startup and Qt-free animation evaluation adapters."""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from rigora import APP_NAME, __version__
from rigora.app.application import ApplicationRuntime
from rigora.app.bootstrap import run_desktop, run_headless
from rigora.app.config import load_config
from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError


def _run(argv: Sequence[str] | None, *, force_headless: bool) -> int:
    """Parse adapter options and run desktop or Qt-free diagnostics with meaningful exit codes."""
    values = list(sys.argv[1:] if argv is None else argv)
    if values[:1] == ["automation"]:
        from rigora.interfaces.cli.automation import automation_main

        return automation_main(values[1:])
    parser = argparse.ArgumentParser(
        prog="rigora-headless" if force_headless else "rigora",
        description=("Rigora 2D desktop workspace and deterministic animation evaluation."),
        epilog="Use rigora automation --help for project operations and batch workflows.",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--headless", action="store_true", help="Run a Qt-free startup diagnostic.")
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        default=None,
        help="Start with all executable plugins disabled.",
    )
    parser.add_argument(
        "--evaluate", type=Path, metavar="PROJECT", help="Evaluate a .rigora project without Qt."
    )
    parser.add_argument(
        "--frame", type=float, help="Absolute timeline frame; defaults to clip start."
    )
    parser.add_argument("--clip", help="Clip UUID; defaults to the first clip.")
    parser.add_argument(
        "--loop", action="store_true", help="Wrap the evaluation frame through the clip range."
    )
    parser.add_argument(
        "--log-level", metavar="LEVEL", help="DEBUG, INFO, WARNING, ERROR, CRITICAL"
    )
    args = parser.parse_args(argv)
    if args.evaluate is None and (args.frame is not None or args.clip is not None or args.loop):
        parser.error("--frame, --clip and --loop require --evaluate PROJECT")
    try:
        config = load_config(log_level=args.log_level, safe_mode=args.safe_mode)
    except ValueError as error:
        parser.error(str(error))
    if args.evaluate is not None:
        try:
            with ApplicationRuntime(config) as runtime:
                document = DocumentService()
                document.open(args.evaluate)
                runtime.plugins.attach(document)
                if args.clip is not None:
                    document.select_animation_clip(args.clip)
                animation = document.animation
                frame = animation.playback.range.start if args.frame is None else args.frame
                result = animation.evaluate(frame, loop=args.loop)
                print(json.dumps(result.to_dict(), allow_nan=False))
            return 0
        except ProjectError as error:
            print(f"Cannot evaluate project: {error}", file=sys.stderr)
            return 1
    if force_headless or args.headless:
        info = run_headless(config)
        print(json.dumps({**asdict(info), "status": "ok", "mode": "headless"}))
        return 0
    try:
        return run_desktop(config)
    except ModuleNotFoundError as error:
        if error.name is not None and error.name.split(".")[0] == "PySide6":
            print(
                "Desktop dependencies are missing. Run `uv sync --locked --extra gui` "
                "or install `rigora[gui]`; use --headless for Qt-free startup.",
                file=sys.stderr,
            )
            return 1
        raise
    except KeyboardInterrupt:
        return 130


def main(argv: Sequence[str] | None = None) -> int:
    """Start the standard CLI adapter, allowing explicit headless operation."""
    return _run(argv, force_headless=False)


def headless_main(argv: Sequence[str] | None = None) -> int:
    """Start the diagnostic adapter without importing or initializing Qt."""
    return _run(argv, force_headless=True)
