"""Run the documented offline agent workflow through Rigora's canonical Python API."""

import argparse
import json
from pathlib import Path

from rigora.api import AutomationError, RigoraAPI
from rigora.interfaces.cli.automation import run_batch


def main() -> int:
    """Create, animate, preview, validate and save original content inside an authorized root."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        workflow = json.loads(
            Path(__file__).with_name("agent-workflow.json").read_text(encoding="utf-8")
        )
        result = run_batch(RigoraAPI(args.root), workflow, dry_run=args.dry_run)
        print(json.dumps({"ok": True, "result": result}, indent=2))
        return 0
    except (AutomationError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
