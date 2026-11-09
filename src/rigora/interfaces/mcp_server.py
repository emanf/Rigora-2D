"""Optional official-SDK MCP tools over one authorized, offline-capable Rigora session."""

import argparse
import hmac
import inspect
import json
import os
import sys
import types
from collections.abc import Awaitable, Callable
from functools import reduce, wraps
from operator import or_
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

from rigora.api import AutomationError, RigoraAPI
from rigora.application_services.automation import OPERATIONS
from rigora.interfaces.cli.automation import run_batch


def strict_hint(hint: Any) -> Any:
    """Retain JSON schemas while refusing implicit coercion of approval flags and values."""
    from pydantic import StrictBool, StrictFloat, StrictInt, StrictStr

    scalar = {bool: StrictBool, int: StrictInt, float: StrictFloat, str: StrictStr}
    if hint in scalar:
        return scalar[hint]
    origin, args = get_origin(hint), get_args(hint)
    if origin is types.UnionType:
        return reduce(or_, (strict_hint(item) for item in args))
    if origin is list:
        return types.GenericAlias(list, strict_hint(args[0]))
    if origin is dict:
        return types.GenericAlias(dict, (strict_hint(args[0]), strict_hint(args[1])))
    return hint


def operation_tool(api: RigoraAPI, operation: str) -> Callable[..., dict[str, Any]]:
    """Expose the canonical method's concrete typed signature to the official SDK's
    schema builder.
    """
    method = getattr(api, operation)
    hints = {key: strict_hint(hint) for key, hint in get_type_hints(method).items()}

    @wraps(method)
    def tool(**arguments: Any) -> dict[str, Any]:
        """Execute one validated task with optional dry-run and revision preconditions."""
        dry_run = arguments.pop("dry_run", False)
        revision = arguments.pop("expected_revision", None)
        try:
            return {
                "ok": True,
                "result": api.execute(
                    operation, arguments, dry_run=dry_run, expected_revision=revision
                ).to_dict(),
            }
        except AutomationError as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}

    signature = inspect.signature(method)
    parameters = [p.replace(annotation=hints[p.name]) for p in signature.parameters.values()]
    parameters.extend(
        [
            inspect.Parameter(
                "dry_run",
                inspect.Parameter.KEYWORD_ONLY,
                default=False,
                annotation=strict_hint(bool),
            ),
            inspect.Parameter(
                "expected_revision",
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=str | None,
            ),
        ]
    )
    tool.__signature__ = signature.replace(parameters=parameters, return_annotation=dict[str, Any])  # type: ignore[attr-defined]
    tool.__annotations__ = {
        **hints,
        "dry_run": strict_hint(bool),
        "expected_revision": str | None,
        "return": dict[str, Any],
    }
    return tool


def create_server(api: RigoraAPI) -> Any:
    """Construct tools without starting a listener, GUI, shell, Python evaluator or cloud
    connection.
    """
    import anyio
    from mcp.server import MCPServer
    from mcp.server.mcpserver import Context
    from pydantic import StrictBool, StrictFloat, StrictInt

    server = MCPServer(
        "Rigora 2D",
        instructions=(
            "Use project_inspect and stable IDs. Authoring operations use ordinary undo. "
            "File writes stay inside the configured workspace. Dry runs do not write files. "
            "Overwrites require explicit approval and host permission. "
            "Inspect errors using the returned ok/error fields."
        ),
        log_level="WARNING",
    )
    for operation in OPERATIONS:
        if operation == "frame_render":
            continue
        server.tool(name=operation, structured_output=True)(operation_tool(api, operation))

    @server.tool(name="frame_render", structured_output=True)
    async def frame_render(
        path: str,
        ctx: Context[Any, Any],
        frame: StrictFloat = 0,
        frames: list[StrictFloat] | None = None,
        width: StrictInt = 1280,
        height: StrictInt = 720,
        bones: StrictBool = False,
        approve_overwrite: StrictBool = False,
        format: str = "auto",
        fps: StrictFloat | None = None,
        background: str | None = None,
        loop: StrictBool = True,
        columns: StrictInt = 8,
        dry_run: StrictBool = False,
        expected_revision: str | None = None,
    ) -> dict[str, Any]:
        """Render bounded previews on a worker and report per-frame MCP progress."""
        arguments = {
            "path": path,
            "frame": frame,
            "frames": frames,
            "width": width,
            "height": height,
            "bones": bones,
            "approve_overwrite": approve_overwrite,
            "format": format,
            "fps": fps,
            "background": background,
            "loop": loop,
            "columns": columns,
        }

        def run() -> dict[str, Any]:
            """Own the serialized session while forwarding worker progress to the request loop."""
            with api.lock:
                previous = api.progress

                def progress(completed: int, total: int) -> None:
                    """Send one bounded progress notification after each completed frame."""
                    anyio.from_thread.run(ctx.report_progress, completed, total)

                api.progress = progress
                try:
                    return {
                        "ok": True,
                        "result": api.execute(
                            "frame_render",
                            arguments,
                            dry_run=dry_run,
                            expected_revision=expected_revision,
                        ).to_dict(),
                    }
                except AutomationError as error:
                    return {"ok": False, "error": {"code": error.code, "message": str(error)}}
                finally:
                    api.progress = previous

        return await anyio.to_thread.run_sync(run)

    @server.tool(name="workflow_run", structured_output=True)
    def workflow_run(workflow: dict[str, Any], dry_run: StrictBool = True) -> dict[str, Any]:
        """Run a bounded inspectable JSON workflow; defaults to a no-write dry run."""
        try:
            with api.lock:
                return {"ok": True, "result": run_batch(api, workflow, dry_run=dry_run)}
        except AutomationError as error:
            return {"ok": False, "error": {"code": error.code, "message": str(error)}}

    return server


class AuthorizedHTTP:
    """Protect explicitly enabled HTTP transport with a host-owned bearer token."""

    def __init__(self, app: Any, token: str) -> None:
        """Retain the ASGI application and token without exposing either in tool results."""
        if len(token) < 32:
            raise ValueError("HTTP mode requires a token of at least 32 characters.")
        self.app, self.token = app, token.encode()

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Reject unauthorized HTTP requests before any MCP session or file operation is created."""
        if scope["type"] == "http":
            supplied = next(
                (
                    value
                    for key, value in scope.get("headers", [])
                    if key.lower() == b"authorization"
                ),
                b"",
            )
            valid = (
                supplied.startswith(b"Bearer ")
                and len(supplied) <= 4096
                and hmac.compare_digest(supplied[7:], self.token)
            )
            if not valid:
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send(
                    {"type": "http.response.body", "body": b'{"error":"authorization_required"}'}
                )
                return
        await self.app(scope, receive, send)


def http_app(
    server: Any,
    token: str,
    *,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> AuthorizedHTTP:
    """Keep bearer authentication and explicit host/origin validation on every HTTP listener."""
    from mcp.server.transport_security import TransportSecuritySettings

    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts or ["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=allowed_origins
        or ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    )
    return AuthorizedHTTP(
        server.streamable_http_app(
            transport_security=security,
            max_sessions=8,
            max_request_body_size=2 * 1024 * 1024,
        ),
        token,
    )


def main(argv: list[str] | None = None) -> int:
    """Run local stdio by default; HTTP, remote binding and overwrites require host opt-in."""
    parser = argparse.ArgumentParser(
        prog="rigora-mcp",
        description="Official-SDK MCP server using Rigora's canonical application services.",
    )
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="Authorized project and output directory."
    )
    parser.add_argument(
        "--asset-root",
        type=Path,
        action="append",
        default=[],
        help="Additional explicitly authorized read-only asset directory.",
    )
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="Allow clients to request explicitly approved overwrites.",
    )
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument(
        "--speech-analyzer",
        type=Path,
        help="Host-selected local Rhubarb executable; never client-selected.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--encoder",
        type=Path,
        help="Host-approved FFmpeg executable for optional video export; never client-selected.",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help="Permitted HTTP Host header; required for remote binding (repeatable).",
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help="Permitted browser Origin header for HTTP (repeatable).",
    )
    parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="Permit non-loopback HTTP binding; configure HTTPS at a reverse proxy.",
    )
    parser.add_argument(
        "--token-env",
        default="RIGORA_MCP_TOKEN",
        help="Environment variable holding the HTTP bearer token; value is never logged.",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("Port must be between 1 and 65535.")
    if (
        args.transport == "streamable-http"
        and args.host not in ("127.0.0.1", "localhost", "::1")
        and (not args.allow_remote or not args.allowed_host)
    ):
        parser.error("Non-loopback HTTP binding requires --allow-remote and --allowed-host.")
    api = None
    try:
        api = RigoraAPI(
            args.root,
            asset_roots=tuple(args.asset_root),
            allow_overwrite=args.allow_overwrite,
            encoder=args.encoder,
            speech_analyzer=args.speech_analyzer,
        )
        server = create_server(api)
        if args.transport == "stdio":
            server.run(transport="stdio")
        else:
            import uvicorn

            app = http_app(
                server,
                os.environ.get(args.token_env, ""),
                allowed_hosts=args.allowed_host or None,
                allowed_origins=args.allowed_origin or None,
            )
            uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return 0
    except ModuleNotFoundError:
        print(
            "MCP dependencies are missing; install rigora[mcp] or use uv sync --extra mcp.",
            file=sys.stderr,
        )
        return 1
    except (AutomationError, OSError, ValueError) as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(error)
                    if not isinstance(error, OSError)
                    else "Cannot access the authorized workspace.",
                }
            ),
            file=sys.stderr,
        )
        return 3
    except KeyboardInterrupt:
        return 130
    finally:
        if api:
            api.close()


if __name__ == "__main__":
    raise SystemExit(main())
