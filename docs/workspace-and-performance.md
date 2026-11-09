# Workspace, reusable motion and FFD

The stage occupies the center, with a detachable toolbox on the left, Scene and
Inspector tabs above Assets in a shared right column. Assets has Project assets
first and Content second. The
timeline spans the full bottom edge. Drag its eight-pixel top grip upward to
enlarge it; focus the grip and use Up/Down to resize by keyboard. Welcome and
Transform forms scroll instead of imposing hidden height
constraints. Tools, Scene, Assets and Timeline are visible in the default editing
workspace. The right column starts at 320 pixels and Timeline at 280 pixels.
Menu toggles show a plain checkmark on the right when enabled.

Closing the application saves dock placement, visibility, floating geometry,
Timeline's channel divider and selected panel tabs in workspace preferences.
Object Editor retains its sidebar width and Timeline height separately, so closing
there does not replace the Scene arrangement with temporarily hidden panels.
View → Reset Workspace Layout restores the default arrangement and panel views
without changing project content, recent files or the theme.

## Images and scene selection

Ctrl+I opens Add assets for multiple images or layered sources in Project assets
without placing them in the scene by default. Double-click a source to create an
independent instance.
Instances share the original bytes but have separate geometry, transforms and
deformer stacks. Import and each placement are separately undoable.

Select is active by default (V). Click artwork or a scene row to synchronize
selection. Drag an object to move it live; Ctrl extends selection and dragging empty
space draws a selection rectangle. Rotate and Scale operate on objects; the
Transform inspector also exposes numeric local values. F2 renames a scene entry.
Scene rows expose visible/hidden and locked/unlocked icons. Inherited locks block
edits. Bone Select/pose keeps roots fixed; Move origin explicitly repositions them.

The preview header has **Images**, **Bones**, and **Groups** selection checkboxes.
Dragging on empty preview space selects all enabled types together, including bone
segments crossing the rectangle. A group is selected when its full artwork bounds
are enclosed. Locked/hidden entries are excluded. Ctrl extends the selection;
Ctrl+A selects all eligible visible entries. Images-only dragging leaves bound
bones unchanged. Bone drawing and mesh-dot editing retain their specialized tools.

In mesh vertex/edge/triangle selection, the toolbox Scale and Rotate buttons keep
mesh editing active and show eight selection handles. Drag a handle to transform
selected editable dots around the opposite anchor (Scale) or center (Rotate).
Protected vertices stay fixed. The visible preview commits as one undo step on
release; Escape discards it. Choosing Select returns to moving vertices.

Scene names stretch while View/Lock columns remain fixed at the right. Double-click
or F2 renames a row. Right-click offers folders, grouping, attachment, ordering and
deletion. Drag artwork/folders into folders or between rows; the tree shows front
to back, and keep-world reparenting preserves the displayed pose. Cycles, locked
entries and animated changes between incompatible parent spaces are rejected.

Delete removes selected scene objects or bones and dependent records. Bone deletion
removes associated constraints/keys and promotes surviving children. Skin weights
transfer to remaining bound ancestors or the nearest remaining bound bone; if no
influences survive, the skin stage is removed while artwork remains. Attached
artwork is detached at its current pose. Undo restores all removed bindings and
keys. These topology edits do not retarget existing animation on surviving bones.

Source artwork remains reusable in Project assets. Delete/right-click in Project
assets removes an unused source. Referenced sources are protected until their
instances/dependencies are removed. These changes support Undo.

The composer toolbar selects **Parts**, **Sprites** or **Bones**. Parts move artwork
and its bound bone controls together; Sprites adjust artwork/bind space while
leaving bones in place. Attach creates a keep-world rigid bone attachment. The
toolbox separates selection/move/rotate/scale from **Bone Editor** and **Spring
Editor**. Bone Editor exposes drawing, fixed-world origin pins, connecting,
insert/reduce, mirror, independent branch duplication, preview reset and mesh
wireframe/grid regeneration. Duplicate branches start at the same position and
have no copied animation or skin bindings.

## Dragging templates

Drag from Content or the separate library into the stage. New content shows a
45%-opacity ghost at the drop location; motions and animated FFD show an animated
prospective result on the hovered compatible target. Preview evaluation and media
ownership are isolated from source history. New rigs/artwork/fragments position
their new roots at the pointer. Drops preserve camera zoom and pan and commit one
undo item. Incompatible targets produce a reason. Nothing is silently retargeted
to an unrelated selected character.

The library's Preview/share window displays every bundled item even without a
compatible object in the project. A matching original rig or vector prop provides
a standalone specimen. Play preview uses the actual animation evaluator; FFD
previews include the evaluated mesh wireframe. Drag onto that preview to inspect
another item without changing the source project.

## Custom FFD

In Mesh/Deform, select artwork, add an FFD stage, and select its dots by clicking,
Ctrl-clicking or drawing a rectangle. The toolbox Scale/Rotate commands activate
the corresponding FFD mode. Move drags dots, Scale uses selection box handles, and
Rotate rotates about the selected dots' center. Numeric Move X/Y, rotation and
Scale X/Y % apply to the same selected controls. Keep scale proportions links
numeric axes. Select all, mirror, align axes, Average from four corners, align to
bounds center, reset selected and reset all are available in the Deform page.

Existing animated channels update at the current frame; Auto key adds channels
for previously unanimated controls. Each completed gesture or numeric edit is one
undo item. SVG artwork continues through the existing vector geometry renderer;
these tools do not replace the original with a bitmap.

Original FFD motion presets contain complete normalized lattice keyframes and
adapt to the target mesh bounds. They append channels to the current clip, keeping
its bone animation. The library exposes speed, loops and preset strength. Mesh
object strength multiplies each stage's intensity and vertex mask. Share FFD
shape/motion writes a portable `.rigpack` with normalized controls and bounded
key data; it can adapt to differently sized artwork after installation.

## Puppet Stage

Animation → Puppet Stage opens a custom window. Choose a rig or mesh and a
compatible body/FFD motion, assign an ASCII letter or digit, then add a card.
Cards retain speed, loop and pin settings. Object effect cards key actual flip,
visibility and opacity channels. Hotkeys are scoped to the Puppet window so text
entry remains usable. Profiles are bounded inert `.rigpuppet` JSON files; loading
can explicitly remap their targets, and sharing preserves existing files.

Preview creates a scratch performance. Record captures triggers, independently
looping motion and FFD cards, and Stop prepares ordinary timeline keys on a worker.
The result commits as one undo item only if the source revision still matches.
Recording ends at Stop; original keys after that boundary are retained. Closing
or canceling discards scratch edits. Live view temporarily hides authoring docks
and restores their visibility on exit. Mocap, microphone, Puppet Stage speech/camera cards and
live broadcasting are not implemented.
Offline audio playback and editable lip-sync are available separately in
**Animation → Face & lip-sync**; see the facial animation guide.

## Spring follow-through

Select child bones and use Rig → Add spring follow-through, or configure a Spring
constraint in the Rig inspector. Selecting a root expands to its descendants;
the root remains kinematic. Frequency, damping, strength, gravity, inertia and
maximum angle control secondary movement. Live posing updates the visible bones
and their skinned artwork while dragging, with bounded settling after release.
Saved rules also evaluate during playback and headless seeks.

Spring Editor's Create motion test selects its new clip in the active Scene or
Object Editor. Its driver keys appear in an expanded **Spring** timeline row,
with editable Position X/Y and Rotation channels. The row supports the normal
visibility, lock and key operations. These are the real kinematic driver keys;
spring constraints still supply the evaluated follow-through.

Physics uses fixed substeps and deterministic full-history sampling, with bounded
checkpoints and a bounded kinematic cache. Cold long seeks replay from clip start
or a valid checkpoint. Springs provide angular and bounded axial follow-through,
without collision detection, ragdoll contacts or a wall/ladder solver. See
[Spring and Motion Pilot](spring-and-motion-pilot.md) for activation, selective
baking, pointer recording and native motion blending.

## Retention and preparation

Open **Performance & project diagnostics** to set the Undo retention limit.
It defaults to 500 edits and accepts 1–10,000. Compound gestures count once;
lowering the limit releases the oldest history while keeping the nearest redo
steps. The limit persists across projects and restarts. It is not a byte-level
memory guarantee.

**Remove older generated template caches** runs explicit maintenance on a worker.
It preserves the current generation, the two newest generations, anything less
than seven days old, unknown directories and incomplete staging. Installed user
packs and original artwork are outside its cleanup scope. Other running versions
can still require their older caches; this maintenance does not provide
cross-process cache leases.

Cold built-in preparation runs in an isolated process with progress and
cooperative cancellation, keeping native raster work out of the GUI interpreter.
Completed caches use atomic publication; the normal warm path avoids spawning a
process. Playback, vector artwork and document services retain their existing
ownership and evaluation rules.
