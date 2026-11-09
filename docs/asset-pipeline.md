# Asset pipeline and output

Install optional local codecs with:

```powershell
uv sync --locked --extra gui --extra mcp --extra render --extra psd --extra illustrator
```

`render` provides Pillow 13.0.0 and resvg-py 0.5.0. `psd` adds psd-tools 1.25.0
and its basic pixel dependencies. Local operation needs no network after installation.
`illustrator` adds PDFium 5.14.0 for PDF-compatible AI artboards.
Python/CLI rendering does not import Qt. The base package retains SVG/runtime JSON
output. Missing optional codecs produce an actionable error; the launcher never
installs dependencies automatically.

## Source-preserving imports

Use **Assets → Add assets…**. Imports register sources in **Project assets** by
default. Check **Also place** to instantiate immediately, or double-click a
registered sequence/layered source later. Repeated placements have fresh object,
group and mesh IDs while sharing source images. Heavy import decoding runs on a
worker. Changing or closing its source project prevents stale adoption; successful
adoption is one Undo item.

The default **Files** mode accepts up to 128 mixed sources at once. Select multiple
files using the native OS picker (Windows, macOS, or the Linux desktop integration
available to Qt). File navigation, thumbnail view and preview support follow the
OS and its installed preview providers; PSD/SVG previews are not universally
available. Rigora does not scan folders or decode thumbnails during selection.
Qt provides a fallback browser where a native dialog integration is unavailable.
Source validation and background import still run after files are selected.

External local file drops follow their destination:

- **Project assets** or other application surfaces: register sources only.
- **Stage preview**: register sources, then center new artwork in the camera.
- **Scene folder**: register sources, then center instances in the camera inside that folder.
- **Scene row edge**: register and place at the indicated draw-order position.

All successful files in one drop form one Undo item. A failed file rolls back its
own records, leaving successful files intact; the status reports each failure.
Dropping an existing Project asset reuses its embedded source and creates an
independent instance. Project-asset drags show a translucent preview at the actual
scene size and final camera-centered location, without changing undo history.
Layered placements retain nested groups beneath a resource folder. Attach imported
audio in **Animation → Face & lip-sync** for audible timeline playback and mouth keys.

| Input | Supported behavior |
| --- | --- |
| PNG/JPEG/static SVG | Original bytes remain embedded. SVG is self-contained and static. |
| BMP/TIFF/static GIF/WebP | Bounded optional raster decoding; original bytes retained. |
| Image sequences | Explicit file order, equal image dimensions, FPS/start/loop. Sampling is deterministic at fractional or arbitrary absolute frames. |
| Sprite sheets | Uniform row-major cells, dimensions, margin, spacing, count and FPS. The original sheet and derived PNG frames are retained. |
| OpenRaster `.ora` | PNG layers, names, nested groups, offsets, visibility, source-over opacity and painter order. Original archive retained. |
| PSD/PSB | Basic 8-bit RGB pixel layers/groups. Raster masks become derived PNG alpha with a diagnostic; the complete PSD remains embedded. |
| Illustrator AI | PDF-compatible artboards rendered as transparent pixels after explicit approximation acknowledgement. Original retained. Private layers/native vectors are not decoded; use exported SVG for vectors. |
| PCM WAV | Original samples and timing metadata, clip association, transport playback and optional local speech recognition. See the facial/audio guide. |
| `.rigora` / `.rigpack` | Open projects or install packs through existing controls. Packs retain original sources and editable scenes; automation also has `asset_pack_install`. |

Animated GIF/WebP/APNG and multipage TIFF are refused by static import rather than
flattened. Supply explicit frame images. Sequence order follows the paths list;
use padded names or reorder the dialog's lines. Sequence images can be skinned
and deformed with the same mesh tools.

PSD type/vector/smart-object/adjustment layers, advanced blends, clipping, effects,
group masks and isolated group opacity are not a complete Photoshop interpreter.
Unsupported layered features stop import by default. The explicit approximation
option extracts available pixels and reports differences while retaining the
original source. ORA unsupported blends/group opacity use the same policy.
Baked raster masks are not independently editable Rigora mask objects.

Limits: 32 MiB/source file (16 MiB for the automation static-image entry point),
256 sequence files and 64 MiB total sequence source bytes; 128 layered entries,
24 group levels, 64 megapixels combined layer pixels and 96 MiB expanded ORA bytes.
Individual artwork is limited to 8192 pixels per axis and 16 megapixels. New
embedded project sources share a 96 MiB import budget, leaving package headroom.

## Rendering and queue

Open **File → Render & export…** (**Ctrl+Shift+E**). Set destination, scene-frame
range, output FPS, resolution, background and format. Output FPS determines the
sample interval in scene frames. **Add to queue** captures an independent document
snapshot; later edits or tab changes cannot alter running output.

One worker serializes jobs. Select a row to inspect errors/warnings or cancel.
Closing the dialog retains jobs for reopening; closing Rigora cancels unfinished
work. Existing files require **Replace existing output files** explicitly.

| Output | Contract |
| --- | --- |
| PNG / SVG sequences | Transparent canvas; PNG also supports a solid background. Numbered files for sequences. |
| GIF | Indexed color, up to 255 colors plus transparent index, binary alpha, 10 ms timing, at most 100 FPS. |
| Animated WebP | Lossless frames and full alpha when supported by the installed Pillow build. Independent keyframes preserve the transparent canvas. |
| Animated PNG | `.apng`, exact 8-bit RGBA frames and smooth alpha, using Pillow. |
| WebM · VP9 / VP8 | `.webm`, smooth alpha with `libvpx-vp9` / `libvpx` and 4:2:0 color. High-quality lossy color; not exact RGBA. VP9 is the default for `.webm`; select `webm-vp8` explicitly for VP8. |
| MOV · ProRes 4444 | `.mov`, `prores_ks` profile 4, 4:4:4 color and alpha. Editing/compositing intermediate; not mathematically lossless. |
| MKV · FFV1 | `.mkv`, FFV1 level 3 with BGRA. Lossless decoded 8-bit RGBA, including fractional alpha. Requires a compatible editor/player. |
| MP4 | Configured FFmpeg, H.264/yuv420p, even dimensions and solid background. No alpha; optional attached clip audio. Other video formats also support clip audio. |
| Sprite atlas | PNG grid plus versioned JSON rectangles, sample frames, durations, loop and pivots for custom game loaders. |
| Runtime JSON | Baked world-space nodes/meshes, UVs, draw order and original visual source bytes. |
| Godot / Unity / Unreal ZIP | Transparent baked sprites, timing, native resources/editor importers. See [engine exports](game-engine-export.md). |
| Editable Godot / Unity / Unreal ZIP | Planar bones, weighted meshes, native animation/morph corrections, separate clothing/colors, original artwork and runtime metadata. Native Unity/Godot checked; Unreal native execution unverified. See [engine exports](game-engine-export.md). |
| Project/scene packages | `.rigora` retains editable data and sources; `.rigpack` shares an editable scene. |

Sequences use `name-0000.ext`, etc.; one synchronous frame retains its exact name.
All destinations are checked before work and again at publication. Jobs stage
privately under the destination directory. Cancellation/render/encode failure
discards staging and preserves existing files. Publication is short and cannot
be cancelled once begun. Each file is atomic; publication I/O errors can leave
earlier files, since a sequence is not a filesystem-wide transaction.

Queue limits: 600 samples/job, 1–240 FPS, 1–4096 output pixels per axis, 16 active
jobs, 32 history entries. The synchronous preview retains its 60-frame limit.
Staged/encoded output is bounded to 128 MiB. GIF encodes one independent frame at
a time, so its image memory does not grow with animation length. WebP/APNG/atlas
memory is limited to 64 megapixels; atlas dimensions must fit 8192 pixels per side. SVG limits are
20,000 triangles, 16 MiB source bytes and 32 MiB output per frame. Runtime samples
have a 64 MiB geometry budget and visual sources a 32 MiB budget.

The pipeline evaluates hierarchy, constraints, skinning and deformer stacks before
drawing in scene order. Vector artwork rasterizes at final output resolution,
never from thumbnails. UV triangle mapping, union clips and group opacity preserve
deformation and translucent regions. Headless SVG text requires conversion to
outlines; no silent machine-font dependency is used. Evaluation warnings prevent
successful-looking exports with missing solvers.

## Python, CLI and MCP

New canonical operations are `sequence_import`, `sequence_place`,
`spritesheet_import`, `layered_import`, `layered_place`, `audio_import`,
`asset_pack_install`, `output_formats`, `render_submit`, `render_status` and
`render_cancel`. Import operations default to `place=False`. Inspect their typed
signatures in `RigoraAPI`; CLI/MCP expose the same validated arguments.

`frame_render` adds `format`, `fps`, `background`, `loop` and `columns` to existing
path/frame/frames/resolution/bones/overwrite arguments. `format="auto"` infers
ordinary extensions; use explicit `spritesheet` or `runtime-json` for those outputs.
`render_submit` accepts an explicit frame list and the same settings, returning a
stable `job_id`. Poll `render_status` or cancel through `render_cancel` in the
same Python/MCP session. Another CLI process cannot access its in-memory queue.
Call `api.close()` when a long-lived host shuts down.

```python
from pathlib import Path
from rigora.api import RigoraAPI

api = RigoraAPI(Path.cwd())
api.execute("project_open", {"path": "character.rigora"})
api.execute(
    "frame_render",
    {
        "path": "frames/walk.png",
        "frames": [0, 1, 2, 3],
        "width": 800,
        "height": 600,
    },
)
```

Dry runs validate settings, paths and initial evaluation without creating output
directories or encoded images. A dry-run submission creates no job. The one-shot
CLI waits for submitted jobs before exiting; optional JSON progress goes to
stderr, and Ctrl+C requests cancellation. Stateful Python/MCP hosts may poll
asynchronously; synchronous MCP rendering also sends per-frame progress.

For video, the GUI automatically detects FFmpeg on PATH unless a saved encoder
still exists. The encoder picker can select a different local installation.
Configure `RigoraAPI(root, encoder=Path(...))` or CLI/MCP `--encoder PATH` for
those hosts. Client tools cannot choose executables or arbitrary
flags. The fixed FFmpeg subprocess has a 120-second deadline and cancellation of
only its own process. No shell is used. FFmpeg is neither bundled nor downloaded;
use an installed build with the selected codec and its applicable license.
In the GUI, **Use installed** refreshes the detected FFmpeg from PATH; **Choose…**
uses a native file picker. The path is retained after a successful queue submission.
Transparent video profiles default to **Transparent**; leave it checked for alpha.
The GUI, CLI, Python API and MCP all use the same fixed encoding profiles.
GIF needs no FFmpeg installation. Its incremental writer uses Pillow's documented
[GIF block helpers](https://pillow.readthedocs.io/en/stable/reference/plugins.html#module-PIL.GifImagePlugin),
with per-frame palettes, transparent disposal and cumulative 10 ms timing.

For lossless masters choose PNG frames, APNG, lossless WebP or FFV1. ProRes is
suited to compositing intermediates; WebM is suited to web delivery. A player
may display transparent pixels against black without compositing them. FFmpeg's
native VP8/VP9 decoders may omit WebM's alpha payload: force `-c:v libvpx` or
`-c:v libvpx-vp9` before `-i` when checking alpha. Integration tests decode actual
frames and compare transparent, fractional-alpha and opaque pixels; FFV1/APNG
round trips also compare every RGBA byte. See the official
[FFmpeg encoder documentation](https://ffmpeg.org/ffmpeg-codecs.html) for codec options.

Trusted hosts can inject custom exporters with
`RigoraAPI(..., exporters={"org.example.format": callback})`. The callback receives
a document snapshot, immutable OutputSettings, one staging path, a cancellation
event and progress callback. Write the staging file and return diagnostics; the
shared service bounds and publishes it. Enabled Plugin SDK commands can call the
same service. This is trusted host code, not a remote code-loading operation.

## Documented interchange

`rigora.sprite-atlas` JSON version 1 has `image` (sibling PNG basename), `size`
`[width,height]`, `fps`, `loop`, and `frames`. Each frame has `index`,
`source_frame`, `rect: [x,y,width,height]`, `duration_ms`, and `pivot: [0,0]`.
Coordinates use top-left pixel origin; pivots are canvas-relative. Cells are not
trimmed or rotated. This dedicated game-oriented format makes no native Spine,
Unity, Godot or other engine compatibility claim.

`rigora.runtime-animation` JSON version 1 contains `fps`, `coordinates`, `canvas`,
`assets` and ordered `samples`. Visual assets carry stable IDs, MIME types,
SHA-256 hashes and original base64 bytes. Samples use the headless ScenePose
contract: requested/evaluated frame, nodes, render order and triangle meshes.
Mesh vertex positions are already **world-space pixels**: do not apply the owner
matrix again. UVs are normalized to the referenced image. Node local/world
matrices are six-value affine transforms; X points right and Y down. Runtime
output is visual and baked; retain `.rigora` for audio, keys, constraints and
editable deformation controls.

Optional format-2 `sprite_sequence` metadata contains `assets`, `fps`, `start`,
`loop` on sequence assets and meshes. Layered source `layered_layout` contains
earlier group indices, image IDs, names, offsets, opacity and visibility. These
authoritative records survive save/load and remap when scene packs create fresh
IDs; original source files remain unchanged and separate.

## Offline acceptance and dependencies

Run `python examples/asset_pipeline_workflow.py --output build/my-output-study`
in a fresh directory. It imports original vector artwork, creates a rigged
character, applies walk/FFD animation, embeds PCM WAV, renders transparent PNGs,
exports atlas/runtime JSON/scene pack and saves an editable project. It reopens
the project and compares exact source bytes and evaluated geometry, without Qt.

Compatibility was checked against the official [resvg API](https://resvg-py.readthedocs.io/en/latest/api.html),
[Pillow formats](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html),
[psd-tools API](https://psd-tools.readthedocs.io/en/latest/reference/psd_tools.api.layers.html),
[OpenRaster specification](https://www.openraster.org/baseline/file-layout-spec.html)
and [FFmpeg reference](https://ffmpeg.org/ffmpeg.html). Pillow uses MIT-CMU;
resvg-py/resvg and psd-tools use permissive licenses. Installed distributions
retain their notices. Exact dependencies are in `uv.lock`. No proprietary
artwork, motion library or runtime schema was copied into this project.
