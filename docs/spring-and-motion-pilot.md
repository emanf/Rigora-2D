# Spring Dynamics and Motion Pilot

Spring Editor adds secondary motion to existing rigs. Motion Pilot drives primary
movement with mouse or pen input. They work separately or together, using normal
project animation, Undo/Redo and export.

## Author Spring groups

1. Select your character or rig and open **Rig → Spring Editor** or its toolbox
   icon. The existing Object Editor workflow remains available.
2. Use **+** beside Groups. Double-click a custom group to rename it. The palette
   icon sets its viewport color; it does not recolor artwork.
3. Select bones on stage or in the expanded group tree. **Include child bones**
   determines whether descendants join the selection. Click **Assign to Group**.
   The object root anchors the rig, so its first bone can also spring around its
   fixed base joint. Standalone rigs without a separate object root retain a
   kinematic first bone. A bone belongs to one group;
   reassignment removes former membership and adopts the new group's keys.
4. Choose a preset, then tune properties. Presets are starting values, not a
   mode that prevents manual editing. Type a project custom preset name and use
   **Save custom**; **Apply** restores it. Reapplying Default resets physical
   values. All these edits support Undo.
   For an existing group whose first bone was previously an anchor, reapply the
   preset once to enable that bone; saved legacy assignments are preserved until
   edited.
5. Expand **Bone display** to adjust width, opacity and connection silhouettes.
   Group colors and selection are viewport overlays. Closing the editor releases
   temporary display overrides.

**Bounciness** reduces damping as it increases, producing stronger overshoot.
**Speed** increases natural frequency and generally settles the same damping
ratio faster. Frequency, damping, inertia and strength are available under
**Physical solver values**. Gravity uses pixels/second², with positive Y down.
Clockwise/counterclockwise limits are independent, up to 180° relative to the
stored rest angle and resolved parent. **Rotate** enables angular response.
**Translate / stretch and squash** enables bounded axial elasticity. Stretch
permits extension; Squash permits compression. Zero disables that side of the
range. Root anchors, pins and locked ancestry remain respected.

Use the footer **Play** icon for an isolated release test. **Repeat** repeats the
test without moving Timeline's playhead. While this explicit preview is active
or paused, dragging a bone tests follow-through and discards temporary authored
changes on release. Stop/close restores the held timeline pose. Ordinary editing
outside explicit preview retains normal authoring behavior. **Body / Face**
scopes live testing to the existing anatomical region.

For a persistent moving driver, **Create timeline motion test** creates a new
three-second editable clip. This is an authored operation with one Undo step.
Static rigs settle after a release, but need changing input to keep reacting.

## Activation and editable baking

At the desired playhead, select a group and click **Key On** or **Key Off**.
Check **Key master** to key its owning object's master gate instead. A later first
key preserves the preceding enabled interval. Expand **Spring** in Timeline for
group/master activation and the separate motion-test driver channels.

The header shows **Spring: ON / OFF / MIXED** at the current playhead, with
separate Group and Master states and the frame number. A check mark highlights
the sampled Key On/Off state for the chosen keying scope. An enabled group can
still be effectively off under a master Off key, pin, lock or baked-motion
bypass. These indicators follow scrubbing and Undo without creating keys.

Right-click Spring keys/rows for **Spring On/Off at playhead** and group/all-group
baking. Keys support ordinary move, edit, copy and delete. Filtering a group
limits summary actions to matching channels. Off removes procedural contribution
while manual animation remains; On resumes from fresh simulation state.

In **Bake to editable keys**, choose all groups or the selected group and a
minimum settling tail. Slow springs extend the tail automatically. **Use baked
result** selects the new clip, bypassing the baked bones' live simulation. Turn
it off to retain the procedural source selection while keeping the baked clip
available. Source clips and rig settings survive either way.

Baking runs in the background. Source edits reject stale output; closing the
editor discards unfinished publication. One Undo removes the new clip. Baking
one group leaves others live. An already baked group cannot be baked repeatedly
into duplicate output. Limits are 120 seconds including settling and 100,000
bone samples. Shorten the range or adjust slow settings if a limit is reported.
Output is normal editable position/rotation/scale/length animation.

## Configure Motion Pilot

Open **Animation → Motion Pilot** or its toolbox icon. It operates in Scene
context and accepts ordinary objects/groups and compatible connected rigs. Use
the top selector for the leader. Expand sections independently:

| Section | Behavior |
| --- | --- |
| Transform | Enable Move, Rotate and Scale independently. Signed/exchanged X/Y inputs map pointer displacement to scene pixels or degrees. World/Local sets the movement basis. Width/height use exponential scale gains; Uniform applies width mapping to both dimensions. |
| Face cursor | Off, Flip or Turn. Forward angle describes the artwork's facing direction. Turn overrides ordinary rotation mapping and smooths toward cursor direction over the chosen seconds. |
| Wave | Independent movement/rotation/scale amplitudes combine with other mappings or work alone. Speed is cycles/second, or cycles per 100 pixels with Use mouse movement. Stationary input holds mouse-driven phase. |
| Motion | Add project clips, remove layers or import `.rigaction`. Enable motion, speed/reverse and Automatic, Mouse movement, Click to play or Click to loop. Eight compatible layers can combine in list order. Move in place suppresses root X motion. |
| Flock Settings | Check followers or add Scene selection. None has no stagger; Uniform applies successive intervals; Random uses minimum/maximum frames and a repeatable seed. Leader mappings drive the flock without overwriting follower profiles. |
| Puppet Settings | Lazy Mouse adds lag in seconds. Cursor reference chooses a virtual Object/Viewport center origin. Blend combines with existing animation; disabling it replaces selected targets' previous Pilot output, retaining manual source tracks. Position optimization reduces X/Y keys within the per-axis tolerance. |

`assets/examples/motion-pilot-soft-follow.rigpilot` is an original reusable
starting profile with Lazy Mouse, a small vertical wave and uniform flock delay.
It has no project-specific clip or follower references.

## Preview, record and edit

1. Configure leader/followers and put Timeline at the desired start.
2. Click **Preview** or **Record** to arm capture, then press **Space** over the
   viewport or click the visible **Start preview / Start recording** button.
   Capture preserves the initial object pose and OS cursor position.
   While armed, the viewport still accepts selection and pointer input. Leader
   selection is locked for the armed take; Cancel lets you choose another target.
3. Move the mouse or pen in the viewport. Status shows the frame. Pointer presses
   trigger click-based motion. Pause freezes the clock; resume continues from
   the last valid input.
4. Press **Space** or Stop. Preview discards animation. Record preserves the last
   fractional sample and prepares editable keys in the background with a
   progress indication. **Esc** or Cancel discards capture.
5. Expand Transform/Motion lanes to edit, move or delete keys normally. One Undo
   removes the recording; Redo restores it. Add rotation over recorded movement
   with another blended pass, or disable Blend to replace earlier Pilot output.

Space remains text input in text/numeric fields. Closing releases listeners and
cancels live/unfinished capture. Changing document/context or editing the source
cancels stale work. Capture ends at the clip/scene end; extend that range before
a longer take. Limits are 128 targets, 100,000 pointer samples and one million
scalar samples. Keep the source revision unchanged until preparation finishes.

To combine walking and Springs, assign a premade character's ears/tail/hair to
groups, open Motion Pilot, add its Walk clip, enable native motion with Move in
place, and record primary movement. Springs react during replay. Bake a selected
group for editable secondary movement. Loaded native baked clips retain explicit
physics-bypass channels so secondary motion is not applied twice.

## Additional device and visual checks

Automated GUI tests run offscreen. Physical tablet hardware was not exercised.
With a tablet, select an object, arm Preview, press Space over the viewport,
move the pen and press its tip with Click to play enabled. Verify the same
position/trigger behavior as mouse, stop with Space, then record and inspect
the final keys. Pen pressure is not an animation channel.

To verify turning smoothing, disable Move, select Turn with a positive smoothing
time, start Preview and reverse direction. Compare zero smoothing: zero turns
immediately; positive values approach gradually across the shortest angle.
Check forward angles and rotated parents. Resize each panel to its minimum and
collapse sections: transport remains available while properties scroll. Bone
display edits should leave rendered artwork unchanged.

No collision/ragdoll system is included. Cold seeks replay a valid checkpoint or
clip start and may cost more on dense/long scenes. Recorded/baked output samples
project frames and retained subframes, rather than preserving continuous Bézier
polynomials symbolically. See the [Prompt 17 report](prompt-17-implementation.md)
for architecture, all acceptance evidence and explicit reference differences.
