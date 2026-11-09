"""Compile a native desktop bundle; application validation is an explicit optional step."""

import argparse
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def native_platform() -> str:
    """Return the supported native target; freezing cannot cross-compile other operating systems."""
    systems = {"Windows": "windows", "Linux": "linux", "Darwin": "macos"}
    try:
        return systems[platform.system()]
    except KeyError as error:
        raise RuntimeError("Build on Windows, Linux (glibc), or macOS.") from error


def install_linux_tools() -> None:
    """Install missing freezing/Qt system libraries on supported Linux package managers."""
    if platform.libc_ver()[0] != "glibc":
        raise RuntimeError("The locked Qt wheels require glibc Linux; use Ubuntu/Debian or Fedora.")
    if not all(shutil.which(tool) for tool in ("ldd", "objdump", "objcopy")):
        install_linux_packages()


def install_linux_packages() -> None:
    """Install native dependencies with the host package manager and sudo when needed."""
    prefix = [] if os.geteuid() == 0 else ["sudo"]
    if prefix and not shutil.which("sudo"):
        raise RuntimeError("Missing native libraries: run this build with sudo available.")
    if shutil.which("apt-get"):
        subprocess.run([*prefix, "apt-get", "update"], check=True)
        commands = [
            *prefix,
            "apt-get",
            "install",
            "-y",
            "binutils",
            "libc-bin",
            "libgl1",
            "libegl1",
            "libfontconfig1",
            "libdbus-1-3",
            "libpulse0",
            "libxkbcommon0",
            "libxkbcommon-x11-0",
            "libxcb-cursor0",
            "libxcb-icccm4",
            "libxcb-image0",
            "libxcb-keysyms1",
            "libxcb-render-util0",
            "libxcb-shape0",
            "libxcb-xinerama0",
            "libxcb-xkb1",
        ]
    elif shutil.which("dnf"):
        commands = [
            *prefix,
            "dnf",
            "install",
            "-y",
            "binutils",
            "glibc",
            "mesa-libGL",
            "mesa-libEGL",
            "fontconfig",
            "dbus-libs",
            "pulseaudio-libs",
            "libxkbcommon",
            "libxkbcommon-x11",
            "xcb-util-cursor",
            "xcb-util-wm",
            "xcb-util-image",
            "xcb-util-keysyms",
            "xcb-util-renderutil",
            "libxcb",
        ]
    elif shutil.which("pacman"):
        commands = [
            *prefix,
            "pacman",
            "-S",
            "--needed",
            "--noconfirm",
            "binutils",
            "glibc",
            "mesa",
            "fontconfig",
            "dbus",
            "libpulse",
            "libxkbcommon",
            "libxkbcommon-x11",
            "xcb-util-cursor",
            "xcb-util-wm",
            "xcb-util-image",
            "xcb-util-keysyms",
            "xcb-util-renderutil",
            "libxcb",
        ]
    else:
        raise RuntimeError("Install binutils and Qt's xcb/OpenGL system libraries for this distro.")
    subprocess.run(commands, check=True)


def linux_missing_libraries(python: Path, environment: dict[str, str]) -> str:
    """Report unresolved libraries needed by the bundled GUI and its native display plugins."""
    location = subprocess.check_output(
        [str(python), "-c", "import PySide6; print(PySide6.__path__[0])"],
        text=True,
        env=environment,
    ).strip()
    qt = Path(location) / "Qt"
    libraries = [
        *(
            qt / "lib" / f"libQt6{name}.so.6"
            for name in ("Core", "Gui", "Widgets", "Network", "Svg", "OpenGL", "Multimedia")
        ),
        qt / "plugins/platforms/libqxcb.so",
        qt / "plugins/platforms/libqoffscreen.so",
    ]
    missing = []
    for library in libraries:
        if not library.is_file():
            raise RuntimeError(f"A required Qt library is missing: {library}")
        result = subprocess.run(
            ["ldd", str(library)], capture_output=True, text=True, check=False, env=environment
        )
        missing.extend(line.strip() for line in result.stdout.splitlines() if "not found" in line)
    return "\n".join(sorted(set(missing)))


def executable_path(output: Path, target: str) -> Path:
    """Locate the main native executable in PyInstaller's platform-specific output."""
    if target == "macos":
        return output / "Rigora.app" / "Contents" / "MacOS" / "Rigora"
    return output / "Rigora" / ("Rigora.exe" if target == "windows" else "Rigora")


def remove_build_outputs(*relative_paths: str) -> None:
    """Delete only resolved generated build paths inside this checkout.

    Validate every target before deleting any. Linked directories are rejected so
    cleanup cannot traverse into another checkout, user data or a shared folder.
    Locked files stop cleanup rather than allowing another large build beside them.
    """
    root = ROOT.resolve()
    targets = []
    for relative in relative_paths:
        target = root / relative
        resolved = target.resolve()
        if (
            resolved != target
            or resolved == root
            or not resolved.is_relative_to(root)
            or not (target == root / "dist" or target.is_relative_to(root / "build" / "desktop"))
        ):
            raise RuntimeError(f"Refusing cleanup outside generated build directories: {target}")
        if target.exists() and not target.is_dir():
            raise RuntimeError(f"Expected a generated build directory: {target}")
        targets.append(target)
    for target in targets:
        if target.exists():
            print(f"Cleaning generated build output: {target}", flush=True)
            try:
                shutil.rmtree(target)
            except OSError as error:
                raise RuntimeError(
                    f"Could not clean {target}. Close any running built copy of Rigora "
                    "and applications holding build files, then retry."
                ) from error


def freezing_path(python: Path, target: str) -> str:
    """Exclude unrelated applications' DLLs/tools from native dependency discovery."""
    if target == "windows":
        windows = Path(os.environ.get("SYSTEMROOT", "C:\\Windows"))
        directories = [python.parent, windows / "System32", windows]
    else:
        directories = [
            python.parent,
            Path("/usr/bin"),
            Path("/bin"),
            Path("/usr/sbin"),
            Path("/sbin"),
        ]
    return os.pathsep.join(str(path) for path in directories)


def check_tests(python: Path, output: Path, run: Callable[..., None]) -> None:
    """Run the full suite in bounded file batches and combine reports after every batch passes."""
    files = sorted(
        path
        for path in (ROOT / "tests").rglob("*.py")
        if path.name.startswith("test_") or path.name.endswith("_test.py")
    )
    if not files:
        raise RuntimeError("No test files were found in this source checkout.")
    combined = ET.Element("testsuites")
    for offset in range(0, len(files), 20):
        report = output / f"tests-{offset // 20 + 1:02}.xml"
        run(
            str(python),
            "-m",
            "pytest",
            "-q",
            "-x",
            *(str(path) for path in files[offset : offset + 20]),
            f"--junitxml={report}",
        )
        for suite in ET.parse(report).getroot().findall("testsuite"):
            if int(suite.get("errors", "0")) or int(suite.get("failures", "0")):
                raise RuntimeError(f"A test batch reported failures: {report}")
            combined.append(suite)
    if not sum(int(suite.get("tests", "0")) for suite in combined):
        raise RuntimeError("The test batches did not execute any tests.")
    ET.ElementTree(combined).write(output / "tests.xml", encoding="utf-8", xml_declaration=True)


def build(uv: str, *, verify: bool = False) -> Path:
    """Install native build dependencies and package the app, optionally running validation."""
    target = native_platform()
    if target == "windows":
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    elif hasattr(os, "nice"):
        os.nice(5)
    remove_build_outputs("build/desktop", "dist")
    if target == "linux":
        install_linux_tools()
    if target == "macos" and not shutil.which("codesign"):
        raise RuntimeError(
            "macOS codesign is missing. Restore the OS developer command-line tools."
        )
    if shutil.disk_usage(ROOT).free < 4 * 1024**3:
        raise RuntimeError("The build requires at least 4 GiB of free disk space.")
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    work = ROOT / "build" / "desktop" / stamp
    work.mkdir(parents=True)
    output = ROOT / "dist" / f"{target}-{platform.machine().lower()}-{stamp}"
    output.mkdir(parents=True)
    temporary = work / "temp"
    temporary.mkdir()
    environment = work / "environment"
    env = {
        **os.environ,
        "UV_PROJECT_ENVIRONMENT": str(environment),
        "QT_QPA_PLATFORM": "offscreen",
        "RIGORA_PREFERENCES_PATH": str(work / "preferences.json"),
        "TMP": str(temporary),
        "TEMP": str(temporary),
        "TMPDIR": str(temporary),
    }
    env.pop("VIRTUAL_ENV", None)
    env.pop("RIGORA_SAFE_MODE", None)
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    log = output / "build.log"

    def run(*command: str, cwd: Path = ROOT, timeout: float | None = None) -> None:
        """Retain each checked stage in the build log without opening child windows."""
        print("\nRUN:", subprocess.list2cmdline(command), flush=True)
        with log.open("a", encoding="utf-8") as stream:
            stream.write("\nRUN: " + subprocess.list2cmdline(command) + "\n")
            stream.flush()
            subprocess.run(
                command,
                cwd=cwd,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if target == "windows" else 0,
            )
        print("PASS (details in", log, ")", flush=True)

    print(f"Building {target}/{platform.machine()}; progress log: {log}", flush=True)
    groups = ["--group", "dev"] if verify else []
    run(
        uv,
        "sync",
        "--locked",
        "--all-extras",
        "--no-default-groups",
        "--group",
        "build",
        *groups,
        "--no-editable",
        "--link-mode",
        "copy",
    )
    python = environment / ("Scripts/python.exe" if target == "windows" else "bin/python")
    if target == "linux" and linux_missing_libraries(python, env):
        install_linux_packages()
        if missing := linux_missing_libraries(python, env):
            raise RuntimeError("Unresolved native libraries after installation:\n" + missing)
    run(uv, "pip", "check", "--python", str(python))
    checks: list = ["locked dependencies", "dependency consistency", "native packaging"]
    if verify:
        run(str(python), "-m", "ruff", "check", ".")
        run(str(python), "-m", "ruff", "format", "--check", ".")
        run(str(python), "-m", "mypy")
        check_tests(python, output, run)
        checks.extend(("lint", "format", "mypy", "pytest"))
    env["PATH"] = freezing_path(python, target)
    run(
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--distpath",
        str(output),
        "--workpath",
        str(work / "freeze"),
        str(ROOT / "packaging" / "Rigora.spec"),
    )
    executable = executable_path(output, target)
    if not executable.is_file():
        raise RuntimeError(f"The native executable was not produced: {executable}")
    if verify:
        report = output / "bundle-check.json"
        run(str(executable), "--bundle-self-test", str(report), cwd=temporary, timeout=180)
        checked = json.loads(report.read_text(encoding="utf-8"))
        if checked.get("status") != "passed":
            raise RuntimeError(f"Packaged application checks failed: {report}")
        checks.append(checked)
    manifest = {
        "status": "passed",
        "platform": target,
        "architecture": platform.machine(),
        "executable": str(executable.relative_to(output)),
        "python": platform.python_version(),
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "tests": "passed (see tests.xml)" if verify else "not requested (compile-only)",
        "checks": checks,
    }
    (output / "build-report.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    remove_build_outputs(str(work.relative_to(ROOT)))
    print(
        f"\nBUILD PASSED: {executable}\nKeep the entire bundle folder together.\nReport: {output}"
    )
    return executable


def main() -> int:
    """Parse build options and preserve a failing stage's exit status for all OS launchers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uv", required=True, help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-pause", action="store_true", help="Do not pause the OS launcher on failure"
    )
    parser.add_argument(
        "--verify", action="store_true", help="Also run lint, types, tests and offscreen app checks"
    )
    args = parser.parse_args()
    try:
        build(args.uv, verify=args.verify)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(
            f"\nBUILD FAILED: {error}\nRead the build.log in the newest dist folder.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
