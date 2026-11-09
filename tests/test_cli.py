import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rigora import __version__


def run_process(*arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("RIGORA_LOG_LEVEL", None)
    environment.pop("DISPLAY", None)
    environment.pop("WAYLAND_DISPLAY", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )


def test_headless_startup_without_display() -> None:
    result = run_process("-m", "rigora", "--headless")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "name": "Rigora 2D",
        "version": __version__,
        "milestone": "plugin-sdk",
        "mode": "headless",
        "status": "ok",
    }
    assert len(result.stderr.splitlines()) == 2
    assert all(json.loads(line)["logger"] == "rigora" for line in result.stderr.splitlines())


def test_headless_never_attempts_qt_imports() -> None:
    result = run_process(
        "-c",
        """
import importlib.abc
import sys
class BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide', 'PyQt', 'shiboken')):
            raise AssertionError('Headless attempted Qt import: ' + fullname)
sys.meta_path.insert(0, BlockQt())
from rigora.interfaces.cli.main import headless_main
raise SystemExit(headless_main([]))
""",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mode"] == "headless"


@pytest.mark.parametrize("example_name", ["animation_example", "rigging_example"])
def test_headless_project_evaluation_matches_shared_service_without_qt(tmp_path, example_name):
    import animation_fixtures as samples

    from rigora.application_services.animation import AnimationSession
    from rigora.infrastructure.project_storage import ProjectStorage

    project = getattr(samples, example_name)()
    path = tmp_path / "animation.rigora"
    ProjectStorage().save(path, project, {})
    expected = AnimationSession(project.scenes[0]).evaluate(23.5).to_dict()
    result = run_process(
        "-c",
        """
import importlib.abc, sys
class BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide', 'PyQt', 'shiboken')):
            raise AssertionError('Evaluation attempted Qt import: ' + fullname)
sys.meta_path.insert(0, BlockQt())
from rigora.interfaces.cli.main import headless_main
raise SystemExit(headless_main(sys.argv[1:]))
""",
        "--evaluate",
        str(path),
        "--frame",
        "23.5",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
    invalid = run_process("-m", "rigora", "--evaluate", str(path), "--frame", "nan")
    assert invalid.returncode == 1 and "finite" in invalid.stderr


def test_imports_have_no_runtime_or_filesystem_side_effects(tmp_path: Path) -> None:
    result = run_process(
        "-c",
        """
import logging
import sys
before = logging.getLogger().handlers[:]
import rigora
import rigora.app.application
import rigora.app.bootstrap
import rigora.interfaces.cli.main
assert logging.getLogger().handlers == before
assert not any(name.startswith(('PySide', 'PyQt', 'shiboken')) for name in sys.modules)
""",
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["character-torso", "waving-arm"])
def test_headless_deformation_examples_need_no_qt(name):
    from rigora.application_services.documents import DocumentService

    path = Path(__file__).resolve().parents[1] / "examples" / f"deformation-{name}.rigora"
    document = DocumentService()
    document.open(path)
    expected = document.animation.evaluate(24).to_dict()
    result = run_process(
        "-c",
        """
import importlib.abc
import sys
class BlockQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('PySide', 'PyQt', 'shiboken')):
            raise AssertionError('Deformation evaluation attempted Qt import: ' + fullname)
sys.meta_path.insert(0, BlockQt())
from rigora.interfaces.cli.main import headless_main
raise SystemExit(headless_main(sys.argv[1:]))
""",
        "--evaluate",
        str(path),
        "--frame",
        "24",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected
    assert expected["meshes"] and not expected["warnings"]


@pytest.mark.parametrize("argument", ["--version", "--help"])
def test_information_commands_do_not_start_application(argument: str) -> None:
    result = run_process("-m", "rigora", argument)
    assert result.returncode == 0
    assert "Rigora 2D" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize("arguments", [("--bad",), ("--headless", "--log-level", "TRACE")])
def test_invalid_arguments_return_usage_error(arguments: tuple[str, ...]) -> None:
    result = run_process("-m", "rigora", *arguments)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "error:" in result.stderr


def test_missing_gui_dependency_has_installation_advice() -> None:
    result = run_process(
        "-c",
        """
import importlib.abc
import sys
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('PySide6'):
            raise ModuleNotFoundError('Qt intentionally absent', name=fullname)
sys.meta_path.insert(0, NoQt())
from rigora.interfaces.cli.main import main
raise SystemExit(main([]))
""",
    )
    assert result.returncode == 1
    assert "uv sync --locked --extra gui" in result.stderr
    assert "Traceback" not in result.stderr


def test_installed_metadata_and_console_scripts() -> None:
    assert importlib.metadata.version("rigora") == __version__
    scripts = {
        point.name: point
        for point in importlib.metadata.distribution("rigora").entry_points
        if point.group == "console_scripts"
    }
    assert scripts["rigora"].value == "rigora.interfaces.cli.main:main"
    assert scripts["rigora-headless"].value == "rigora.interfaces.cli.main:headless_main"
