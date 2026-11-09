# Install and run Rigora

The current release is a **development candidate**, packaged as a Python wheel
and source archive. There is no signed standalone installer. Windows is the
validated desktop platform; other platforms need native validation.

Native executable build scripts are also available for Windows, Linux and macOS.
See [desktop builds](desktop-builds.md) for automatic dependency setup and the
resulting executable/application bundle. Application testing is optional.

## Development checkout

Install Python 3.12 and uv, then open PowerShell in the project directory:

```powershell
uv sync --locked --extra gui --extra mcp --extra render --extra psd
.\Run_Rigora.bat
```

The lock pins runtime, optional codecs and development tools. Core installs need
no optional extras; `gui` adds the desktop and built-in offline speech recognition,
`mcp` the official protocol adapter,
`render` raster output and additional static imports, and `psd` layered PSD input.
`illustrator` adds PDF-compatible AI artboard import; `tracking` adds optional
local MediaPipe face/body inference. `video-rig` adds local RTMLib/ONNX media pose
recovery; see [Media to Rig](video-to-rig.md) for model installation and limits.
Camera tracking also requires compatible
local task model files; see [camera setup](camera-performance.md). Use
`speech` for offline phoneme recognition in headless clients; GUI installations
already include it and its bundled models. No separate executable is needed;
see [live local lip-sync](live-speech.md). Use
`uv sync --locked --all-extras` to retain every feature group in one environment.
Only select the extras you use. Installation may download dependencies; normal
operation uses local files and no network service. `Run_Rigora.bat` and
`Test_Rigora.bat` never install packages. See [development.md](development.md).

## Install a built wheel

From the extracted source release, build as described in [release.md](release.md).
Use a separate environment for the built package:

```powershell
uv venv .\installed --python 3.12
uv pip install --python .\installed\Scripts\python.exe "rigora[gui,mcp,render,psd] @ file:///E:/Rigora/dist/rigora-0.1.0-py3-none-any.whl"
.\installed\Scripts\rigora.exe
```

Replace the wheel URL with the actual local artifact path. Python's standard
`venv` and `pip` can be used instead of uv. For an offline machine, prepare the
wheel and **all transitive dependencies** for that machine's Python/platform in
a local wheelhouse first; use pip `--no-index --find-links WHEELHOUSE`. An installed
package and warm uv cache are not themselves a portable wheelhouse.

Verify without opening a window using `rigora-headless --headless`. The desktop
does not require render/PSD/MCP extras to start. SVG export works without codecs.
MP4 additionally requires an explicitly selected compatible FFmpeg executable;
no encoder is downloaded or bundled. See [asset-pipeline.md](asset-pipeline.md).

## Settings, upgrades and recovery

Preferences normally live at `%LOCALAPPDATA%\Rigora\workspace.json`. Set
`RIGORA_PREFERENCES_PATH` before launch for an isolated or portable profile. Projects
live where you save them, separate from installation and preferences. Upgrading
Rigora does not migrate executable plugins automatically: restart after a plugin
wheel upgrade and review compatibility/trust diagnostics.

If a plugin prevents normal work, start `rigora --safe-mode`. For a failed save,
retain the open document and use Save As. A successful replacement leaves the
previous project as `.rigora.bak`; File → Open can open that backup as unsaved work.
There is no automatic crash recovery of unsaved edits. Copy a backup before
replacing your main file. See [project-format.md](project-format.md).
