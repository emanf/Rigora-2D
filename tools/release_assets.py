"""Archive native bundles and collect verified downloads without compiling or publishing."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

TARGETS = {("windows", "x64"), ("linux", "x64"), ("macos", "arm64")}


def digest(path: Path) -> str:
    """Hash an archive incrementally without retaining its binary contents in memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def release_name(tag: str) -> str:
    """Make a tag safe for downloadable filenames while retaining the exact tag in metadata."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", tag).strip(".-")
    if not name or len(name) > 100:
        raise ValueError("Use a nonempty release tag of at most 100 filename characters.")
    return name


def archive_bundle(bundle: Path, archive: Path, target: str) -> None:
    """Retain the complete application and native executable modes/framework symlinks."""
    if target == "macos":
        subprocess.run(
            ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(archive)],
            check=True,
        )
    elif target == "linux":
        subprocess.run(
            ["zip", "--symlinks", "-r", "-q", str(archive), bundle.name],
            cwd=bundle.parent,
            check=True,
        )
    else:
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for path in sorted(bundle.rglob("*")):
                if path.is_symlink():
                    raise ValueError("Unexpected symlink in the Windows bundle.")
                if path.is_file():
                    output.write(path, path.relative_to(bundle.parent).as_posix())


def package_build(report: Path, output: Path, tag: str, commit: str, arch: str) -> Path:
    """Package one successful build, recording its tag, commit, lock and archive digest.

    Output files never overwrite a previous package. The application bundle itself
    is unchanged, including macOS signing metadata. No application tests run here.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("The source commit must be a complete Git SHA.")
    data = json.loads(report.read_text(encoding="utf-8"))
    target = data.get("platform")
    if data.get("status") != "passed" or (target, arch) not in TARGETS:
        raise ValueError("A passing build report for a supported target is required.")
    normalized = {"amd64": "x64", "x86_64": "x64", "aarch64": "arm64", "arm64": "arm64"}
    if normalized.get(str(data.get("architecture", "")).lower()) != arch:
        raise ValueError("Build architecture does not match the requested archive.")
    name = "Rigora.app" if target == "macos" else "Rigora"
    executable = {
        "windows": "Rigora/Rigora.exe",
        "linux": "Rigora/Rigora",
        "macos": "Rigora.app/Contents/MacOS/Rigora",
    }[target]
    if str(data.get("executable", "")).replace("\\", "/") != executable:
        raise ValueError("Unexpected executable path in build report.")
    bundle = report.resolve().parent / name
    if not (report.parent / executable).is_file():
        raise ValueError("The reported application executable is missing.")
    if not re.fullmatch(r"[0-9a-f]{64}", str(data.get("lock_sha256", ""))):
        raise ValueError("The build report has no valid dependency lock digest.")
    output.mkdir(parents=True, exist_ok=True)
    stem = f"Rigora-{release_name(tag)}-{target}-{arch}"
    archive = output.resolve() / f"{stem}.zip"
    metadata = output / f"{stem}.release.json"
    if archive.exists() or metadata.exists():
        raise FileExistsError("Release files already exist; use a fresh output directory.")
    archive_bundle(bundle, archive, target)
    metadata.write_text(
        json.dumps(
            {
                "schema": 1,
                "tag": tag,
                "commit": commit,
                "platform": target,
                "architecture": arch,
                "archive": archive.name,
                "bytes": archive.stat().st_size,
                "sha256": digest(archive),
                "build": data,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return archive


def collect_packages(source: Path, output: Path, tag: str, commit: str) -> list[Path]:
    """Verify all three matrix results before collecting any release downloads.

    Reject missing/duplicate targets, unsafe names, changed archives and mismatched
    source revisions. This is a local check; uploading belongs to the workflow.
    """
    files = []
    targets = set()
    for metadata in sorted(source.rglob("*.release.json")):
        data: dict[str, Any] = json.loads(metadata.read_text(encoding="utf-8"))
        target = data.get("platform"), data.get("architecture")
        if target not in TARGETS or target in targets:
            raise ValueError("Missing, unsupported or duplicate release target.")
        targets.add(target)
        if data.get("schema") != 1 or data.get("tag") != tag or data.get("commit") != commit:
            raise ValueError("Release artifacts have a different tag, commit or schema.")
        if data.get("build", {}).get("status") != "passed":
            raise ValueError("A release artifact has no passing compiler report.")
        expected = f"Rigora-{release_name(tag)}-{target[0]}-{target[1]}"
        if metadata.name != expected + ".release.json" or data.get("archive") != expected + ".zip":
            raise ValueError("Release filenames do not match their declared target.")
        archive = metadata.parent / data["archive"]
        if archive.is_symlink() or metadata.is_symlink():
            raise ValueError("Release artifacts must be ordinary files.")
        if archive.stat().st_size != data.get("bytes") or digest(archive) != data.get("sha256"):
            raise ValueError("Release archive size or SHA-256 does not match its manifest.")
        files.extend((archive, metadata))
    if targets != TARGETS:
        raise ValueError("All three native packages must pass before anything is published.")
    output.mkdir(parents=True, exist_ok=False)
    collected = [Path(shutil.copy2(path, output / path.name)) for path in files]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{digest(path)}  {path.name}\n" for path in sorted(collected)), encoding="utf-8"
    )
    return collected


def main() -> None:
    """Run packaging or collection explicitly, propagating invalid/missing outputs as failures."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("package", "collect"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--arch", choices=("x64", "arm64"))
    args = parser.parse_args()
    if args.operation == "package":
        actual = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        if actual != args.commit:
            raise ValueError("The checkout is not the selected release commit.")
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--"], check=True)
        reports = list(args.source.glob("*/build-report.json"))
        if len(reports) != 1 or args.arch is None:
            raise ValueError("Use one fresh build output and specify its architecture.")
        print(package_build(reports[0], args.output, args.tag, args.commit, args.arch))
    else:
        collected = collect_packages(args.source, args.output, args.tag, args.commit)
        print(f"Verified {len(collected)} files")


if __name__ == "__main__":
    main()
