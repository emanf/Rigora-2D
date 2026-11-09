"""Small fault-tolerant local UI preferences, independent of Qt."""

import json
import os
from pathlib import Path
from typing import Any

from rigora.infrastructure.project_storage import _atomic_bytes


def default_preferences_path() -> Path:
    """Resolve an explicit override or a platform-local workspace preference location."""
    override = os.environ.get("RIGORA_PREFERENCES_PATH")
    if override:
        return Path(override)
    root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME")
    return (Path(root) if root else Path.home() / ".config") / "Rigora" / "workspace.json"


class PreferencesStore:
    """Fault-tolerant local UI preferences independent of project data and Qt widgets."""

    def __init__(self, path: Path | None = None) -> None:
        """Load bounded optional preferences and recover usable defaults from invalid values."""
        self.path = path if path is not None else default_preferences_path()
        self.data: dict[str, Any] = {"theme": "dark", "recent": []}
        self.warning: str | None = None
        try:
            if self.path.exists():
                if self.path.stat().st_size > 262144:
                    raise ValueError("Preference file is too large.")
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict):
                    raise ValueError("Preference file is not an object.")
                self.data.update(loaded)
        except (OSError, ValueError, RecursionError) as error:
            self.warning = f"Workspace preferences could not be read: {error}"
        if self.data.get("theme") not in ("dark", "light"):
            self.data["theme"] = "dark"
        undo_limit = self.data.get("undo_limit", 500)
        self.data["undo_limit"] = (
            undo_limit if type(undo_limit) is int and 1 <= undo_limit <= 10000 else 500
        )
        recent = self.data.get("recent")
        if not isinstance(recent, list):
            recent = []
        self.data["recent"] = [v for v in recent if isinstance(v, str) and len(v) <= 4096][:10]

    @property
    def recent(self) -> list[str]:
        """Return a copy of recent paths so callers cannot mutate stored ordering indirectly."""
        return list(self.data["recent"])

    def add_recent(self, path: Path) -> None:
        """Move a project path to the front of the bounded, deduplicated recent list."""
        value = str(path)
        self.data["recent"] = [value, *(item for item in self.recent if item != value)][:10]

    def save(self) -> str | None:
        """Publish preference JSON atomically and return a recoverable warning on failure."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self.data, indent=2, allow_nan=False).encode("utf-8")
            _atomic_bytes(self.path, payload)
            self.warning = None
        except (OSError, ValueError, TypeError) as error:
            self.warning = f"Workspace preferences could not be saved: {error}"
        return self.warning
