"""Verify built distributions against canonical sources and optionally write a hash manifest."""

import argparse
import ast
import hashlib
import importlib.metadata
import json
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path
from urllib.parse import unquote

from rigora import __version__


def audit(root: Path, distributions: Path) -> dict:
    """Check exact packaged assets, source documentation, exclusions and batch line endings."""
    wheel = distributions / f"rigora-{__version__}-py3-none-any.whl"
    source = distributions / f"rigora-{__version__}.tar.gz"
    prefix = f"rigora-{__version__}/"
    with zipfile.ZipFile(wheel) as archive, tarfile.open(source) as sdist:
        wheel_names = set(archive.namelist())
        source_names = set(sdist.getnames())
        for path in (root / "assets").rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            assert archive.read("rigora/" + relative) == path.read_bytes(), relative
            member = sdist.extractfile(prefix + relative)
            assert member is not None and member.read() == path.read_bytes(), relative
        for path in (root / "src" / "rigora").rglob("*.py"):
            relative = path.relative_to(root / "src").as_posix()
            assert archive.read(relative) == path.read_bytes(), relative
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    assert ast.get_docstring(node), f"Missing purpose documentation: {path}"
        for folder in ("docs", "examples", "tools"):
            for path in (root / folder).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    assert prefix + path.relative_to(root).as_posix() in source_names, str(path)
        for name in ("pyproject.toml", "uv.lock", "README.md", "AGENTS.md", ".gitattributes"):
            assert prefix + name in source_names, name
        for name in wheel_names | source_names:
            assert not set(Path(name).parts) & {"build", ".venv", ".uv-cache", "__pycache__"}, name
    for path in root.glob("*.bat"):
        data = path.read_bytes()
        assert b"\n" in data and b"\n" not in data.replace(b"\r\n", b""), str(path)
    for document in (root / "README.md", *(root / "docs").rglob("*.md")):
        for target in re.findall(r"\]\(([^\s)]+)\)", document.read_text(encoding="utf-8-sig")):
            if ":" not in target and not target.startswith("#"):
                path = document.parent / unquote(target.split("#")[0])
                assert path.exists(), f"Broken local guide link: {document}: {target}"
    dependencies = {}
    for name in ("PySide6", "mcp", "Pillow", "resvg-py", "psd-tools", "hatchling"):
        try:
            metadata = importlib.metadata.metadata(name)
        except importlib.metadata.PackageNotFoundError:
            continue
        dependencies[name] = {
            "version": metadata["Version"],
            "license_expression": metadata.get("License-Expression"),
        }
    return {
        "version": __version__,
        "classification": "development candidate",
        "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (wheel, source)},
        "lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "build_requirements": tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))[
            "build-system"
        ]["requires"],
        "build_environment": dependencies,
        "checks": [
            "exact source modules",
            "exact canonical assets",
            "source guides/examples/tools",
            "archive exclusions",
            "batch CRLF",
            "source docstrings",
            "local guide links",
        ],
    }


def main() -> None:
    """Audit this checkout's artifacts and refuse replacing an existing manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = audit(root, args.dist.resolve())
    encoded = json.dumps(result, indent=2) + "\n"
    if args.manifest:
        with args.manifest.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
