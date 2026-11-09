# Secondary motion and editable baking

Use **Animation → Secondary motion & physics** to configure child-bone springs,
preview motion, create cartoon motion and bake dynamics into ordinary timeline
keys. Separate object roots anchor the rig; the first bone can spring about its
base. Standalone rigs without an object anchor retain a kinematic first bone.
Frequency, damping, inertia, gravity, strength
and angle limits control follow-through; settings persist with the project.

Bounce presets create editable clips for a chosen control, height and duration.
Squash/stretch keys scale X and inverse-scale Y, retaining area at authored
samples. Interpolated scale products can vary slightly between samples.

Bake dynamics runs in the background. It simulates the complete clip from its
start at fixed 60 Hz, with internal integration up to 240 Hz, and samples project
frames plus authored subframes. Fractional samples cannot change later
integration. The new FK clip retains non-bone tracks and markers, bypasses bone
constraints to avoid double simulation, and leaves the original clip intact.
One Undo removes the bake. Publication rejects a changed source, and closing the
dialog discards unfinished work. Baking is bounded to 120 seconds and 100,000
bone samples per clip.

Interactive random seeks reconstruct full history using bounded checkpoints.
Forward playback extends existing fixed ticks; cold seeks replay from clip start.
This solver provides angular
follow-through with optional bounded axial stretch/squash. It does not provide
collision detection or general rigid-body simulation.

Forward playback retains its completed 60 Hz
integer tick and integrates only newly elapsed ticks. Fractional display samples
use a copied state, so they cannot change subsequent full steps. Backward seeks,
loop restarts and checkpoint restores reconstruct their canonical samples;
transient override samples use a separate simulation. New evaluators own new
cursors, so property/clip changes cannot reuse stale physics. The parent-first
spring pass recomposes each hierarchy node once, including nonspring descendants.

## Modeless Spring Editor

Open the toolbox Spring Editor or **Rig → Spring Editor**. Use the **+** beside
Groups to create a uniquely named group; double-click its name to rename it.
Expand a group to see its assigned bones. Selecting member rows also selects
those bones on the stage; Ctrl/Shift selects several rows. Drag the divider under
the tree to resize it, with at least five rows remaining visible. The list height
is remembered when the editor closes.

Select child bones (optionally including descendants), then **Assign to Group**.
Assignment includes every selected bone itself, plus its descendants when
**Include child bones** is enabled. An object's first bone receives a Spring rule
and can rotate/stretch about its fixed base. Standalone roots without a separate
object anchor appear with an anchor icon and remain kinematic. Assignment moves a bone
from its previous spring group. **Remove from Group** removes the selected membership; **−** removes the
group and its rules. These edits and inline renaming support Undo and project saves.
Clicking a preset immediately updates the chosen group's members. If the group is
empty, it assigns selected bones with that preset; selecting a root with
Include child bones enabled adds the first bone and its children, using the
object root as their anchor.
Property changes update existing members after a short coalescing delay. Each
published change supports Undo. Switching groups finishes the former group's
pending update; removal and external document changes cancel stale pending edits.
While paused, clicking a preset also releases a visibly deflected live spring
pose so even a stationary newly drawn chain shows its response. This release
changes simulation memory only; it creates no keys, moves no root, and adds no
extra Undo step. Rubbery/Slow have broader follow-through; Fast/Stiff settle
quickly; Weighted has stronger gravity. Stretchy demonstrates axial lengthening,
and Squashy demonstrates compression, with rotation disabled for these two
presets. Existing saved settings change only when a preset is reapplied.

For continuous testing on a rig without animated inputs, click **Create motion
test** in Presets. It adds a separate three-second clip with editable Bézier
translation/rotation keys on the relevant rig roots and starts Play/Repeat.
Real spring constraints and skinning produce the response. Existing clips and
rest bones remain intact; one Undo removes the new clip. A spring preset needs
changing input to keep moving, so ordinary playback of a completely static rig
does not synthesize hidden animation.
Clockwise and counterclockwise limits are independent.
Translate enables axial elasticity bounded by the displayed Stretch/Squash
percentages. It changes evaluated local X scale, retaining the base joint and
carrying connected children and skinned artwork. Authored transforms stay intact.
Limits apply to each bone's evaluated world length; parent elasticity does not
multiply squash/stretch repeatedly down the chain.
Even 100% squash retains a small nonzero scale so descendants remain editable.
Rotate can be disabled independently. Bounciness and Speed expose monotonic 0–100
controls; physical coefficients remain available in the collapsible section.
Group definitions and membership persist in project saves.

Each of the ten presets has a small animated example beside its button. Every
example uses the same moving attachment and the production spring solver with
that preset's coefficients. The examples are computed once, cached, and drawn
using one shared clock while the editor is visible. Hover an example for a
description and suggested use. These illustrations do not modify the scene or
its playhead.
The **Presets** and **Property** headers expand or collapse independently without
changing settings. Preset illustrations stop drawing when their section is closed.
The bottom **Body / Face** selector scopes live physics preview. Facial bones are
explicitly assigned to the **Face** bone group (or declare `region: "face"`);
their descendants inherit that region. Face is unavailable for rigs without such
bones. Changing preview scope does not rewrite authored constraints or timeline
playback. **Play/Pause** and **Repeat** sit beside Body/Face in the fixed footer.
Spring Editor has no separate Preview toggle, progress slider or frame readout;
use Timeline to seek to a specific frame.

Timeline playback exclusively owns the stage pose while running. Interactive
drag/settling simulation stops when playback starts, including queued live timer
callbacks, so two simulations cannot alternately overwrite the displayed bones.
After pausing, moving the rig starts interactive physics again.

## SVG spring examples

Click **Open SVG spring examples…** at the bottom of Spring Editor, or choose
**Content → Templates → Props & accessories** and search `spring-example`.
The collection includes Daisy, Sunflower, Berry bush, Willow, Windsock and
Mushroom. Each has independent SVG artwork, bones, skin bindings, named spring
groups and a stationary support. Apply one, choose **Breeze** or **Strong gust**
from Timeline and Play. The clips key a wind driver; real spring constraints
produce the follow-through and settling. The mushroom also demonstrates bounded
axial stretch/squash. Named groups open directly in Spring Editor for preset
and property changes. Drag the driver with Live physics enabled to interact.

Sources live in `assets/examples/springs/`. Rebuild with
`python tools/build_spring_examples.py`; review native projects are written to
`build/spring-studies/`. Save changes as a project or custom pack before rebuilding.
These examples demonstrate the current angular/axial solver, without foliage
collision, fluid simulation or a separate wind-field engine.
