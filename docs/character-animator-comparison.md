# Adobe Character Animator comparison

Reviewed 2026-10-26 and updated 2026-11-01 using Adobe's official help and local source/UI.
“Partial” means a related working feature exists, not Adobe compatibility.
Adobe artwork, models and motion libraries were not copied.

Rigora's production workflow update on 2026-10-30 adds editable foot contacts,
masked Override/Additive layers and crossfades, typed events, deterministic vector
particles, game regions, motion paths, camera shot planning and state-machine
preview. See [current production workflows](production-workflows.md). The table
below includes offline streaming phonemes, audio-reactive gestures, camera turns,
movement views, ground/magnet particles, replay/audio integration and local browser
output. Godot and updated Unity packages have current native checks; Unreal
runtime execution remains unverified. See [completion evidence](completion-plan.md)
and [format boundaries](adobe-interoperability.md).

| Workflow | Rigora status after this increment |
| --- | --- |
| Imported voice and editable lip-sync | PCM WAV embedding, explicit microphone recording, waveform, timed visemes and Undo. Optional offline streaming phonemes provide transient preview and synchronized editable speech takes. Local Rhubarb analysis remains available. |
| Photoshop artwork | Basic PSD/PSB pixel layers/groups and offsets; masks bake into pixels and originals are preserved. Advanced effects and full editing fidelity remain partial. |
| Illustrator artwork | PDF-compatible AI artboards render as transparent images with explicit acknowledgement; original AI stays embedded. Private layers/native vector editing remain missing. Exported SVG preserves vectors. |
| Expressions, blink and gaze | Full face rigs support keyed controls and local camera gaze/brow/blink capture. Creator characters have coordinated feelings, eye poses and speech mouths; camera controls drive visible mouth poses and eye variants. |
| Live head/face/body tracking | Optional local MediaPipe models, explicit Start/Stop, calibration, smoothing, confidence filtering, editable takes and synchronized voice. Head yaw can select existing Front/3/4/Side views with hysteresis. This is not 3D mocap or finger tracking. |
| Keyboard triggers and recorded performances | Puppet Stage motion/FFD/effect and project-local action/replay cards, scoped hotkeys, scratch previews and editable recording with voice. Replay audio supports rate, repeat and end limits. Nested audio loops need an explicit WAV mix. |
| Layer switching | Wardrobe/skin variants, visibility keys, eye/hand poses and sequences. Shared movement-driven Object views use authored slots; explicit View keys take priority. Arbitrary Adobe auto-swap behaviors are not imported. |
| Turnarounds | Five creator views and editable Object views. Optional calibrated camera turns select authored Front/3/4/Side; missing/rear artwork is not synthesized. |
| Locomotion and gestures | Original stand/walk/run actions and retargeted motions exist. Adobe's proprietary motion library is not included. |
| Secondary movement | Springs/baking and deterministic vector particles with static ground collision, bounce/friction and attract/repel magnets. Arbitrary artwork/particle-particle collision is not implemented. |
| Handles and rigging | Bones, FK/IK, pins, mesh deformation and custom FFD exist. Adobe layer tags/automatic puppet attachments are missing. |
| Animation editing | Keys, curves, clips, editable performances, expressions and visemes exist. Adobe take/lane editing is not replicated. |
| Speech-driven gestures | Optional editable audio-reactive head/brow motion follows voice energy/rhythm. Semantic gesture inference is not implemented. |
| Rendered video/audio | Transparent sequences, animated images and configured FFmpeg video exist; video now includes synchronized clip audio. |
| Broadcasting/Adobe projects | Transparent local browser-source output with explicit lifecycle and separate audio capture. NDI, Syphon, Dynamic Link and .puppet/.chproj conversion remain absent. |
| Requested game exports | Baked sprite packages and editable planar rigs for Godot, Unity and Unreal. Editable rigs retain bones, skin weights, separate meshes, morph animation and runtime wardrobe metadata. Unity/Godot native checks passed. Unreal runtime plugin/importer source is supplied but native execution remains unverified. Constraints/FFD are sampled, rather than editable engine solvers. |

The audio/interchange work adds audio playback/timing, local recognition,
microphone recording, creator speech mouths/legacy conversion, video audio muxing,
AI artboard import, game sprite packages and editable rig packages. Both export
modes are supported. Remaining missing/partial rows stay in the accepted scope;
they are not implemented features.
Current limits are documented in [live speech](live-speech.md),
[local output](local-broadcast.md), [production workflows](production-workflows.md)
and [Adobe interoperability](adobe-interoperability.md). Native Unreal scene playback
still requires an installed engine/SDK; unsupported routes stay blocked by preflight.

Official references:

- [Adobe behaviors](https://helpx.adobe.com/adobe-character-animator/desktop/behaviors/behaviors.html): behavior inventory.
- [Artwork preparation](https://helpx.adobe.com/adobe-character-animator/desktop/creating-and-controlling-puppets/prepare-artwork.html): PSD/AI structure, tagging and attachments.
- [Mouths and lip-sync](https://www.adobe.com/learn/adobe-character-animator/web/lip-sync-mouth-shapes): audio-based visemes and editing.
- [Triggers and controls](https://helpx.adobe.com/adobe-character-animator/desktop/creating-and-controlling-puppets/triggering-and-controlling-puppets.html).
- [Physical simulations](https://helpx.adobe.com/adobe-character-animator/desktop/behaviors/learn-more-about-behaviors/physical-simulations.html).
- [Recording](https://helpx.adobe.com/adobe-character-animator/desktop/recording-and-playback/record-and-playback.html), [exports](https://helpx.adobe.com/adobe-character-animator/desktop/export-projects/export.html), [streaming](https://helpx.adobe.com/adobe-character-animator/desktop/export-projects/streaming.html).

Local evidence: `application_services/{facial,audio,asset_pipeline,output,characters,dynamics}.py`,
`application_services/{rig_export,recording}.py`, `docs/workspace-and-performance.md`,
`docs/validation-audio-interchange.md`, `docs/validation-editable-rig.md` and
`docs/validation-camera-performance.md`.
