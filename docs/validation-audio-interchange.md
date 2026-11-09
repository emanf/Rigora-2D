# Audio, speech and game interchange validation

Date: 2026-10-25. Implementation and review were performed in the current chat,
following the project's single-agent preference. No production project was used.

## Verified behavior

- New and rebuilt creator characters have ten independently bound mouth shapes.
  All five original identities were inserted, keyed, saved and reopened. Older
  character conversion preserves the Rest mesh/binding and undoes in one step.
- Audio association stores embedded source identity, start frame, gain and mute.
  Reopening after deleting the external WAV succeeds. Invalid edits are atomic.
- The real Qt Multimedia buffer/player follows seeking, pause and document
  changes. Testing found and fixed seeks lost during asynchronous decoder loading.
- Face & lip-sync reuses imported audio, restores clip settings and saves mouth
  keys/audio timing as one Undo item. Analysis results remain uncommitted until
  keying. Unsupported creator gaze/blink controls are disabled.
- The official Rhubarb 1.14.0 Windows build processed its bundled 14.3768-second
  speech sample locally: 88 timed cues across eight mapped shapes. The recognizer
  is optional and host-selected; no downloaded build path is a runtime dependency.
- Actual FFmpeg MP4 encoding/decoding verified delayed audio, audible sample
  energy after the offset, silence before it, and explicit silent export.
- PSD tests retain separate pixel layers and original source bytes. PDF-compatible
  AI tests retain artboards, visibility and original bytes, require acknowledgement
  of flattening, and reject legacy PostScript. The Rhubarb sample Illustrator file
  also imported successfully at 509 × 681 pixels.
- Engine ZIP tests verify rendered alpha/colors, frame ordering, FPS/duration,
  loop metadata, required resources/importer files and source-document immutability.
- Godot 4.7.2 loaded the native scene and checked three frames, 12 FPS, looping and
  explicit atlas rectangles. Unity 6000.6.4f1 compiled and ran the importer, then
  verified a native clip, exact duration, ordered sprite keys, pivot and prefab.
  The Unity check caught an extra hold frame and Windows separator handling;
  both were fixed in the shipped adapter and rechecked in the editor.

## Test runs and evidence

Separate regression groups overlap; counts are not a distinct-test total:

- 47 passed: new interchange tests plus existing face, asset pipeline, playback,
  output, media UI and alpha-video tests. `build/audio-interchange/tests.xml`.
- 85 passed: automation, MCP, interchange, character creation, game cast and
  feelings. `build/audio-interchange/services-tests.xml`.
- 15 passed: release reliability/dependency directions, face UI, audio UI and
  actual buffered audio transport review checks.
- Creator dialog regression results: `build/audio-interchange/creator-ui-tests.xml`.
  Eight tests passed, including the expandable categories/feelings workflow and
  the final audio-dialog screenshots.
- Whole-workspace Ruff lint/format and mypy pass; 187 source files type-checked.
- A final five-test recheck passed after adding a visible error for facial keys
  attempted outside the active object's animation scope.

`tools/review_audio_interchange.py` generates 250 mouth previews across all five
views, original sprite fixtures and three engine ZIPs in `build/audio-interchange`.
Front and side sheets were visually inspected for mouth placement, distinct
shapes and robot palette consistency. Rear-view mouth art stays hidden.
Native check sources are in `tools/engine_validation/`. Unity logs and its success
marker are under `build/audio-interchange`; speech cue evidence is under
`build/validation-tools/rhubarb-result.json`. Downloaded test tools remain in
`build/validation-tools`, outside packaged runtime assets.

## Practical limits

Unreal is not installed on this machine: the adapter's syntax and package content
were checked, but native PaperSprite/Flipbook creation remains unverified.
The sprite export modes are baked visuals, without runtime bones or wardrobe changes.
Editable export modes were added subsequently; see `validation-editable-rig.md`.
AI artboards flatten; Illustrator's private layers/native vectors are not decoded.
Audio input is PCM WAV, one source per clip. Subsequent microphone recording is
documented in `validation-editable-rig.md`. Live camera/speech tracking,
streaming, multitrack mixing and complete Adobe behavior parity remain unimplemented.
The detailed inventory is in `character-animator-comparison.md`.
