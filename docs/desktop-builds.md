# Build a native desktop application

Run the script for the operating system on which you want to use Rigora. Builds
include Python, PySide6, every optional Python feature group, and the complete
canonical asset collection. The resulting application does not need a separate
Python installation. The source checkout must include `assets/` and `uv.lock`.

The [GitHub release workflow](github-releases.md) runs these native builds on
hosted Windows, Linux and Apple Silicon macOS runners, creates ZIP downloads,
and attaches them to the selected published release when explicitly dispatched.

| Platform | Command | Application inside the new `dist/` folder |
| --- | --- | --- |
| Windows | `Build_Rigora.bat` | `Rigora/Rigora.exe` |
| Linux | `bash Build_Rigora.sh` | `Rigora/Rigora` |
| macOS | `bash Build_Rigora.sh` | `Rigora.app` |

macOS also has `Build_Rigora_macOS.command` for Finder. After copying a checkout
from Windows, run `chmod +x Build_Rigora_macOS.command` once to enable double-click.
Windows automation can use `Build_Rigora.bat --no-pause`. Both Unix scripts accept
the same options. All launchers resolve paths relative to themselves, including
project paths containing spaces.

The first run needs internet access. The scripts locate uv or install it into
`.build-tools/uv` using Astral's official installer without modifying the shell
profile. uv obtains Python 3.12 when necessary and installs the locked project,
codecs and PyInstaller into a fresh `build/desktop/<timestamp>/environment`.
The development `.venv` is independent. A separate environment per build avoids
reusing dependency files from an earlier build. Before every build, the driver
removes the previous `build/desktop/` environments and all generated `dist/`
output, including previous bundles and archives. Cleanup runs before the free-space
check or dependency installation so their disk space can be reclaimed first.
Close any running built copy before rebuilding. A locked file stops the build
with a cleanup error; linked output directories are rejected.

Source files, root `assets/`, `plugins/`, projects outside generated output,
the development `.venv`, unrelated test reports, and uv's download cache are retained.
Keep personal projects and modified plugin/artwork sources outside `dist/` and
`build/desktop/`, since those directories are disposable build output.
After successful compilation, the temporary environment and PyInstaller working
files are removed as well. The new bundle, build log and reports stay in `dist/`.
uv reuses its
download cache; an offline build requires all locked distributions and Python
already available.

Linux additionally checks binutils, glibc and the GUI's native libraries. Missing
packages are installed with apt, dnf or pacman; sudo may request a password. Other
distributions receive a diagnostic listing unresolved libraries. Use a glibc
distribution. macOS requires the system `codesign` tool. An installation failure
or incompatible wheel stops the build with an error rather than dropping a feature.

With the current lock, the complete feature set needs macOS 14+ on Apple Silicon;
the pinned MediaPipe release has no Intel macOS wheel. Linux x64 needs glibc 2.34+
and Linux ARM64 needs glibc 2.39+ for the pinned Qt wheels. Windows x64 is the
validated build target. The scripts cannot install a missing OS/architecture
wheel or upgrade the operating system to meet these requirements.

The default is **compile only**. It performs these steps:

1. Remove old generated desktop environments and distribution output.
2. Locked dependency installation and `uv pip check`.
3. PyInstaller native compilation with bundled assets and dependency metadata.
4. Confirm the executable exists, write `build-report.json`, and remove temporary build files.

It does **not** run Ruff, mypy, pytest, character checks or the application. It
does not install development/test tools. Build dependencies and native library
prerequisites are checked because compilation requires them.

For optional application validation, explicitly add `--verify`, for example
`Build_Rigora.bat --no-pause --verify` or `bash Build_Rigora.sh --verify`.
This additionally installs development tools, runs Ruff, mypy and the full pytest
suite in batches of up to 20 files, then tests the compiled executable offscreen.
That optional test checks asset hashes, codecs, a premade character animation,
save/reopen, PNG export, MCP, icons and desktop startup/shutdown. Verification can
take substantially longer than compilation and releases GUI memory between batches.

Native dependency discovery uses a restricted system/build PATH, preventing DLLs
from unrelated installed applications from overriding the packaged Qt runtime.

Optional tests use temporary preferences and run offscreen. Build processes use
reduced CPU priority. See the printed
`dist/<platform>-<architecture>-<timestamp>/build.log` for live stage details.
Successful builds contain `build-report.json` and record whether testing was
requested. `bundle-check.json` and `tests.xml` appear only with `--verify`.
A failure does not write a passing report.

Keep the entire `Rigora` folder on Windows/Linux, or the complete `.app` on macOS.
Windows/Linux bundles have this layout:

```text
Rigora/
  Rigora.exe         (Rigora on Linux)
  RigoraCLI.exe      (Windows console companion)
  assets/           (artwork, fonts, content packs and engine export integrations)
  plugins/          (local plugin packages; see its README)
  _internal/        (required Python, Qt, codecs and dependency licenses)
```

Assets are resolved relative to the executable, independently of the working
directory. There is no duplicate asset tree inside `_internal/rigora` and no
fallback to source files in native builds. macOS keeps app data in
`Rigora.app/Contents/Resources/assets` and `plugins`, following its bundle layout.
Plugin discovery checks both this application folder and the existing user plugin
folder; new discoveries still require explicit trust. Preferences, logs, recovery
and user-installed content remain in their normal writable user locations.

Studio Tools and Rig Health Check are included as optional example packages in
that plugin folder. Packaging their source does not enable or trust them.

Bundles omit installer/cache records from dependency metadata and Matplotlib's
sample datasets/documentation assets. Runtime metadata, entry points, licenses,
camera-tracking libraries, audio codecs and import/export integrations are retained.
Windows also includes `RigoraCLI.exe` for command-line automation, MCP and isolated
plugin workers. For example, `RigoraCLI.exe --headless --safe-mode` prints JSON;
the main `Rigora.exe` opens the editor without a console. Neither output is an
installer. Each build replaces previous generated output; old builds are not retained.

Build each OS and architecture on a matching host. Linux should be built on the
oldest glibc platform you intend to support. These scripts do not produce signed
installers or Apple notarization. Camera task models and configured FFmpeg remain
user-supplied runtime integrations. Offline English lip-sync and its model are
included; no separate Rhubarb installation is required. See [camera performance](camera-performance.md) and the
[asset pipeline](asset-pipeline.md).

The implementation follows the official [PyInstaller native build guidance](https://www.pyinstaller.org/en/stable/),
[system requirements](https://pyinstaller.org/en/stable/requirements.html) and
[uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/).
