"""Optional subprocess execution for trusted data-only plugin jobs; not an OS sandbox."""

import json
import os
import subprocess
from typing import TYPE_CHECKING, Any

from rigora.domain.project import ProjectError
from rigora.domain.validation import json_copy
from rigora.infrastructure.processes import module_command
from rigora.sdk.api import PluginRequest

if TYPE_CHECKING:
    from rigora.application_services.plugins import PluginManager


def run_isolated(
    manager: "PluginManager", key: str, request: PluginRequest, *, timeout: float = 30
) -> Any:
    """Run a trusted numeric job with a project snapshot; child mutations are never published."""
    contribution = next((c for c in manager.contributions() if c.id == key), None)
    if contribution is None or contribution.kind not in (
        "batch_jobs",
        "validators",
        "generators",
        "services",
    ):
        raise ProjectError(
            "Subprocess execution supports data-only jobs, validators, generators and services."
        )
    if not 0 < timeout <= 300:
        raise ProjectError("Plugin job timeout must be between zero and 300 seconds.")
    order: list[str] = []
    manager._order(contribution.plugin_id, set(), order)
    document = request.document
    if (
        document is not None
        and "project.read" not in manager.states[contribution.plugin_id].manifest.permissions
    ):
        raise ProjectError("Plugin did not declare project.read permission.")
    payload = {
        "key": key,
        "plugin_id": contribution.plugin_id,
        "arguments": json_copy(request.arguments),
        "state": json_copy(request.state),
        "project": document.project.to_dict() if document and document.project else None,
        "plugins": [
            {
                "root": str(manager.states[k].root),
                "fingerprint": manager.states[k].fingerprint,
                "installed": manager.states[k].installed,
            }
            for k in order
        ],
    }
    encoded = json.dumps(payload, allow_nan=False).encode("utf-8")
    if len(encoded) > 8 * 1024 * 1024:
        raise ProjectError("Isolated plugin requests must be smaller than 8 MiB.")
    try:
        result = subprocess.run(
            module_command("rigora.sdk.worker"),
            input=encoded,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        manager.report(contribution.plugin_id, "Isolated job timed out and was terminated.")
        raise ProjectError("The isolated plugin job timed out and was terminated.") from error
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ProjectError("Isolated plugin output exceeds 4 MiB.")
    try:
        output = json.loads(result.stdout)
        if not isinstance(output, dict):
            raise ProjectError("Plugin worker returned an invalid response object.")
        if result.returncode or "error" in output:
            raise ProjectError(str(output.get("error", "Plugin worker failed.")))
        return json_copy(output["result"])
    except (ValueError, KeyError, TypeError) as error:
        raise ProjectError(f"Invalid plugin worker response: {error}") from error
