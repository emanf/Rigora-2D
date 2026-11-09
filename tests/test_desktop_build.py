"""Check native bundle routing and failure propagation without installing or launching a GUI."""

import importlib.util
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from rigora.infrastructure.processes import module_command
from rigora.resources import application_root, asset_path

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name: str):
    """Load a build-only module by path without adding tooling to the application package."""
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_workers_use_frozen_console_peer_and_source_python(monkeypatch):
    """Ensure Windows workers have pipes while ordinary installed Python commands stay intact."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(ROOT / "dist" / "Rigora.exe"))
    assert module_command("rigora.sdk.worker")[0] == str(ROOT / "dist" / "RigoraCLI.exe")
    monkeypatch.setattr(sys, "frozen", False)
    assert module_command("rigora.sdk.worker") == [sys.executable, "-m", "rigora.sdk.worker"]


@pytest.mark.parametrize("target", ["win32", "linux", "darwin"])
def test_native_assets_resolve_from_public_folder_without_source_fallback(
    tmp_path, monkeypatch, target
):
    """Native bundles use public data folders from any cwd and cannot mask missing assets."""
    root = tmp_path / "app with spaces"
    executable = root / "Rigora.exe"
    if target == "darwin":
        executable = root / "Rigora.app" / "Contents" / "MacOS" / "Rigora"
        root = executable.parent.parent / "Resources"
    assets = root / "assets" / "shapes"
    assets.mkdir(parents=True)
    bone = assets / "bone.svg"
    bone.write_text("<svg/>", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", target)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.chdir(tmp_path)
    assert application_root() == root
    assert asset_path("shapes/bone.svg") == bone
    with pytest.raises(FileNotFoundError):
        asset_path("library/starter.rigpack")
    for name in ("../outside.svg", "C:\\outside.svg", "/outside.svg", "..\\outside.svg"):
        with pytest.raises(ValueError):
            asset_path(name)


def test_frozen_entry_forwards_worker_args_and_exit_code(monkeypatch):
    """Forward module arguments and spaced paths exactly without opening the desktop."""
    entry = load_tool("frozen_entry")
    args = ["--root", str(ROOT / "folder with spaces")]
    monkeypatch.setattr(sys, "argv", ["RigoraCLI", "-m", "rigora.interfaces.mcp_server", *args])
    called = []

    def invoke():
        """Capture the adapter's argv and return a meaningful nonzero status."""
        called.append(sys.argv[:])
        return 7

    monkeypatch.setattr(entry.importlib, "import_module", lambda _: SimpleNamespace(main=invoke))
    assert entry.main() == 7
    assert called == [["rigora.interfaces.mcp_server", *args]]
    monkeypatch.setattr(sys, "argv", ["RigoraCLI", "-m", "arbitrary.module"])
    assert entry.main() == 2


def test_build_driver_propagates_failure_and_resolves_native_paths(monkeypatch, capsys):
    """Refuse success on failed prerequisites and resolve native output locations."""
    builder = load_tool("build_app")
    output = ROOT / "dist" / "test"
    assert builder.executable_path(output, "windows") == output / "Rigora" / "Rigora.exe"
    assert builder.executable_path(output, "linux") == output / "Rigora" / "Rigora"
    assert builder.executable_path(output, "macos") == output / "Rigora.app/Contents/MacOS/Rigora"
    monkeypatch.setenv("PATH", str(ROOT / "unrelated-app-dlls"))
    assert "unrelated-app-dlls" not in builder.freezing_path(Path(sys.executable), "windows")

    def fail(*args, **kwargs):
        """Model an unavailable prerequisite before any build outputs are written."""
        raise RuntimeError("test prerequisite missing")

    monkeypatch.setattr(builder, "build", fail)
    monkeypatch.setattr(sys, "argv", ["build_app.py", "--uv", "uv", "--no-pause"])
    assert builder.main() == 1
    assert "test prerequisite missing" in capsys.readouterr().err
    monkeypatch.setattr(builder.platform, "system", lambda: "Unsupported")
    with pytest.raises(RuntimeError, match="Build on"):
        builder.native_platform()


def test_batch_reports_combine_only_after_all_tests_pass(tmp_path, monkeypatch):
    """Bounded test processes retain their case results and cannot hide a failed batch."""
    builder = load_tool("build_app")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    tests = tmp_path / "tests"
    tests.mkdir()
    for index in range(45):
        (tests / f"test_{index:02}.py").write_text("", encoding="utf-8")
    output = tmp_path / "reports"
    output.mkdir()
    batches = []

    def run(*command):
        """Emulate successful test processes while retaining their actual batch boundaries."""
        files = [value for value in command if value.endswith(".py")]
        batches.append(files)
        report = Path(command[-1].removeprefix("--junitxml="))
        report.write_text(
            '<testsuites><testsuite tests="1" errors="0" failures="0">'
            f'<testcase name="batch-{len(batches)}"/></testsuite></testsuites>',
            encoding="utf-8",
        )

    builder.check_tests(Path(sys.executable), output, run)
    assert [len(batch) for batch in batches] == [20, 20, 5]
    assert {case.get("name") for case in ET.parse(output / "tests.xml").iter("testcase")} == {
        "batch-1",
        "batch-2",
        "batch-3",
    }
    failed = tmp_path / "failed"
    failed.mkdir()

    def fail(*command):
        """Return a genuine process failure before a combined passing report can be published."""
        raise subprocess.CalledProcessError(1, command)

    with pytest.raises(subprocess.CalledProcessError):
        builder.check_tests(Path(sys.executable), failed, fail)
    assert not (failed / "tests.xml").exists()


def test_rebuild_cleanup_removes_generated_outputs_and_preserves_source(tmp_path, monkeypatch):
    """Cleanup reclaims old environments/bundles while retaining development and authored data."""
    builder = load_tool("build_app")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    generated = ("build/desktop/old/environment/python", "dist/windows-old/Rigora.exe")
    retained = (
        ".venv/python",
        "assets/art.svg",
        "plugins/tool.py",
        "work.rigora",
        "build/test-results.xml",
    )
    for relative in (*generated, *retained):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")
    builder.remove_build_outputs("build/desktop", "dist")
    assert all(not (tmp_path / relative).exists() for relative in generated)
    assert all((tmp_path / relative).is_file() for relative in retained)
    for forbidden in (".", "assets", ".venv", "../outside"):
        with pytest.raises(RuntimeError, match="Refusing cleanup"):
            builder.remove_build_outputs(forbidden)


def test_build_cleans_before_checking_available_space(tmp_path, monkeypatch):
    """A full disk can recover old build space before the free-space prerequisite runs."""
    builder = load_tool("build_app")
    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "native_platform", lambda: "linux")
    monkeypatch.setattr(builder.os, "nice", lambda _: None, raising=False)
    monkeypatch.setattr(builder, "install_linux_tools", lambda: None)
    (tmp_path / "build/desktop/old").mkdir(parents=True)
    (tmp_path / "dist/old").mkdir(parents=True)

    def disk_usage(path):
        assert not (tmp_path / "build/desktop").exists()
        assert not (tmp_path / "dist").exists()
        raise RuntimeError("cleanup checked; no compilation requested")

    monkeypatch.setattr(builder.shutil, "disk_usage", disk_usage)
    with pytest.raises(RuntimeError, match="cleanup checked"):
        builder.build("uv")


def test_cleanup_rejects_linked_output_before_removing_anything(tmp_path, monkeypatch):
    """An output symlink cannot redirect recursive cleanup into another directory."""
    builder = load_tool("build_app")
    project, shared = tmp_path / "project", tmp_path / "shared"
    (project / "build/desktop/old").mkdir(parents=True)
    shared.mkdir()
    marker = shared / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        (project / "dist").symlink_to(shared, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            pytest.skip("Creating directory symlinks is unavailable on this host")
        import _winapi

        _winapi.CreateJunction(str(shared), str(project / "dist"))
    monkeypatch.setattr(builder, "ROOT", project)
    with pytest.raises(RuntimeError, match="Refusing cleanup"):
        builder.remove_build_outputs("build/desktop", "dist")
    assert (project / "build/desktop/old").exists() and marker.is_file()
