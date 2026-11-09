# English voice example

`english-welcome.wav` is an original synthetic demonstration made locally for
Rigora, using the installed Microsoft Zira Desktop English voice. No recorded
human performance, third-party sample clip, or voice model is bundled.

Text: “Hello! Welcome to Rigora. Bring your characters to life, one frame at a time.”

The file is mono 16-bit PCM at 16 kHz. `english-welcome.cues` contains editable,
automatically estimated viseme timings from the actual audio, using Rigora's
offline PocketSphinx adapter. They are an example for review, not a claim of
perfect phoneme alignment. The last cue returns to Rest at the audio endpoint.

Both files are application assets and work offline on Windows, Linux and macOS.
The runtime does not need Windows speech APIs, a synthesizer or a speech model
to load or key this example.

Developers can regenerate it on Windows with the optional `speech` dependencies
installed: `powershell.exe -NoProfile -File tools/generate_english_voice.ps1`.
This utility writes files without playing sound. Use `-Voice` to select another
installed English voice; inspect the new cues before distributing the result.
