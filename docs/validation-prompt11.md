# Prompt 11 validation

Date: 2026-10-18. Windows, Python 3.12.14, PySide6 6.12.0, Pillow 13.0.0,
resvg-py 0.5.0, psd-tools 1.25.0 and official MCP SDK 2.3.0.

`Test_Rigora.bat --no-pause` passed **285 tests**, with one existing Windows
symlink-permission skip and three Qt drag-constructor deprecation warnings.
Ruff lint/format and strict mypy passed (112 source modules). Focused checks
also exercise the final CLI queue result and runtime source/sample budget split.

Actual output checks cover transparent PNG sequences, SVG, GIF, animated WebP,
sprite PNG/JSON atlases, runtime JSON and a configured local FFmpeg H.264 MP4.
The MP4 was decoded by FFmpeg after encoding. Pixel checks verify changing
sequence sources, full transparency, translucent compositing and deformed vector
artwork at final resolution. WebP independent keyframes preserve transparent
canvas pixels. GIF timing uses distributed centisecond durations.

Import checks cover original-source preservation, image sequence sampling,
sprite slicing, repeated independent placement, basic PSD pixels/raster masks,
OpenRaster hierarchy/draw order/opacity, PCM timing, explicit unsupported-feature
handling, static animation refusal, safe archive paths, one-command undo,
project reopening and source-ID remapping in reusable packs.

Queue checks hold a real renderer between frames while inspecting progress,
editing the source, cancelling active/queued jobs and verifying unchanged existing
outputs and staging cleanup. Actual GUI tests verify asynchronous imports adopt
on the Qt thread, library-only defaults, repeated placement, responsive output
controls and settings/history retained when the dialog reopens. The real official
MCP stdio client also submitted and polled a PNG queue job successfully.

The headless acceptance example created a rigged original character, imported
original SVG/PCM sources, applied body motion and FFD, rendered four transparent
PNGs and exported atlas/runtime JSON/scene pack. Reopening the `.rigora` project
preserved exact source bytes and evaluated geometry. This ran without importing Qt.
Artifacts are ignored under `build/prompt11-example-complete/`.

The built wheel was installed in a clean environment with render/PSD codecs but
without Qt or MCP. Offline execution repeated the acceptance workflow, verified
transparent PNG pixels, completed an actual CLI queue command and imported/placed
a generated PSD while preserving its source bytes. A core-only environment also
retains SVG/API functionality without optional codecs.

Native Windows verification captured the main workspace, completed four-frame
render queue, sprite-import controls and layered-import controls using isolated
preferences. Images and logs are ignored under `build/ui-preview/` and
`build/maintenance/`. No existing user window was closed or reused.

Wheel/sdist builds and audits verify canonical assets, exact original bone SVG,
source documentation, package exclusions and batch CRLF. Render/PSD packages are
optional; the desktop and core still load without them. No FFmpeg binary or
proprietary artwork/library is bundled. Supported features and limits are in
[asset-pipeline.md](asset-pipeline.md). These checks completed before the Prompt 12 audit.
