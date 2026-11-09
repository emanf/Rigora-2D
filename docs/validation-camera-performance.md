# Camera performance validation

Date: 2026-10-26. One implementation owner reviewed and tested this increment.
No physical camera or microphone was activated during validation.

## Review scores

| Review | Score | Evidence / findings |
| --- | --- | --- |
| 1 | 6/10 | Real local models detect faces/body poses, but checks found immediate Calibrate → Record failure and fractional-frame step timing. Both were fixed. |
| 2 | 8/10 | Preview, calibrated parent-relative angles, tracking-loss holds, atomic keys and simulated camera controls passed. Added source clip/workspace protection and synchronized microphone capture. |
| 3 | 8.5/10 | All five creator identities, camera/voice publication and undo, stale-frame rejection, model failure and hardware-release paths pass. Physical device/camera-format QA remains unperformed. |

Final criteria: canonical mapping/geometry 2/2, transactional ownership/undo 2/2,
real model inference 2/2, visible UI/lifecycle 1.5/2, hardware/platform coverage
1/2. This score does not imply full Adobe feature parity.

## Evidence

- `tools/review_camera_tracking.py --download` obtains official Google model/test
  fixtures under `build/camera-review`. Subsequent runs work without network.
  Actual MediaPipe 1.1.1 CPU inference produced 52 face coefficients and head tilt,
  plus 14 body-angle channels. A rotated input changed detected angles. No
  synthetic detector substituted for this model check; results are in
  `build/camera-review/results.json`.
- `tests/test_camera_tracking.py` uses real domain models, evaluators and vector
  parts. It checks all five creator identities, local rotation deltas, eye/mouth
  switching, unchanged bone lengths/meshes, preview isolation, tracking-loss holds,
  save/reopen equality and one-step undo.
- Headless `tracking_apply` uses the same implementation. Tests cover existing
  later keys, explicit start beyond the prior clip, malformed samples, sample
  limits, stale source revisions and selected-clip changes without project edits.
- Simulated device tests use actual Qt buffers/images, the bounded worker queues,
  the visible dialog and canonical imports. They check explicit Start, model
  failure before camera creation, calibration, recording, synchronized embedded
  voice and one-step undo. Physical OS devices are replaced at the boundary.
- The camera dialog screenshot was visually inspected for a neutral palette,
  readable controls, fitted content, chrome and clear active/disabled states:
  `build/camera-review/camera-dialog.png`.
- A 48-test regression group passed across capture, microphone, facial/audio
  interchange, media UI, editable exports and dependency/release checks. Results:
  `build/camera-review/regression.xml`. Lifecycle checks are subsequently re-run
  after the final ownership/device-release changes; overlapping counts are not
  added into a claimed distinct-test total.
  The lifecycle group passed 13 tests: `build/camera-review/lifecycle.xml`.
  Ten further checks passed for the actual menu route and shared automation/MCP
  interfaces: `build/camera-review/api-tests.xml`.

Source lint/format and strict mypy cover the modified application, tests, tools
and exporters. Two unrelated PNG asset helper scripts have separate style failures
in a whole-workspace lint invocation; they were not silently modified by this work.

## Limits

Actual camera formats, permissions, device unplugging and microphone latency
need physical hardware validation. Other platforms are not verified. Imported
model bundles are external local prerequisites, not runtime downloads. Capture
is bounded short-take planar retargeting. It does not implement 3D/finger tracking,
automatic turns, speech gesture inference, NDI/broadcasting or collision physics.
