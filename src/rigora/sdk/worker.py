"""Private JSON worker for trusted plugin jobs with process-level failure separation."""

import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

from rigora.application_services.documents import DocumentService
from rigora.application_services.plugins import PluginManager, inspect_plugin
from rigora.domain.project import Project, ProjectError
from rigora.infrastructure.preferences import PreferencesStore
from rigora.sdk.api import PluginRequest


def main() -> int:
    """Verify parent-approved fingerprints, invoke one data callback and emit bounded JSON."""
    raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        print(json.dumps({"error": "Plugin request exceeds 8 MiB."}))
        return 1
    try:
        payload = json.loads(raw)
        with tempfile.TemporaryDirectory(prefix="rigora-plugin-worker-") as temporary:
            preferences = PreferencesStore(Path(temporary) / "worker.json")
            manager = PluginManager(preferences)
            trust = {}
            for descriptor in payload["plugins"]:
                state = inspect_plugin(
                    Path(descriptor["root"]) / "rigora-plugin.json",
                    installed=descriptor["installed"],
                )
                if state.fingerprint != descriptor["fingerprint"]:
                    raise ProjectError("Plugin source changed before the isolated job started.")
                manager.states[state.manifest.id] = state
                trust[state.manifest.id] = state.fingerprint
            preferences.data["plugin_trust"] = trust
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    manager.enable(payload["plugin_id"], persist=False)
                    document = None
                    if payload.get("project") is not None:
                        document = DocumentService()
                        document.project = Project.from_dict(payload["project"])
                        manager.attach(document)
                    result = manager.invoke(
                        payload["key"],
                        PluginRequest(
                            document, payload["arguments"], state=payload.get("state", {})
                        ),
                    )
                    encoded = json.dumps({"result": result}, allow_nan=False)
                if len(encoded.encode("utf-8")) > 4 * 1024 * 1024:
                    raise ProjectError("Plugin result exceeds 4 MiB.")
            finally:
                with contextlib.redirect_stdout(io.StringIO()):
                    manager.shutdown()
        print(encoded)
        return 0
    except (Exception, SystemExit) as error:
        print(json.dumps({"error": f"{type(error).__name__}: {str(error)[:2000]}"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
