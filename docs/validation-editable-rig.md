# Editable rig and microphone validation

Date: 2026-10-26. Implementation, review and fixes were performed in the current
chat with one implementation owner. Native review fixtures are disposable.

This is the historical validation of that increment. For the 2026-10-30 runtime
and format additions, see [production workflow status](production-workflow-plan.md)
and [current engine capabilities](game-engine-export.md). Current Godot packages
have headless execution checks; the updated Unity/Unreal adapters need new native
validation. Animated source/palette changes now retain texture variants. Remaining
feature gaps below describe the earlier increment, not the current feature list.

## Criteria and scores

Scores describe this increment, not complete Adobe parity or production readiness.

| Review | Score | Evidence and findings |
| --- | --- | --- |
| 1 | 7/10 | Canonical geometry reconstruction and native Godot imports passed. The disposable Unity test project lacked built-in modules; its fixture setup was repaired. |
| 2 | 8.5/10 | Native Unity skinned vertices, bones, clothing, color and timing passed; Godot passed; Khronos validator reported zero errors/warnings. Texture orientation and package budgets were checked. |
| 3 | 9/10 | Geometry, native Unity/Godot, wardrobe/color and microphone checks pass. Fixed duplicate transparent Unity faces and retained/released material instances. Unreal native execution remains unverified. |

Final criteria: canonical geometry 2/2, native Unity/Godot 2/2, runtime clothing
and color 2/2, audio/undo 2/2, engine deployment coverage 1/2. This is an export
increment score, not a score for all remaining feature groups.

## Verified contracts

- All three editable format packages retain bones, native hierarchy, up to four
  influences per vertex, separate textured meshes, morph corrections, original
  artwork and source-project metadata. Authored project/history remain unchanged.
- Tests independently decode GLB accessors and reconstruct hierarchy, skinning
  and morph vertices at three poses, comparing every vertex against Rigora's
  canonical evaluator. A separate two-bone fixture exercises true blended weights
  and nonlinear correction, beyond a rigid single-bone character.
- Wardrobe metadata preserves default selections, variants and skin coverage.
  Runtime wrappers expose per-category selection/removal and independent colors.
- Native Godot 4.7.2 checks Skeleton3D bones, changing animation poses, separate
  MeshInstance3D parts, garment removal, independent red tint and a fitted preview
  camera. The supplied rig scene stays camera-free for use in an existing game.
- Native Unity 6000.6.4f1 imports a prefab, editable AnimationClip, weighted Mesh
  and SkinnedMeshRenderer parts. The check uses BakeMesh at three times and
  compares native world-space vertices with canonical expectations. Native
  wardrobe/color and exact duration checks run in the editor.
  Both a full character and a genuinely blended two-bone mesh pass native vertex
  comparisons. UV orientation and single-face transparent geometry are checked.
- Khronos glTF Validator 2.0.0-dev.3.10 reports zero errors and zero warnings on
  the exported character. Validation does not use Rigora's importer.
- PCM capture starts only on explicit Record. Stop/Discard/close release input;
  failed publication retains stopped samples for retry. Imported recordings are
  bounded, embedded and undoable through the same service as file imports.
  Tests use fake devices with real Qt buffers; no physical microphone was opened.

## Reproducible evidence

`tools/review_editable_rig.py` produces the original character and blended-skin
fixtures in `build/editable-rig-review`. Native check sources are in
`tools/engine_validation/{editable_rig.gd,RigoraEditableValidation.cs,validate_gltf.cjs}`.
The existing disposable Unity fixture is in `build/audio-interchange/unity`.
Editor logs and completion markers retain results; process launch alone is not
counted as validation.
Final native Unity log: `build/editable-rig-review/unity-material-final.log`.
Success markers: `build/audio-interchange/unity/{EditableRig,EditableWeighted}-validation.txt`.

The final focused regression run passed 43 tests across editable rigs, microphone
capture, audio/media interchange, output, GUI media controls and release
reliability. See `build/editable-rig-review/tests-final.xml`. These overlap prior
audio checks and must not be added into a claimed unique-test total.

## Remaining limits

These are planar 3D rigs rather than native 2D bone systems. Original vectors
are retained but engines use portable PNG textures. Constraint/FFD solvers are
sampled into animation; source definitions remain in the original project.
Arbitrary animated source/palette swaps reject explicitly. One action per export.

No Unreal installation/SDK is available. Interchange importer and Blueprint plugin
source are supplied, but Unreal compilation and runtime behavior have not been
verified. Unreal audio requires manual integration. Unity's bundled shader targets
the built-in renderer; URP/HDRP materials require adaptation.

Microphone speech recognition is record-then-analyze. Subsequent local camera
performance capture is documented in `camera-performance.md` and
`validation-camera-performance.md`. Speech-driven gestures, collisions/particles/
magnets, movement-driven layer switching and broadcasting remain missing groups in
`character-animator-comparison.md`. This work does not claim complete Adobe parity.
