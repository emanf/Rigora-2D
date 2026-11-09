# Video discovery and streamed GIF validation

Reviewed on 29 October 2026 using the source app with Qt offscreen on Windows.

The video error came from an empty encoder field, although a working FFmpeg was
already installed on PATH. Render & export now uses a valid saved executable or
automatically detects the installed one. Choose and Use installed remain available
for overriding that choice. Successful submissions retain the selected path.
Python/CLI/MCP hosts retain their explicit encoder configuration boundary.

The GIF error came from retaining every uncompressed RGBA frame, followed by a
second collection of quantized frames. The shared OutputService now encodes each
rendered GIF frame immediately into private staging with Pillow's documented GIF
block helpers. Local palettes preserve per-frame colors; transparency index 255
and disposal 2 clear previous artwork. Cumulative 10 ms timing avoids rounding
drift. The trailer is written only after all frames render successfully.
GIF needs no FFmpeg or new dependencies. Existing per-job frame, dimension and
encoded-byte bounds remain. WebP/APNG/atlas memory limits are unchanged.

## Evidence

**36 distinct tests have passing latest results** across:

- `build/export-recovery.xml`: 33 passed, one unrelated legacy character fixture
  failed because it removed mouth Objects without removing their draw-order
  references. The fixture now constructs a valid older scene and passes in the
  recheck; the project validator was retained.
- `build/streamed-gif-final.xml`: two passed and one initial sprite-placement
  assertion failed. The check now derives its sample point from actual rendered
  bounds instead of assuming imports bypass their placement transform.
- `build/export-recheck.xml`: all 12 passed, including both corrected cases and
  the complete output test module.

The tests cover:

- Real 1920×1080 GIF output with 34 frames (70,502,400 combined source pixels,
  exceeding the former 67,108,864-pixel limit), decoding every frame's color,
  alpha, frame count, repeat flag and aggregate 24 FPS timing.
- Moving transparent sprites with independent palettes and no disposal trails;
  play-once GIFs contain no repeat extension.
- Cancellation after a streamed frame preserves an existing destination and
  removes private staging.
- Actual MP4 export from the dialog with a stale saved encoder path, requiring
  no manual executable selection; the usable installed path is retained.
- Real VP8/VP9 alpha, ProRes 4444 and FFV1 encoding/decoding, lossless APNG,
  clip-audio muxing and previous image/atlas/runtime/queue workflows.

Ruff lint and format checks pass for 607 Python files. Mypy passes for 220 source
modules. The installed FFmpeg successfully executed; nothing needed downloading.
No executable bundle was rebuilt and all GUI tests ran offscreen.

Re-run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_output.py tests/test_alpha_output.py tests/test_media_gui.py tests/test_audio_game_interchange.py
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy
```

Review score: **9/10** — correctness **4/4**, memory/cancellation **2/2**,
desktop usability **1.5/2**, format compatibility **1/1**, platform coverage
**0.5/1**. Linux/macOS execution was not validated. GIF retains its standard
palette, binary transparency and timing limits; FFmpeg remains a local installed
tool rather than a bundled download. See [the output guide](asset-pipeline.md).
