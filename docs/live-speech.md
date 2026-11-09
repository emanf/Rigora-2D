# Live local lip-sync

The GUI installation includes speech recognition: `uv sync --locked --extra gui`.
The `speech` extra remains available for headless clients and older setup commands.
PocketSphinx 5.0.4
supplies a native Python 3.12 Windows wheel and bundled acoustic/phone models.
The recognizer does not download anything during capture or send audio anywhere.

Open **Animation → Face & Lip Sync**, choose a supported face/creator mouth rig,
then enable **Live phonemes**. **Record** explicitly opens the
chosen input. Provisional phonemes drive a scratch preview without changing the
project. Optional **Audio-reactive head and eyebrow gestures** follow voice energy
and rhythm; they are not semantic gesture prediction. Independent brows must
exist in the target rig; creator mouths retain their existing proportions.

**Stop & keep** releases the input, drains queued recognition, then
embeds the WAV and creates ordinary mouth visibility keys with synchronized clip
audio in one Undo step. The cue editor remains available afterward. Optional
gesture keys return to the original pose at the end. **Discard take** or
closing the dialog releases the device and drops unpublished data.

The bundled acoustic model is US English. Provisional phones can change as more
audio arrives, so final keys can differ from the last live shape. Use the cue
editor or the built-in **Analyze speech locally** workflow for corrections. This is phoneme
recognition, not an energy-only jaw approximation or a transcript service.

Recognition runs on a worker with at most two seconds of pending PCM and one
pending preview. If recognition falls behind, the device stops and retains the
captured voice. Disable Live preview to keep raw audio, or discard and retry.
Project/scene/clip/context changes reject publication of stale takes. Bounds are
5,000 mouth cues, 5,000 optional gesture samples and the existing 16 MiB / 30-minute
PCM bound. The byte limit can shorten capture below 30 minutes at higher rates.

Validation: the actual native decoder processed CMU's official `goforward.raw`
fixture locally, producing multiple distinct provisional/final mouths in 0.14
seconds for 2.79 seconds of audio. Silence, odd chunk boundaries, ten-second
decoder resets, worker stop/restart, transient preview, synchronized voice/keys,
stale take rejection and one-step Undo pass in
`build/live-speech-integrated.xml` (eight checks including the existing face UI).
Tests inject PCM and do not access microphones/speakers. Physical devices,
other operating systems and recognition quality across accents remain unverified.

Review: **8.5/10**, judged on offline recognition, responsiveness/bounds, editable
results, undo/ownership, device lifecycle and useful failure recovery. The remaining
limits are the bundled acoustic model and physical-device/platform coverage.

References: [PocketSphinx decoder API](https://pocketsphinx.readthedocs.io/en/stable/pocketsphinx.html),
[official test recording](https://github.com/cmusphinx/pocketsphinx/blob/main/test/data/goforward.raw).
