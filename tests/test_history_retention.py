"""History pruning retains valid transitions and never changes the saved-state baseline."""

import pytest

from rigora.application_services.commands import CommandHistory, ProjectPatch
from rigora.application_services.documents import DocumentService
from rigora.domain.project import Project, ProjectError


def test_bounded_history_roundtrip_and_reduction_preserve_nearest_redo():
    history = CommandHistory(3)
    project = Project()
    for index in range(6):
        command = ProjectPatch("Rename", {"name": project.name}, {"name": str(index)})
        project = command.apply(project)
        history.record(command)
    assert len(history.undo_stack) == 3
    project = history.undo(history.undo(project))
    assert project.name == "3"
    history.set_limit(2)
    assert len(history.redo_stack) == 1
    assert history.redo(project).name == "4"


def test_document_retains_history_policy_after_new_and_open_and_pruning_stays_dirty(tmp_path):
    doc = DocumentService()
    doc.new()
    doc.history.set_limit(2)
    path = tmp_path / "saved.rigora"
    doc.save(path)
    for index in range(4):
        doc.execute(ProjectPatch("Rename", {"name": doc.project.name}, {"name": str(index)}))
    doc.undo()
    doc.undo()
    assert doc.dirty and not doc.can_undo
    doc.open(path)
    assert doc.history.limit == 2 and not doc.dirty
    doc.new()
    assert doc.history.limit == 2


@pytest.mark.parametrize("limit", (0, -1, True, 10001))
def test_invalid_retention_limit_is_rejected(limit):
    with pytest.raises(ProjectError):
        CommandHistory(limit)
