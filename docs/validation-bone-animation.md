# Current-frame bone animation and playback cap

The former bone-selection route activated rig interaction and rendered frame-zero
rest data while disabling transport. Bone interaction now follows the shared
animation session. Posing an existing clip or using Auto key solves from evaluated
local transforms, then writes changed scalar channels into a scratch timeline.
Only its timeline/clip delta is committed. Rest skeletons, attachment/bind geometry
and constraint definitions remain unchanged. IK endpoints record their control
target transforms. Selection and inspector fields follow the current frame;
scrubbing cancels gestures that belong to an earlier frame. Unsupported-clip
recovery and transient selection after undo remain guarded.

New scenes use inclusive end frame 120. The numeric End field and ruler flag edit
the active clip's range or the unkeyed scene range. Flag movement is transient;
release is one undo step. Keys outside a shortened cap are retained and shown in
a shaded area. Saved ranges are used by the normal evaluator and transport.

Validation: 45 rig/timeline/animation/mesh GUI regressions passed; all five new
domain/UI cases passed, including current-frame IK keying, root anchoring,
save/reopen, numeric caps, end-flag dragging and free scrubbing/playback. Ruff and
strict mypy pass. Logs are under `build/maintenance/bone-animation-*.log`.
