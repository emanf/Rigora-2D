# Character acting, preview transport, browsing and alpha exports

Validated 2026-10-21 on the Windows development host.

## Delivered behavior

- The 23 character templates contain 69 editable performances. All 11 human
  identities have separate Walk/Run key-pose sequences and standing acting beats.
  Dog, cat and rabbit have separate body acting and footfall orders. Front and
  profile motion curves are compared after removing tempo, offsets and amplitude,
  so renamed or scaled copies cannot satisfy the distinct-performance test.
- Standing keeps complete foot transforms locked. Frontal standing legs remain
  nearly extended, without introducing nonuniform scales into floor constraints.
  Front arms can cross the torso and near hands remain visible over the face.
- Spring Editor uses the shared timeline Play/Pause and Loop actions, a styled
  scrubber and frame readout. Successful settings changes resume running previews.
  Closing stops playback started there. No second playback timer was added.
- Docked Preview selects a character without filtering the browser to its name.
  Search has a clear button and result counts. Per-character performance choices
  survive browsing. A changed archive triggers catalog refresh before stale
  scene/source identities can be used in a new preview.
- Render & export supports WebM VP9/VP8 alpha, ProRes 4444 MOV, lossless BGRA
  FFV1 MKV and APNG, alongside existing PNG/SVG/WebP/GIF/MP4/atlas/runtime output.
  All adapters use the same staged exporter. Video uses an explicitly selected
  local FFmpeg; Use installed selects PATH's encoder without downloading anything.

## Checks

- 49 character, Spring Editor, subdivision, template-browser and workspace tests
  passed together: `build/choreography-review/final-tests.xml`.
- 16 image/video output and GUI tests passed together, including actual encode /
  decode checks: `build/choreography-review/alpha-export-tests.xml`.
- Ruff lint, formatting and mypy passed. No new dependencies were added.
- All 23 templates were rendered through real document/evaluation/export services.
  Motion sheets and animated WebP previews are under
  `build/choreography-review/final/`; Spring Editor screenshot is
  `build/choreography-review/spring-editor.png`.

Actual alpha tests cover empty, fractional-alpha and opaque regions. FFV1 and
APNG compare every decoded RGBA byte. WebM decoding explicitly uses libvpx,
because FFmpeg's native decoder may omit the separate WebM alpha payload.

The supplied-reference boy's 18-frame Run was exported at 960×540 / 24 FPS to
all five new profiles under `build/alpha-export-demo/`. Decoded first frames
have alpha ranges 0–255 in every profile; FFV1 and APNG match the source RGBA
exactly. See `alpha-verification.json` and `alpha-proof.png` in that folder.
WebM and ProRes preserve alpha but are not exact RGBA archival formats; the
export dialog describes those quality differences.

Diagnostic medians on this host (9 samples; fixture creation excluded):

| Scene | Hand pan | Changed frame paint | Sequential playback + paint |
| --- | ---: | ---: | ---: |
| Reference boy | 2.45 ms | 6.91 ms | — |
| Willow | 2.83 ms | 9.94 ms | 11.36 ms |

Reports: `build/choreography-review/performance-boy/workspace.json` and
`build/choreography-review/performance-willow/workspace.json`. These are local
measurements, not portable performance guarantees.

Restart the running Python app to load changed UI code. Refresh Templates and
place fresh characters to use the new embedded artwork/clips; existing project
instances retain their owned animation data. Open Render & export with
Ctrl+Shift+E, select a profile and keep Transparent checked for alpha. For video,
use Use installed or Choose… once to select FFmpeg. See
[the output guide](asset-pipeline.md) for limits, API keys and codec details.
