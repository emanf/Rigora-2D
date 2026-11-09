# Face workspace and English audio validation

2026-11-02. Implementation, review and tests were performed by one agent using
the source application. GUI tests ran with `QT_QPA_PLATFORM=offscreen`; no
foreground application, microphone or camera was opened. Automated tests muted
their own output. After the owner requested audible verification, the English
sample was also played once through the default speakers at full volume.
No executable bundles were rebuilt.

## Reviewed behavior

- A persistent portrait and waveform sit beside Face, Audio and Lip Sync tabs.
  Each tab owns one outer scroll surface. All six expression cards and ten
  mouth cards are visible together at the normal dialog size. Advanced cue text
  and executable setup collapse completely under expansion headings.
- The empty-project example is owned by a separate document. Card clicks do not
  create objects, asset imports or undo entries in the user's project. Repeated
  clicks keep the active card selected. Actual face editing uses a scratch pose
  until Key pose; previews remain inside the face window. Closing stops its
  independent transport, releases the decoder and disconnects dialog observers.
- Creator portraits render their own head artwork, not a substituted sample
  face. Original vectors, evaluated mesh deformation and appearance are reused.
  Painted head bounds exclude empty sprite margins; framing stays fixed across
  mouth changes. Full standalone facial rigs have a preview-only neutral backing.
- The real English welcome is bundled PCM, with an optional developer-only
  Windows generation script. The application loads WAV and cue files without
  a synthesizer, model download or external recording path. The same embedded
  audio is reused by content digest when explicitly applied. The English voice,
  transcript and cues load automatically when no attached voice is restored.
  Opening or importing preview audio leaves the main project's assets and undo
  history untouched. Attach/Key embeds the source in the same undoable edit.
- Play, Pause, Stop, waveform scrubbing and expression audition use dialog-owned
  state. Tests replace scene transport entry points with failures to prove they
  are never called. Actual Qt Multimedia decoding yields nonzero PCM through
  `QAudioBufferOutput`, with automated-test speakers muted. Preview volume and
  mute are independent of the scene mixer.
  Periodic painting follows the player's clock without replay/seek calls. A
  regression counts explicit synchronization commands during real PCM decoding.
  Output selection persists, and disconnected choices fail visibly.
- Draft timing appears under the waveform. Clicking near a cue selects it;
  time and mouth controls insert, replace or remove events without losing decoder
  precision or invalid manual text. Draft audition persists when paused and can
  be switched off to inspect saved animation.
- Key mouth cues and audio saves editable visibility keys and synchronized voice
  as one undo item. Embedded voice and timing survive save/reopen. Reattaching
  voice to a multitrack clip updates one stable voice placement and keeps music.
- Built-in analysis exposes progress, cancellation and editable uncommitted output.
  Actual PocketSphinx inference is tested through the service, public API and real
  GUI worker with no executable configuration. Native-format conversion tests
  exercise 8/16/24/32-bit PCM, mono/stereo, and 8/44.1/48/192 kHz sources. The
  separate live decoder handles the observed `+SPN+` noise token as Rest.
- Actual FFmpeg encoding/decoding verifies delayed voice is audible after its
  start and silent beforehand. The export path uses authored gain rather than
  a zero-gain pre-start transport sample. Explicit silent export remains silent.

## Evidence

Run the focused integration suite with the local environment:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_builtin_speech.py tests/test_face_workspace_gui.py tests/test_facial.py tests/test_live_speech.py tests/test_audio_mixer.py tests/test_audio_game_interchange.py -q --basetemp=build/builtin-face-final --junitxml=build/builtin-face-final.xml
```

The integration run passed **42 tests in 69.00 seconds**, with no failures
or skips. Screenshots from the actual widgets were inspected at 1120 × 820
and 870 × 650, including Creator, Audio and Lip Sync views. The compact-layout
test also verifies transport controls do not overlap the portrait.

Whole-workspace Ruff lint, formatting and mypy checks pass (504 Python files
formatted; 266 application modules type-checked). Review artifacts and JUnit
reports live under ignored `build/face-workspace-*`, `build/face-local-*` and
`build/builtin-face-*` directories.

The audible check used the actual FaceDialog Play button with its auto-loaded
example, an unmuted Qt audio output at gain 1.0, and the default
**Speakers (Realtek(R) Audio)** device. The 7.045-second playback decoded 164
buffers, including 105 with nonzero PCM, and reported no player error. The main
project identity and playhead stayed unchanged. Metadata is in
`build/face-local-audible/result.json`; no project source audio was attached.

A subsequent check used Rigora's actual Windows application identity without
adding a decoder monitor. The Windows endpoint meter rose from zero to 0.5163
during the complete English example. Rigora's Windows audio session reported gain
1.0 and mute off; the scene and playhead stayed unchanged. Evidence:
`build/face-native-output/result.json`. Windows master volume was found at 8%;
it was raised to 25% for the owner's requested audible check, and a short preview
was played again. No system microphone or loopback recording was opened.

## Review

Score: **9.0/10**, using equally weighted criteria: layout/readability **9.0**,
authoring correctness/undo **9.5**, audio integration **9.5**, platform validation
**8.0**. Findings about portrait framing, compact spacing, card deselection,
duplicate voice placement, decoder noise, delayed export, automatic example
loading, and transport isolation were fixed and
checked before completion.

Native validation was on Windows with offscreen Qt. Linux/macOS assets and UI
paths use shared portable code, but native device playback was not rechecked on
those hosts. Recognition quality depends on the recording and bundled English model;
example cues are estimates that remain editable. Creator expression/gaze/blink
cards do not synthesize unsupported controls: their existing Feelings/Eye pose
workflow remains in Object Editor. Detach clip audio removes all audio placements
in the active clip and retains source assets; individual removal uses Audio tracks.

Implementation references: [Qt audio output selection](https://doc.qt.io/qt-6/qaudiooutput.html),
[PocketSphinx decoder/model API](https://pocketsphinx.readthedocs.io/en/stable/pocketsphinx.html).
