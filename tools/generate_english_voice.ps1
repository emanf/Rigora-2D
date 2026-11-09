# Regenerate the original English demonstration as a silent, offline file operation.
# Development utility only: Rigora reads the bundled WAV/cues on every platform.
param([string]$Voice = 'Microsoft Zira Desktop')
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$audioDirectory = Join-Path (Split-Path $PSScriptRoot -Parent) 'assets/audio'
$synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synthesizer.SelectVoice($Voice)
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(
        16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synthesizer.SetOutputToWaveFile((Join-Path $audioDirectory 'english-welcome.wav'), $format)
    $synthesizer.Speak('Hello! Welcome to Rigora. Bring your characters to life, one frame at a time.')
} finally {
    $synthesizer.Dispose()
}
# Decode the actual samples: synthesizer event offsets can differ from written PCM timing.
$projectPython = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv/Scripts/python.exe'
@'
import wave
from rigora.infrastructure.live_speech import LivePhonemes
from rigora.resources import asset_path
with wave.open(str(asset_path('audio/english-welcome.wav')), 'rb') as source:
    decoder = LivePhonemes(source.getframerate())
    while block := source.readframes(1600):
        decoder.feed(block)
    sample = decoder.close()
asset_path('audio/english-welcome.cues').write_text(
    '\n'.join(f'{time:.5f}, {mouth}' for time, mouth in sample.cues) + '\n', encoding='utf-8'
)
'@ | & $projectPython -
if ($LASTEXITCODE -ne 0) { throw 'Cue analysis failed; install the speech extra before regenerating.' }
