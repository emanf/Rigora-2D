"""Resolve application-owned folders independently of the working directory."""

import sys
from importlib.resources import files
from pathlib import Path, PureWindowsPath


def application_root() -> Path:
    """Locate portable app data beside the executable, or in macOS bundle Resources."""
    if getattr(sys, "frozen", False):
        directory = Path(sys.executable).resolve().parent
        if sys.platform == "darwin" and directory.name == "MacOS":
            return directory.parent / "Resources"
        return directory
    return Path(__file__).resolve().parents[2]


def asset_path(relative: str) -> Path:
    """Resolve safe asset names in native bundles, installed wheels or editable checkouts."""
    windows_path = PureWindowsPath(relative)
    if (
        Path(relative).anchor
        or windows_path.anchor
        or windows_path.drive
        or ".." in Path(relative).parts
        or ".." in windows_path.parts
    ):
        raise ValueError("Asset paths must stay relative to the asset root.")
    if getattr(sys, "frozen", False):
        bundled = application_root() / "assets" / relative
        if bundled.is_file():
            return bundled
        raise FileNotFoundError(f"Bundled Rigora asset is missing: {relative}")
    packaged = Path(str(files("rigora").joinpath("assets", relative)))
    if packaged.is_file():
        return packaged
    source = application_root() / "assets" / relative
    if source.is_file():
        return source
    raise FileNotFoundError(f"Bundled Rigora asset is missing: {relative}")
