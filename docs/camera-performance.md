# Local camera performance

Open **Animation → Camera performance…**. Camera preview and recording require
the optional tracking dependency and compatible local model files. No camera or
microphone opens merely by opening this dialog. Inference stays on the computer;
Rigora does not download models or send frames to a server.

## Setup

Install all configured extras using `uv sync --locked --all-extras`, or include
`--extra tracking` alongside the other extras you use. The lockfile pins
MediaPipe 1.1.1. Obtain compatible Face Landmarker and/or Pose Landmarker `.task`
bundles from Google's official guides, retain them locally and select them with
**Choose…**. A model is optional when its corresponding tracking checkbox is off.
Files must be at most 64 MiB. Wrong/missing models fail before the camera opens.

- [Face Landmarker guide and model](https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker).
- [Pose Landmarker guide and models](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/index).

Task bundles and sample images used for development stay under `build/`; they
are not packaged as Rigora artwork or a hidden dependency on a developer path.
The model locations selected in the dialog are remembered in local preferences.

## Preview and record

1. Choose a creator character, full face rig, or matching human skeleton and the
   desired camera. Enable face/head and/or body tracking, with its local model.
2. **Start preview** loads the models off-thread, then opens the chosen camera.
   Hold a neutral pose and press **Calibrate**. The initial detected pose also
   provides a default neutral. Calibration never changes the character's rig.
3. Move to preview. **Smoothing** filters scalar controls; visibility switches
   remain stepped so only one mouth/eye variant is shown. Each frame is evaluated
   through Rigora's normal bone/skin/deformation pipeline.
4. Optionally enable **Record microphone with this take** and choose a microphone.
   **Record** starts retaining controls and, if selected, opens that input. Voice
   and body controls share a monotonic recording clock. In-flight frames captured
   before Record are skipped rather than keyed before the take's start.
5. **Stop and keep take** releases hardware first, prepares keys off-thread, then
   commits against the captured project/clip/workspace revision. A kept voice WAV
   embeds and attaches to the clip at the take's start. Everything is one Undo.
   The final pose holds until Stop; existing keys outside captured intervals survive.
6. **Discard / stop preview** or closing the window stops both devices and drops
   unpublished data. Switching projects, clips or animation contexts stops capture
   and prevents a take from being written into a different target. Failed
   publication retains stopped samples for retry while the source remains valid.

Recordings contain up to 600 observations / 30,000 scalar keys. Capture processes
at most 15 frames per second at 640 × 480; it keeps one pending frame and one
result, dropping stale input when detection is slower. This is a short-take
workflow, not unlimited multitrack recording. Microphone recording also has the
16 MiB / 30-minute bound documented in the facial/audio guide.

## Supported controls and limits

All five original creator identities support head tilt, calibrated limb rotation,
exclusive visible mouth poses and Open/Closed eye variants. Full separate face
rigs also support continuous eyelids, pupil gaze and eyebrows. Calibrated body
angles map by canonical bone names (`hips`, `spine`, `upper_arm.L/R`,
`forearm.L/R`, `hand.L/R`, `thigh.L/R`, `shin.L/R`, `foot.L/R`). Parent motion is
subtracted before applying local joint rotation, retaining proportions and skin
weights. Attached custom full faces can use their explicit parent bone for head tilt.

Body segments with landmark presence/visibility below 0.6 are omitted; missing
regions keep the last local controls. Single-person face/pose detection uses
the model's confidence gates. Input is unmirrored and left/right names refer to
the detected subject. Recalibrate after changing camera position or neutral pose.

This captures planar rotation, not 3D motion, finger articulation, root travel,
depth turns, foot contacts or continuous view synthesis. Creator gaze/brow artwork
is not split into independent scalar controls. Camera mouth selection uses visible
jaw/pucker/funnel/press/smile movement, not phoneme recognition. A kept WAV can
subsequently use the local Rhubarb workflow for audio-based visemes.

Optional **Switch authored Object views from head turns** reads calibrated face
yaw and records ordinary held `object.view` keys. It requires existing nonempty
Front, Front 3/4 and Side Object views in the main Scene. It never fabricates
missing artwork or infers rear-facing views. Both turn directions use those
authored slots. Hysteresis changes Front → 3/4 above 25°, 3/4 → Side above 65°,
and returns below 15°/55° respectively, reducing threshold flicker. Turn keys
remain discrete even when other tracking controls use smoothing. Expressive
controls continue to target the explicitly mapped facial rig.

For audio-driven mouth preview while recording voice, use the separate
[live lip-sync workflow](live-speech.md). Camera mouth tracking remains visual.

Python, CLI and MCP can supply local observations through `tracking_apply` with
`target_id`, up to 600 `samples` (`seconds`, `face`, `angles`), optional `start`
and `smoothing`. It uses the same calibrated retargeter and canonical keys without
accessing hardware or loading a client-specified model/executable. The first
observation is neutral; capture timestamps must strictly increase.

See [validation and review scores](validation-camera-performance.md).
