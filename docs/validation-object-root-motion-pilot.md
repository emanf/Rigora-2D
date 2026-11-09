# Object-root Springs and Motion Pilot capture correction

Object Editor has a separate object/character root, but Spring assignment
previously treated every bone with `parent_id=None` as that anchor. Its first
real bone was therefore excluded from simulation. Object-owned first bones can
now receive Spring rules: the solver derives their driving parent frame without
inserting dummy bones or changing skeletal parenting. Their base joints remain
attached, with angular/axial response and normal descendant propagation.
Removing Scene-space driving transforms no longer overwrites their simulated
local pose. Existing unassigned/legacy root anchors remain unchanged until a
group or preset is reapplied. Standalone roots without a separate object anchor
retain the previous kinematic behavior.

Motion Pilot's Record button arms capture. Its viewport filter previously
consumed pointer input even before capture started, blocking ordinary selection
and focus while the user was still waiting to start. Armed input now passes
through normally. A full-width **Start recording / Start preview · Space** button
makes the second step explicit; it uses the same start operation as Space.
Pending profile edits are flushed before starting. During capture, pointer
movement drives the selected target without dragging its geometry. Space/Stop
finishes; Esc cancels. The leader selector stays locked for the armed take;
Cancel allows choosing another target.

Validation runs with `QT_QPA_PLATFORM=offscreen` and does not activate desktop
windows. `build/object-root-pilot-regression.xml` records **63 passing tests**,
covering new first-bone and real mouse/clock capture tests plus existing Spring
authoring/preview, roots, physics, activation, deterministic playback, selective
baking, native motion and persistence. Additional first-bone checks compare
skinned vertices through baking and exercise a nonuniformly scaled pivoted root.
Ruff lint/format and strict mypy pass.

Review score: **9/10**, based on root/attachment correctness, actual pointer
capture, preservation of authored data, baking/reload fidelity and UI clarity.
Physical pen hardware remains unverified; its position/press path is shared with
the existing Qt capture workflow. See [the guide](spring-and-motion-pilot.md).
