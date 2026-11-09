# Native one-folder bundles keep replaceable assets alongside the embedded Python runtime.
import hashlib
import json
import shutil
import sys
from importlib.metadata import version
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
asset_files = [
    path
    for path in sorted((root / "assets").rglob("*"))
    if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo")
]
plugin_files = [
    path
    for path in sorted((root / "plugins").rglob("*"))
    if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo")
]
datas = (
    [
        (str(path), "assets/" + path.parent.relative_to(root / "assets").as_posix())
        for path in asset_files
    ]
    if sys.platform == "darwin"
    else []
)
if sys.platform == "darwin":
    datas.extend(
        (str(path), "plugins/" + path.parent.relative_to(root / "plugins").as_posix())
        for path in plugin_files
    )
inventory = Path(CONF["workpath"]) / "asset-inventory.json"
inventory.parent.mkdir(parents=True, exist_ok=True)
inventory.write_text(
    json.dumps(
        {
            path.relative_to(root / "assets").as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in asset_files
        }
    ),
    encoding="utf-8",
)
datas.append((str(inventory), "."))
binaries = []
hidden = collect_submodules("rigora")
for package in ("mediapipe", "resvg_py", "pypdfium2", "psd_tools", "pocketsphinx", "rtmlib", "onnxruntime", "cv2"):
    package_data, package_binaries, package_hidden = collect_all(
        package,
        include_py_files=False,
        filter_submodules=lambda name: not ({"test", "tests"} & set(name.split("."))),
        exclude_datas=["**/test/**", "**/tests/**"],
    )
    datas += package_data
    binaries += package_binaries
    hidden += package_hidden
for package in (
    "rigora",
    "PySide6",
    "mcp",
    "Pillow",
    "shapely",
    "resvg-py",
    "psd-tools",
    "pypdfium2",
    "mediapipe",
    "pocketsphinx",
    "rtmlib",
    "onnxruntime",
):
    datas += copy_metadata(package, recursive=True)

analysis = Analysis(
    [str(root / "tools" / "frozen_entry.py")],
    pathex=[str(root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["PyQt5", "PyQt6", "PySide2", "pytest", "mypy", "ruff", "tkinter", "IPython"],
    noarchive=False,
)
# Installer records describe the build environment, not the frozen application's files.
# Keep version/entry-point metadata and licenses used by dependencies and plugin discovery.
analysis.datas = [
    entry
    for entry in analysis.datas
    if not (
        any(part.endswith(".dist-info") for part in Path(entry[0]).parts)
        and Path(entry[0]).name
        in {"RECORD", "INSTALLER", "REQUESTED", "direct_url.json", "uv_cache.json", "uv_build.json"}
        or entry[0]
        .replace("\\", "/")
        .startswith(("matplotlib/mpl-data/sample_data/", "matplotlib/mpl-data/plot_directive/"))
    )
]
archive = PYZ(analysis.pure)
application = EXE(
    archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="Rigora",
    console=sys.platform == "linux",
    icon=str(root / "assets" / "icons" / "app" / "rigora.png"),
    upx=False,
)
executables = [application]
if sys.platform == "win32":
    # Windowed bootloaders have no standard streams; MCP and numeric workers need a console peer.
    executables.append(
        EXE(
            archive,
            analysis.scripts,
            [],
            exclude_binaries=True,
            name="RigoraCLI",
            console=True,
            icon=str(root / "assets" / "icons" / "app" / "rigora.png"),
            upx=False,
        )
    )
folder = COLLECT(*executables, analysis.binaries, analysis.datas, name="Rigora", upx=False)
if sys.platform != "darwin":
    # PyInstaller collects data under _internal; public editable data belongs beside the EXE.
    destination = Path(folder.name)
    for path in asset_files:
        target = destination / "assets" / path.relative_to(root / "assets")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    for path in plugin_files:
        target = destination / "plugins" / path.relative_to(root / "plugins")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
if sys.platform == "darwin":
    application_bundle = BUNDLE(
        folder,
        name="Rigora.app",
        version=version("rigora"),
        bundle_identifier="org.rigora.desktop",
        icon=str(root / "assets" / "icons" / "app" / "rigora.png"),
        info_plist={
            "NSHighResolutionCapable": True,
            "NSCameraUsageDescription": "Capture an optional local character performance.",
            "NSMicrophoneUsageDescription": "Record optional local lip-sync audio.",
        },
    )
