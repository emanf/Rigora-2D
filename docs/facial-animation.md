# Facial animation, audio and offline lip-sync

New creator characters and rebuilt human/original-cast library characters include
ten separate speech mouths. Select the character at the top of **Animation →
Face & Lip Sync**. For older creator projects, choose **Face → Rig setup →
Enable character speech**. This preserves the existing Rest mouth, geometry and binding, with
one Undo step. Older mouth bounds that cannot be converted safely require a
creator rebuild. Creator characters retain Eye pose variants for blinking;
the standalone full face rigs below also support scalar gaze/brow/blink controls.

Create a free vector face or attach it to a
head bone. Ten original CC0 SVG mouth shapes, eyes, pupils and eyebrows are
embedded into the project. All parts remain ordinary replaceable scene objects
and meshes. A constraint makes attached faces follow the bone.
Attachment retains an upright initial face even when the head bone's rest axis
points upward; later bone rotation carries the face with it.

The portrait remains visible beside **Face**, **Audio** and **Lip Sync** tabs.
Creator portraits show the actual head artwork and bound mouth meshes, including
deformation and appearance changes. Full face rigs have a neutral gray oval
behind their floating facial parts for preview only; this backing is not exported.
The expression and mouth cards use the bundled vector shapes, with example
pronunciations in mouth tooltips. Click a card to audition a scratch pose;
repeated clicks keep its selected outline. No keys are created by previewing.
The portrait and its transport belong to this window: Play, Pause, Stop and
waveform scrubbing never play or seek the main scene, even after applying speech.
Previewing expression cards also stays inside the window.
Playback follows the audio player's device clock. Portrait refreshes do not
repeatedly seek or restart the voice decoder. **Audio → Preview output** shows
the default physical output and lets you choose a speaker or headset; the choice
is saved. A disconnected selection produces a visible error instead of silently
playing elsewhere. Preview Volume/Mute affect Rigora's output, while Windows/macOS/
Linux system volume and per-application mixer controls still apply.
Gaze X/Y and blink amount are under **Eyes & gaze**. **Key pose** creates one undoable group of scalar keys at
the current playhead. Add blink inserts open/closed/open keys over six frames.
Change the keys in the normal timeline to adjust timing and intensity.

**Import WAV** stages valid PCM WAV audio locally and displays an approximate sampled
peak waveform with mouth cue markers. Click the waveform to scrub this preview;
click near a cue to select its time and mouth. **Lip Sync → Mouth timing** has
visual mouth selection and time fields: **Set cue** inserts/replaces a draft event,
and **Remove cue** removes the event at that time. **Edit cue text** expands the
optional `seconds, phoneme` editor for ARPAbet (stress digits accepted) or mouth
names: Rest, AI, E, O, U, FV, L, MBP, WQ, TH. Invalid text is preserved for correction.
**Preview cues** auditions draft timing in the portrait while scrubbing or playing;
the document and its main-scene animation remain unchanged until keying.
**Key mouth cues & audio** creates exclusive step visibility keys. Cue times
are relative to **Start frame** when applied. Preview always starts at source time zero;
the Start frame field only controls placement into the scene. Choose an embedded audio source or load a WAV,
set start, volume and mute, and **Attach voice to timeline**. Timeline playback, seeking,
looping, speed and clip/document switches synchronize the embedded audio.
Staged audio is copied to the project only by Attach or Key mouth cues & audio.
Opening the window, trying the example and importing a preview WAV leave the
project's assets and undo history unchanged.
**Detach clip audio** removes the active clip's audio associations, including other
mix tracks, while retaining their embedded sources. **Manage audio tracks…** opens
the existing mixer for independent voice, sound and music placements. Repeated
voice attachment updates one voice placement while preserving other mix tracks.
Key mouth cues saves keys and timing in one Undo
item. Reopening the dialog restores the selected clip's source and controls.
Unknown phonemes reject the entire operation. Moving/copying/deleting normal
timeline keys edits lip-sync timing. Earlier/later mouth keys are retained.

Suggest energy cues offers local open/rest jaw timing, **not automatic phoneme
recognition**. Precise mouth shapes require authored or externally prepared
phoneme cues, or the optional local recognizer below. Waveform
analysis supports uncompressed PCM WAV up to 16 MiB; audio import supports up to
30 minutes and the normal source-byte limit. Clip playback uses Qt Multimedia;
up to 32 independent tracks per clip can mix during playback and video export.
Decoder/device errors appear below the controls.
Tests cover visible vector switching, bone attachment, blink/gaze, invalid cues,
local waveform analysis, desktop preview, persistence and undo.

## Record a microphone

Choose an input device in **Audio → Microphone**, then **Record**. Capture starts only after
that action. **Stop & keep** stops the device and embeds a PCM WAV
as one undoable imported source. Select that recording, attach it to the clip,
and analyze/key it using the same workflow as imported audio. **Discard take**
or closing the dialog releases the device and drops uncommitted samples.
If import fails, the stopped recording remains available for retry. A disconnected
selected device produces an error instead of opening a different microphone.

Recording is bounded to 16 MiB or 30 minutes, whichever comes first, in supported
mono signed 16-bit PCM. At 16 kHz this permits about eight minutes. This is
record-then-analyze speech by default. **Live phonemes · US English · offline**
enables built-in local PocketSphinx preview and recording; see [live speech](live-speech.md).

## Try the English example

The English example loads automatically when the window opens without an attached
voice, including the first opening in a new project. Saved attached voice takes
priority. **Audio → Voice track → English voice example** restores the example
at any time. This stages an original spoken welcome and loads its transcript and editable estimated mouth
timings. The approximately seven-second mono PCM recording works offline on all
platforms without a recognizer or synthesizer. Press the portrait's **Play** button
to hear it immediately, with no scene attachment or character required. Volume
and Mute affect this local output. Scrubbing auditions the loaded draft mouth cues
in the portrait. To retain it, choose a face and start frame, then **Key mouth cues
& audio** saves animation and voice together. **Attach voice to timeline** applies
only the voice. Application reuses an identical embedded source by content digest.
Closing stops playback and discards unapplied preview audio and edits.
You can replace this recording with imported English speech or another language.
See [audio asset provenance](../assets/audio/README.md) for generation details.

## Automatic speech analysis

**Lip Sync → Speech recognition → Analyze speech locally** uses the built-in
PocketSphinx acoustic/phone model. The GUI dependency set and desktop bundles
include the engine and its model data; no Rhubarb installation, executable path,
download or account is required. Analysis runs on a cancellable worker with a
five-minute limit and a thin progress indicator. Results remain editable draft
cues until **Key mouth cues & audio** is pressed.

PCM WAV formats supported by the audio importer are converted to mono 16-bit
16 kHz in small blocks for the model. This includes 8–192 kHz input, 1–8 channels,
and 8/16/24/32-bit integer PCM, within the 16 MiB/30-minute source limits.
Audio stays on the computer. Reference text is for the author; this built-in
phoneme detector uses audio and does not perform transcript-constrained alignment.
The bundled acoustic model is US English. Other languages, accents, noisy voices
and overlapping speech may need substantial cue correction.

The Python API/CLI `speech_analyze` operation uses the same built-in service by
default. Explicit host-configured Rhubarb integration remains available for older
automation clients; it is not a setup requirement in the face window.

## Camera performance

**Animation → Camera performance…** previews calibrated local face/head/body
controls and records editable keys. **Record microphone with this take** embeds
synchronized voice when keeping the take. Camera mouth poses follow visible
facial movement; built-in speech analysis provides the separate audio-based phoneme workflow.
See [camera setup and recording](camera-performance.md).

## Video and automation

**File → Render & export… → Include clip audio** muxes attached audio into MP4,
WebM, MOV and FFV1 video using configured FFmpeg. Start, volume and mute are
honored; audio is trimmed/padded to the sampled duration. Consecutive samples at
output FPS are required; disable audio for arbitrary sample orders. Images and
game sprite packages carry visual animation only.
Editable rig packages retain the WAV and timing; Unity and Godot wrappers can
synchronize it with the exported native animation. Unreal receives audio source
and timing metadata for manual integration.

Shared Python/CLI/MCP operations include `audio_import`, `audio_attach`,
`audio_detach`, `face_enable_character`, `speech_analyze` and `lip_sync_set`.
Trusted hosts pass `speech_analyzer=Path(...)` to RigoraAPI; CLI/MCP startup accept
`--speech-analyzer`. Operation arguments cannot choose executables. Analysis
returns cues without keying them. `frame_render`/`render_submit` accept
`include_audio=False` for explicit silent output.
