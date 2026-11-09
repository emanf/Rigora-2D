"""Reversible field deltas and atomic compound authoring commands."""

from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from types import MappingProxyType
from typing import Any, Protocol

from rigora.domain.project import Project, ProjectError, Scene


def _freeze_change(value: Any) -> Any:
    """Freeze delta containers while sharing already immutable authoring records."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_change(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_change(item) for item in value)
    return value


class Command(Protocol):
    """Contract for a validated mutation that can be reversed against its result."""

    @property
    def label(self) -> str:
        """Return the human-readable history entry for this action."""
        ...

    def apply(self, project: Project) -> Project:
        """Return the validated result without modifying the input model."""
        ...

    def undo(self, project: Project) -> Project:
        """Return the prior state or fail if the command conflicts with current data."""
        ...


@dataclass(frozen=True)
class ProjectPatch:
    """Reversible immutable field deltas that preserve the persistent project identity."""

    label: str
    before: Mapping[str, Any]
    after: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Freeze delta containers and keep persistent project identity immutable."""
        if set(self.before) != set(self.after) or "id" in self.after:
            raise ProjectError("Project deltas must preserve identity and matching field sets.")
        if not set(self.after) <= {item.name for item in fields(Project)}:
            raise ProjectError("Project delta contains an unknown field.")
        object.__setattr__(self, "before", _freeze_change(self.before))
        object.__setattr__(self, "after", _freeze_change(self.after))

    def _change(
        self, project: Project, expected: Mapping[str, Any], values: Mapping[str, Any]
    ) -> Project:
        """Check expected field values before returning a fully validated replacement."""
        if any(getattr(project, key) != value for key, value in expected.items()):
            raise ProjectError("Command conflicts with the current project state.")
        return replace(project, **values)

    def apply(self, project: Project) -> Project:
        """Apply the forward delta without copying unchanged model records."""
        return self._change(project, self.before, self.after)

    def undo(self, project: Project) -> Project:
        """Apply the inverse delta after checking the command result still matches."""
        return self._change(project, self.after, self.before)


@dataclass(frozen=True)
class ScenePatch:
    """Reversible field deltas addressing one scene by its stable UUID."""

    label: str
    scene_id: str
    before: Mapping[str, Any]
    after: Mapping[str, Any]

    def __post_init__(self) -> None:
        """Freeze changed-field containers without copying immutable scene records."""
        if set(self.before) != set(self.after) or "id" in self.after:
            raise ProjectError("Scene deltas must preserve identity and matching field sets.")
        if not set(self.after) <= {item.name for item in fields(Scene)}:
            raise ProjectError("Scene delta contains an unknown field.")
        object.__setattr__(self, "before", _freeze_change(self.before))
        object.__setattr__(self, "after", _freeze_change(self.after))

    def _change(
        self, project: Project, expected: Mapping[str, Any], values: Mapping[str, Any]
    ) -> Project:
        """Replace one matching scene and revalidate the complete project graph."""
        scene = next((s for s in project.scenes if s.id == self.scene_id), None)
        if scene is None or any(getattr(scene, key) != value for key, value in expected.items()):
            raise ProjectError("Command conflicts with the current scene state.")
        changed = replace(scene, **values)
        return replace(
            project, scenes=tuple(changed if s.id == scene.id else s for s in project.scenes)
        )

    def apply(self, project: Project) -> Project:
        """Apply changed scene fields while sharing unaffected scenes."""
        return self._change(project, self.before, self.after)

    def undo(self, project: Project) -> Project:
        """Restore prior scene fields or reject a conflicting document state."""
        return self._change(project, self.after, self.before)


@dataclass(frozen=True)
class PreparedProjectChange:
    """Reversible validated revisions built off-thread, with exact-state conflict checks.

    Both revisions have already passed Project validation. Publishing or undoing
    shares their immutable records instead of replaying a long import transaction.
    """

    label: str
    before: Project
    after: Project

    def __post_init__(self) -> None:
        """Require actual validated projects with the same persistent document identity."""
        if (
            not isinstance(self.before, Project)
            or not isinstance(self.after, Project)
            or self.before.id != self.after.id
        ):
            raise ProjectError("Prepared changes must retain the project identity.")

    def apply(self, project: Project) -> Project:
        """Publish only onto the revision from which this result was prepared."""
        if project is not self.before and project != self.before:
            raise ProjectError("Prepared change conflicts with the current project state.")
        return self.after

    def undo(self, project: Project) -> Project:
        """Restore the original revision without losing later conflicting changes."""
        if project is not self.after and project != self.after:
            raise ProjectError("Prepared undo conflicts with the current project state.")
        return self.before


@dataclass(frozen=True)
class CompoundCommand:
    """Ordered set of reversible actions represented by one history entry."""

    label: str
    commands: tuple[Command, ...]

    def apply(self, project: Project) -> Project:
        """Apply all constituent actions in order to immutable intermediate models."""
        for command in self.commands:
            project = command.apply(project)
        return project

    def undo(self, project: Project) -> Project:
        """Reverse constituent actions in the opposite order."""
        for command in reversed(self.commands):
            project = command.undo(project)
        return project


class CommandHistory:
    """Independent undo and redo stacks for one document session."""

    def __init__(self, limit: int = 500) -> None:
        """Own a bounded number of reversible edits; compound operations count as one."""
        self.undo_stack: list[Command] = []
        self.redo_stack: list[Command] = []
        self.set_limit(limit)

    def set_limit(self, limit: int) -> None:
        """Set a 1–10,000 edit retention budget without invalidating newer Undo/Redo entries."""
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise ProjectError("Undo history must retain between 1 and 10,000 edits.")
        self.limit = limit
        del self.undo_stack[: max(0, len(self.undo_stack) - limit)]
        available = max(0, limit - len(self.undo_stack))
        del self.redo_stack[: max(0, len(self.redo_stack) - available)]

    def record(self, command: Command) -> None:
        """Append a successful action and invalidate the abandoned redo branch."""
        self.undo_stack.append(command)
        self.redo_stack.clear()
        del self.undo_stack[: max(0, len(self.undo_stack) - self.limit)]

    def undo(self, project: Project) -> Project:
        """Move the last action to redo only after its inverse succeeds."""
        if not self.undo_stack:
            return project
        command = self.undo_stack[-1]
        changed = command.undo(project)
        self.undo_stack.pop()
        self.redo_stack.append(command)
        return changed

    def redo(self, project: Project) -> Project:
        """Move a reverted action to undo only after its forward mutation succeeds."""
        if not self.redo_stack:
            return project
        command = self.redo_stack[-1]
        changed = command.apply(project)
        self.redo_stack.pop()
        self.undo_stack.append(command)
        return changed
