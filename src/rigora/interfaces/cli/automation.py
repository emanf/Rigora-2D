"""Predictable JSON CLI operations and bounded, explicit automation batch workflows."""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from rigora.api import AutomationError, RigoraAPI
from rigora.application_services.automation import OPERATIONS
from rigora.domain.project import ProjectError
from rigora.infrastructure.project_storage import _decode


def resolve_references(value: Any, results: dict[str, Any]) -> Any:
    """Substitute data references such as $actor.rig_ids.0 without evaluating Python or paths."""
    if isinstance(value, str) and value.startswith("$"):
        parts = value[1:].split(".")
        try:
            result = results[parts[0]]
            for part in parts[1:]:
                result = result[int(part)] if isinstance(result, list) else result[part]
            return result
        except (KeyError, IndexError, ValueError, TypeError):
            raise AutomationError(
                "invalid_reference", "A batch reference does not resolve to an earlier result."
            ) from None
    if isinstance(value, list):
        return [resolve_references(item, results) for item in value]
    if isinstance(value, dict):
        return {key: resolve_references(item, results) for key, item in value.items()}
    return value


def run_batch(api: RigoraAPI, workflow: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Execute at most 128 inspectable tasks; each edit is undoable and each output atomic.

    This is a sequential workflow, not a cross-file transaction. Failed steps report
    their index and leave prior successful operations reviewable. Python callers can
    group only authoring edits with RigoraAPI.transaction for all-or-nothing undo.
    A complete dry run uses one scratch session and produces no output files.
    """
    if not isinstance(workflow, dict) or set(workflow) - {"version", "steps"}:
        raise AutomationError("invalid_workflow", "Workflow must contain version and steps.")
    if (
        type(workflow.get("version")) is not int
        or workflow.get("version") != 1
        or not isinstance(workflow.get("steps"), list)
        or not 1 <= len(workflow["steps"]) <= 128
    ):
        raise AutomationError("invalid_workflow", "Workflow version 1 requires 1–128 steps.")
    runner = api
    if dry_run:
        runner = RigoraAPI(
            api.root,
            asset_roots=api.asset_roots,
            document=api.document.fork(),
            allow_overwrite=api.allow_overwrite,
            encoder=api.encoder,
            speech_analyzer=api.speech_analyzer,
            exporters=api.exporters,
        )
        runner._dry_run = True
        runner.library.additional_packs = api.library.additional_packs
    results: dict[str, Any] = {}
    ordered = []
    for index, step in enumerate(workflow["steps"]):
        if not isinstance(step, dict) or not set(step) <= {"id", "operation", "arguments"}:
            raise AutomationError(
                "invalid_workflow",
                f"Step {index} must contain operation, arguments and an optional unique id.",
            )
        name = step.get("id", str(index))
        if not isinstance(name, str) or not name or name in results or "." in name:
            raise AutomationError(
                "invalid_workflow", f"Step {index} requires a unique simple string id."
            )
        try:
            result = runner.execute(
                step.get("operation", ""), resolve_references(step.get("arguments", {}), results)
            )
        except AutomationError as error:
            raise AutomationError(error.code, f"Step {index} ({name}): {error}") from None
        results[name] = result.data
        ordered.append({"id": name, **result.to_dict()})
    return {"status": "planned" if runner._dry_run else "completed", "steps": ordered}


def automation_main(argv: list[str] | None = None) -> int:
    """Run JSON automation without desktop imports; exit 0 success, 2 usage, 3 validation, 4 IO."""
    parser = argparse.ArgumentParser(
        prog="rigora-automation",
        description="Offline Rigora Python-service operations and batch workflows.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Authorized workspace directory; all outputs stay here.",
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        action="append",
        default=[],
        help="Additional authorized read-only asset directory.",
    )
    parser.add_argument(
        "--project", help="Open this workspace-relative project before the operation."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Use an isolated session and do not write outputs."
    )
    parser.add_argument(
        "--save", help="Save the resulting project to this workspace-relative .rigora file."
    )
    parser.add_argument(
        "--approve-overwrite",
        action="store_true",
        help="Explicitly approve overwriting the --save destination.",
    )
    parser.add_argument(
        "--progress", action="store_true", help="Emit render progress as JSON lines on stderr."
    )
    parser.add_argument(
        "--encoder",
        type=Path,
        help="Explicit host-approved FFmpeg executable for optional video export.",
    )
    sub = parser.add_subparsers(dest="operation", required=True)
    parser.add_argument(
        "--speech-analyzer", type=Path, help="Host-selected local Rhubarb executable."
    )
    for operation in OPERATIONS:
        command = sub.add_parser(
            operation.replace("_", "-"),
            help=f"Run {operation}; arguments use the documented JSON schema.",
        )
        command.add_argument("--args", default="{}", help="Operation arguments as a JSON object.")
    batch = sub.add_parser(
        "batch", help="Execute a documented version-1 JSON workflow with result references."
    )
    batch.add_argument("workflow", help="Workspace-relative workflow JSON file (maximum 1 MiB).")
    args = parser.parse_args(argv)
    api = None
    try:

        def progress(done: int, total: int) -> None:
            """Keep optional render progress separate from the single machine-readable result."""
            if args.progress:
                print(json.dumps({"completed": done, "total": total}), file=sys.stderr, flush=True)

        api = RigoraAPI(
            args.root,
            asset_roots=tuple(args.asset_root),
            progress=progress,
            encoder=args.encoder,
            speech_analyzer=args.speech_analyzer,
        )
        if args.project:
            api.execute("project_open", {"path": args.project})
        if args.dry_run:
            api = RigoraAPI(
                api.root,
                asset_roots=api.asset_roots,
                document=api.document.fork(),
                progress=progress,
                encoder=api.encoder,
                speech_analyzer=api.speech_analyzer,
            )
            api._dry_run = True
        if args.operation == "batch":
            path = api.path(args.workflow)
            if path.stat().st_size > 1024 * 1024:
                raise AutomationError("invalid_workflow", "Workflow exceeds the 1 MiB size limit.")
            result = run_batch(api, _decode(path.read_bytes()), dry_run=False)
        else:
            if len(args.args) > 1024 * 1024:
                raise AutomationError("invalid_arguments", "Arguments exceed the 1 MiB size limit.")
            payload = _decode(args.args.encode("utf-8"))
            if not isinstance(payload, dict):
                raise AutomationError(
                    "invalid_arguments", "Operation arguments must be a JSON object."
                )
            result = api.execute(args.operation.replace("-", "_"), payload).to_dict()
        if args.save:
            api.execute(
                "project_save",
                {"path": args.save, "approve_overwrite": args.approve_overwrite},
            )
        if api.render_queue:
            previous = None
            while True:
                jobs = api.render_status()["jobs"]
                counters = [(j["job_id"], j["status"], j["completed"]) for j in jobs]
                if args.progress and counters != previous:
                    print(json.dumps({"render_jobs": jobs}), file=sys.stderr, flush=True)
                previous = counters
                if all(j["status"] in ("completed", "cancelled", "failed") for j in jobs):
                    break
                time.sleep(0.05)
            failed = next((j for j in jobs if j["status"] != "completed"), None)
            if failed:
                raise AutomationError(
                    "render_failed", failed["error"] or "Render did not complete."
                )
            result["render_jobs"] = jobs
            if args.operation == "render-submit":
                result["data"] = next(j for j in jobs if j["job_id"] == result["data"]["job_id"])
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except (ProjectError, ValueError, OSError, RecursionError) as error:
        code = (
            error.code
            if isinstance(error, AutomationError)
            else "invalid_json"
            if isinstance(error, (ProjectError, ValueError, RecursionError))
            else "io_error"
        )
        message = (
            str(error)
            if not isinstance(error, OSError)
            else "Cannot read or write the authorized workflow directory."
        )
        print(json.dumps({"ok": False, "error": {"code": code, "message": message}}))
        return 4 if code == "io_error" else 3
    except KeyboardInterrupt:
        print(
            json.dumps(
                {"ok": False, "error": {"code": "cancelled", "message": "Workflow cancelled."}}
            )
        )
        return 130
    finally:
        if api:
            api.close()


if __name__ == "__main__":
    raise SystemExit(automation_main())
