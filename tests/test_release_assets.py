"""Native release ZIP/provenance checks use tiny fixtures and never compile an executable."""

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tools.release_assets import TARGETS, collect_packages, digest, package_build

COMMIT = "a" * 40
TAG = "v0.1.0"


def build_report(root: Path, target="windows", architecture="AMD64") -> Path:
    """Create the minimum passing compiler report and a complete two-file fake bundle."""
    root.mkdir(parents=True)
    executable = {
        "windows": "Rigora/Rigora.exe",
        "linux": "Rigora/Rigora",
        "macos": "Rigora.app/Contents/MacOS/Rigora",
    }[target]
    entry = root / executable
    entry.parent.mkdir(parents=True)
    entry.write_bytes(b"test executable")
    asset = (
        root
        / ("Rigora.app/Contents/Resources" if target == "macos" else "Rigora")
        / "assets/example.svg"
    )
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"<svg/>")
    report = root / "build-report.json"
    report.write_text(
        json.dumps(
            {
                "status": "passed",
                "platform": target,
                "architecture": architecture,
                "executable": executable,
                "lock_sha256": "b" * 64,
                "tests": "not requested (compile-only)",
            }
        ),
        encoding="utf-8",
    )
    return report


def test_complete_windows_bundle_is_zipped_with_matching_digest_and_no_overwrite(tmp_path):
    """Keep assets beside the EXE, exclude surrounding build data and record exact provenance."""
    report = build_report(tmp_path / "build")
    (report.parent / "unrelated.log").write_text("private build diagnostics", encoding="utf-8")
    output = tmp_path / "downloads"
    archive = package_build(report, output, TAG, COMMIT, "x64")
    with zipfile.ZipFile(archive) as content:
        assert set(content.namelist()) == {"Rigora/Rigora.exe", "Rigora/assets/example.svg"}
    metadata = json.loads(next(output.glob("*.release.json")).read_text(encoding="utf-8"))
    assert metadata["sha256"] == digest(archive)
    assert metadata["bytes"] == archive.stat().st_size
    assert metadata["commit"] == COMMIT and metadata["tag"] == TAG
    assert metadata["build"]["tests"].startswith("not requested")
    with pytest.raises(FileExistsError):
        package_build(report, output, TAG, COMMIT, "x64")


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        ("architecture", "x86"),
        ("executable", "../outside.exe"),
        ("lock_sha256", "missing"),
    ],
)
def test_invalid_builds_never_produce_downloads(tmp_path, field, value):
    """A failed compiler, incompatible target or escaped path must stop before archiving."""
    report = build_report(tmp_path / "build")
    data = json.loads(report.read_text(encoding="utf-8"))
    data[field] = value
    report.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        package_build(report, tmp_path / "downloads", TAG, COMMIT, "x64")
    assert not (tmp_path / "downloads").exists()


@pytest.mark.parametrize("target,arch,tool", [("linux", "x64", "zip"), ("macos", "arm64", "ditto")])
def test_unix_archives_use_native_tools_that_preserve_symlinks(
    tmp_path, monkeypatch, target, arch, tool
):
    """Exercise command construction without running another platform's packaging tools."""
    from tools import release_assets

    report = build_report(tmp_path / "build", target, "arm64" if arch == "arm64" else "x86_64")
    calls = []

    def run(command, **kwargs):
        """Record the checked native invocation and emulate its successful archive output."""
        calls.append((command, kwargs))
        destination = Path(command[-1] if tool == "ditto" else command[-2])
        destination.write_bytes(b"archive")

    monkeypatch.setattr(release_assets.subprocess, "run", run)
    archive = package_build(report, tmp_path / "downloads", TAG, COMMIT, arch)
    assert archive.is_file() and calls[0][0][0] == tool and calls[0][1]["check"]
    assert "--keepParent" in calls[0][0] if target == "macos" else "--symlinks" in calls[0][0]


def artifacts(root: Path) -> Path:
    """Create three tiny cross-platform artifact descriptors for collector fault injection."""
    source = root / "artifacts"
    for target, arch in TARGETS:
        directory = source / f"{target}-{arch}"
        directory.mkdir(parents=True)
        name = f"Rigora-{TAG}-{target}-{arch}"
        archive = directory / f"{name}.zip"
        archive.write_bytes(b"archive")
        (directory / f"{name}.release.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "tag": TAG,
                    "commit": COMMIT,
                    "platform": target,
                    "architecture": arch,
                    "archive": archive.name,
                    "bytes": archive.stat().st_size,
                    "sha256": digest(archive),
                    "build": {"status": "passed"},
                }
            ),
            encoding="utf-8",
        )
    return source


def test_collect_requires_complete_matching_unmodified_packages(tmp_path):
    """Publish no partial set; successful collection emits checksums for all six files."""
    source = artifacts(tmp_path)
    output = tmp_path / "ready"
    collected = collect_packages(source, output, TAG, COMMIT)
    assert len(collected) == 6 and len(list(output.iterdir())) == 7
    assert len((output / "SHA256SUMS.txt").read_text().splitlines()) == 6
    archive = next(source.rglob("*.zip"))
    archive.write_bytes(b"changed archive")
    with pytest.raises(ValueError, match="SHA-256"):
        collect_packages(source, tmp_path / "failed", TAG, COMMIT)
    assert not (tmp_path / "failed").exists()


def test_collect_rejects_moved_sources_and_missing_targets(tmp_path):
    """Tag/commit identity and all expected runners are required independently of digests."""
    source = artifacts(tmp_path)
    with pytest.raises(ValueError, match="commit"):
        collect_packages(source, tmp_path / "wrong", TAG, "c" * 40)
    metadata = next(source.rglob("*.release.json"))
    data = json.loads(metadata.read_text(encoding="utf-8"))
    data["build"]["status"] = "failed"
    metadata.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="compiler report"):
        collect_packages(source, tmp_path / "failed", TAG, COMMIT)
    data["build"]["status"] = "passed"
    metadata.write_text(json.dumps(data), encoding="utf-8")
    next(source.rglob("*.release.json")).unlink()
    with pytest.raises(ValueError, match="All three"):
        collect_packages(source, tmp_path / "missing", TAG, COMMIT)


@pytest.mark.parametrize("dirty", (False, True))
def test_package_cli_refuses_different_or_dirty_source_revisions(tmp_path, monkeypatch, dirty):
    """Never attribute changed source to a release commit before inspecting any build output."""
    from tools import release_assets

    monkeypatch.setattr(
        release_assets.subprocess, "check_output", lambda *a, **k: COMMIT if dirty else "c" * 40
    )

    def check_changes(command, **kwargs):
        """Emulate a tracked edit detected by Git without requiring a repository fixture."""
        assert command == ["git", "diff", "--quiet", "HEAD", "--"] and kwargs["check"]
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(release_assets.subprocess, "run", check_changes)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "release_assets",
            "package",
            "--source",
            str(tmp_path),
            "--output",
            str(tmp_path / "out"),
            "--tag",
            TAG,
            "--commit",
            COMMIT,
            "--arch",
            "x64",
        ],
    )
    with pytest.raises(subprocess.CalledProcessError if dirty else ValueError):
        release_assets.main()
    assert not (tmp_path / "out").exists()
