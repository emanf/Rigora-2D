"""Executable extension contracts, live lifecycle and bounded installer behavior without Qt."""

import json
import zipfile
from pathlib import Path

import pytest

from rigora.application_services.documents import DocumentService
from rigora.application_services.plugin_commands import PluginCommandService
from rigora.application_services.plugins import PluginManager
from rigora.domain.project import ProjectError
from rigora.infrastructure.plugin_archives import read_plugin_archive
from rigora.infrastructure.preferences import PreferencesStore
from rigora.sdk.scaffold import generate_plugin

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "plugins" / "studio_tools"
KEY = "org.rigora.studio_tools"


def test_original_api1_tool_package_remains_executable(tmp_path):
    """Load the original API 1 package unchanged and execute its tool through the new service."""
    package = ROOT / "examples/plugins/tool/rigora_org_rigora_example_tool"
    manager = PluginManager(PreferencesStore(tmp_path / "settings.json"))
    manager.discover((package,), installed=False, allowed_roots=(package,))
    key = "org.rigora.example.tool"
    assert manager.states[key].manifest.api_version == "1"
    manager.trust(key)
    manager.enable(key)
    document = DocumentService()
    document.new()
    PluginCommandService(manager).execute(
        key + ".stamp", document, {"phase": "press", "x": 20, "y": 30}
    )
    assert len(document.project.scenes[0].skeletons[0].bones) == 2
    assert len(document.history.undo_stack) == 1
    manager.shutdown()


def test_live_registry_refresh_preserves_context_and_canonical_undo(tmp_path):
    """Run integrated tools headlessly and retain unchanged activations on refresh."""
    plugins = PluginManager(PreferencesStore(tmp_path / "settings.json"))
    plugins.discover((STUDIO,), installed=False, allowed_roots=(STUDIO,))
    plugins.trust(KEY)
    plugins.enable(KEY)
    context = plugins.contexts[KEY]
    commands = PluginCommandService(plugins)
    doc = DocumentService()
    doc.new()
    before = doc.project
    result = commands.execute(KEY + ".chain", doc, {"count": 4})
    assert len(result["bone_ids"]) == 4
    bones = doc.project.scenes[0].skeletons[0].bones
    assert bones[0].parent_id is None
    assert [b.parent_id for b in bones[1:]] == [b.id for b in bones[:-1]]
    assert len(doc.history.undo_stack) == 1
    doc.undo()
    assert doc.project == before
    plugins.discover((STUDIO,), installed=False, allowed_roots=(STUDIO,))
    plugins.restore()
    assert plugins.contexts[KEY] is context
    with pytest.raises(ProjectError, match="integer"):
        commands.execute(KEY + ".chain", doc, {"count": 0})
    assert len(commands.execute(KEY + ".chain", doc, {"count": 1})["bone_ids"]) == 1
    doc.undo()
    assert doc.project == before
    context.action(
        KEY + ".live", "Live action", lambda request: "live", placements=("menu:Rig/Live",)
    )
    assert commands.execute(KEY + ".live", doc, {}) == "live"
    context.remove(KEY + ".live")
    with pytest.raises(ProjectError, match="not active"):
        commands.execute(KEY + ".live", doc, {})
    with pytest.raises(ProjectError, match="unavailable"):
        commands.execute(KEY + ".chain", None, {})
    assert doc.project == before
    plugins.shutdown()


def test_zip_installs_metadata_only_and_refuses_overwrite(tmp_path, monkeypatch):
    """Installing a package never imports its code, even before the owner trusts it."""
    monkeypatch.setattr("rigora.application_services.plugins.application_root", lambda: tmp_path)
    package = generate_plugin(tmp_path / "source", "org.zip.example")
    marker = tmp_path / "executed.txt"
    (package / "__init__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        + (package / "__init__.py").read_text(),
        encoding="utf-8",
    )
    archive = tmp_path / "plugin.zip"
    with zipfile.ZipFile(archive, "w") as target:
        for path in package.iterdir():
            target.write(path, package.name + "/" + path.name)
    manager = PluginManager(PreferencesStore(tmp_path / "profile" / "settings.json"))
    installed = manager.install_archive(archive)
    manager.discover(installed=False)
    assert not marker.exists() and not manager.contexts
    assert manager.states["org.zip.example"].root == installed
    with pytest.raises(ProjectError, match="already exists"):
        manager.install_archive(archive)
    assert json.loads((installed / "rigora-plugin.json").read_text())["id"] == "org.zip.example"
    manager.shutdown()


@pytest.mark.parametrize(
    "unsafe",
    ["../escape.py", "example/../../escape.py", "C:/escape.py", "example/NAME.py", "other/code.py"],
)
def test_zip_rejects_path_escape_case_aliases_and_multiple_roots(tmp_path, unsafe):
    """Reject ambiguous portable paths before any package can be installed."""
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("example/rigora-plugin.json", "{}")
        target.writestr("example/name.py", "")
        target.writestr(unsafe, "")
    with pytest.raises(ProjectError):
        read_plugin_archive(archive)
