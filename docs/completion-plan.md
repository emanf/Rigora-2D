# Completion work — 2026-11-01

Owner authorized completing the outstanding work and choosing established animation
application conventions without waiting for optional answers. Work remains single
agent, source-only, with offscreen/hidden native validation. No Rigora executable
bundle is rebuilt. Checkboxes require working behavior and recorded evidence.

- [x] Timeline action icons: short, centered vertical frame marks above/below each
  appearance/view/camera key and motion endpoint; preserve editing and theme contrast.
- [x] Unity: execute updated editable import, skinning, texture/wardrobe switching
  and event playback in the installed 6000.6.4f1 Editor; fix findings.
- [x] Unity: sampled scene-camera/cuts, lens/backgrounds and particle playback with
  explicit opt-out for use under a game's own camera; verify native behavior.
- [ ] Unreal: equivalent adapter behavior and target-engine validation when the
  actual toolchain is available. Launcher discovery currently lists no engine.
- [x] Real-time local speech-driven mouth preview and editable recording, with
  explicit microphone Start/Stop and clean device/error lifecycle.
- [x] Optional audio-reactive head/brow gestures and authored camera turn detection.
  Semantic gesture inference and generated rear views are not claimed.
- [x] Movement-driven authored-view/layer switching through shared animation services.
- [x] Static world-ground particle collision and magnet controls with deterministic seeking.
  Arbitrary artwork/particle-particle collision is not implemented.
- [x] Puppet Stage audio/replay integration with ordinary editable takes.
  Replays reference project-local actions. Mix nested looping replay audio to WAV
  before capturing another replay; flat voice/music tracks retain rate/loop controls.
- [x] Explicit local broadcast output lifecycle and documented integration routes.
- [x] Audit interoperability gaps against published/vendor-supported formats;
  retain honest limitations for unsupported native project formats.
- [x] Final local audit: resolve actual findings, focused regressions, static checks,
  documentation and numeric review criteria. Native OS/device/platform coverage
  must not be implied by offscreen or mathematical tests.

Existing baseline: full run 1,381 passed / 11 failed / 1 skipped; all eleven failures
were subsequently fixed and pass together in build/final-resolved.xml. Do not add
overlapping counts or call that a fresh passing complete-suite run. See
[prior evidence](production-workflow-plan.md).

Discovery update: Unity Hub's editors-v2.json is empty, but the actual Editor exists
at C:/Program Files/Unity/Hub/Editor/6000.6.4f1/Editor/Unity.exe with matching product
version. Validate the binary directly; registry absence is not installation absence.

## Completed review and evidence

Timeline marks: **9/10** for exact frame anchoring, compact 24-pixel-row fit,
dark/light selected contrast and preserved editing. Seven existing action/view
interaction tests pass in build/action-tick-check.xml; visually checked
build/timeline-action-ticks.png. Real high-DPI displays remain separate coverage.

Unity: **9/10** for native geometry/appearance, deterministic callbacks, camera
projection/cuts, particle placement/scale, ownership/cleanup and actual pixels.
Seventeen focused export checks pass in build/unity-parity-tests.xml. Real Editor
6000.6.4f1 executed tools/engine_validation/RigoraSceneValidation.cs successfully
in hidden batch mode (build/completion-unity/native-scene-final.log). Native BakeMesh
vertices match canonical evaluation, with real blended weights and corrections.
An image comparison found and fixed a 100× particle scale defect. The corrected
GPU render passes the runnable --check-render command in prepare_unity.py: mean
RGBA error [0.157, 0.167, 0.174, 0.0]/255 at 256 × 144 after correcting alpha
composition too, recorded in
build/completion-unity/render-validation.json. The supplied shaders target Unity's
built-in renderer; URP/HDRP and other operating systems are not validated here.

Local speech, camera turns, movement views and particle forces: **8.5/10** with
criteria, bounds and concrete coverage in [live-speech.md](live-speech.md) and
[production-workflows.md](production-workflows.md). Eight speech/face checks,
20 movement/turn/view checks and 15 final authoring UI/particle/movement checks
pass in their recorded reports; groups overlap. No microphone/camera was opened.

Puppet Stage: **8.5/10** for transient preview, editable replay actions, synchronized
rate/loop audio, voice-only capture, atomic Undo, retry/discard and stale-result
protection. Fifteen affected checks pass in build/puppet-replay-final.xml, including
real PCM mix comparisons and simulated offscreen microphone capture. Fixed recorded
replays selecting the wrong Scene timeline and incompatible catalog actions being
listed as compatible. Replays are project-local; nested audio loops need an explicit
WAV mix first. Real capture hardware and cross-platform playback remain unverified.

Local output: **8.5/10**, criteria and evidence in [local-broadcast.md](local-broadcast.md).
Two HTTP/UI checks pass in build/broadcast-check.xml; native offscreen WebEngine
decoded the actual page and confirmed alpha 0/255 in build/broadcast-browser-review.json.
Visual review used real Segoe UI metrics for offscreen Windows; broadcast, audio,
particle physics and Puppet dialogs have readable neutral layouts without clipped
controls. No actual OBS stream or audio routing was claimed.

Interoperability review: **8/10** with scope/criteria in
[adobe-interoperability.md](adobe-interoperability.md). Native Adobe projects and
Unreal scene playback remain unsupported; this audit does not mark them implemented.

## Final affected-source validation

`build/completion-integration.xml`: **70 passed**, no failures/errors/skips, 94 seconds.
This covers affected rendering/export, timeline actions, face/speech, camera turns,
movement/physics, local output and authoring UI paths. It is not a complete-suite run.
Final review then found and fixed preview restart/late-discard cleanup and replay
audio phase/context edge cases. Follow-ups pass **16** teardown checks in
`build/completion-teardown.xml`, **17** audio/replay/spring checks in
`build/completion-audio-phase.xml`, and **16** API/audio/automation/MCP checks in
`build/completion-audio-api.xml`. These reports overlap; do not sum them.

Ruff lint passes, Ruff format checks 677 files, and mypy checks 258 source modules.
Native Unity/PNG and offscreen browser evidence above remains separate from pytest.
No Rigora executable bundle was rebuilt and no physical camera/microphone was opened.

Final local review: **8.5/10**, criteria are working UI/readability, exact frame and
audio timing, shared evaluation, editable/undoable data, deterministic seeking,
resource/worker teardown and honest adapter boundaries. Remaining actual limits:
Unreal scene playback/toolchain validation is blocked without a usable installed
engine/SDK; Adobe native projects, NDI/Syphon, semantic gestures, arbitrary collision
geometry and cross-platform/device QA remain unsupported/unverified as documented.
