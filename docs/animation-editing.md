# Animation editing

The Timeline dock shares the document's clip, track and key records with the
animation evaluator. There is no separate editor playback engine. Bone tools and
the timeline remain available together. **Add tracks** opens a searchable owner/channel
picker for Position, Rotation, Scale, Pivot, Opacity, Visibility, bone length,
FFD and other numeric deformer parameters. Individual vertex channels are an
optional advanced view. See the [timeline guide](timeline.md).

The Dope sheet groups property rows under their object/bone hierarchy. Position
and Scale have expandable X/Y lanes. Collapsed groups show aggregate keys that
select and move their real constituent keys. Expand or collapse owners, scroll,
Ctrl/Alt-wheel to zoom time, and drag the fixed ruler to scrub.
Clicking the ruler gives it keyboard focus. Left/Right arrows step the playhead
one frame backward/forward; holding an arrow repeats and stops at the playback
bounds. The same keys work in the key area, in both Scene and Object Editor.
Text inputs keep normal caret movement and layer trees keep expansion/navigation.
Drag empty space for box selection; Ctrl adds/toggles keys. Shift-drag the ruler
selects a time interval and fills the preview range. Drag keys to move them;
Snap frames defaults on, while stored times remain floating point. Locked tracks
reject edits, including edits from the deformation inspector. Show hides editor
keys/curves and disables that track's animation evaluation.

Scene Objects also expose a flat **Attachment** row with held link-icon keys for
pickups, hand-to-hand transfers and releases. Open an icon to choose the placed
target and grip, retain position or snap, and edit its offset. See
[Scene attachments](scene-attachments.md) for the complete workflow.

With a key surface focused, Ctrl+C/V copies/pastes at the playhead, Ctrl+D
duplicates after the last key on the selected channels, Delete removes keys, Ctrl+A selects visible
keys, F frames the selection, and K captures selected channels at the playhead. Text
fields retain their normal editing shortcuts. Key gestures, multi-key numeric
edits and clipboard operations each create one undo command. Collisions with
existing keys are reported and leave the document unchanged.

Connected tween spans show their easing graphs inline. Drag their bodies to move
both endpoints or drag an endpoint to retime the interval. Double-click a span
for the contextual transition graph popup, with editable dots, 24 original easing
presets, smoothing, snapping, repeat easing, local graph undo/redo and looping
stage preview. Apply commits once; Cancel restores the authored pose. There is no
separate Graph editor tab. Discrete held keys support frame-by-frame workflows.
The canonical evaluator still supports legacy step, linear and Bezier keys;
legacy frame-unit handles scale with endpoint retiming. See the
[timeline guide](timeline.md) for graph controls and data limits.

Clips & markers manages names, annotations, inclusive in/out points, stored loop
defaults, and temporary range previews. Duplicate creates independent timeline,
track, key and marker identities. Retime maps key/marker times and tangent time
components. Reverse swaps handles and segment interpolation. Root offsets are
additive tracks at the end of the clip's layer stack, so nested transforms and
layered channels do not receive the offset twice. Retiming refuses negative
resulting keys; expand the source clip to include its keys before reversing a
trimmed interval. Stepped reversal retains frame-based hold conventions.

Blends and end transitions create new clips with numeric channels sampled at
whole frames and the clip endpoints, using the existing track sampler and layer
policies. They are editable baked actions, rather than live nonlinear sequencing.
Bakes are bounded to 10,000 frames and 20,000 channel samples per operation.
Subframe values between baked keys use linear interpolation; source clips retain
their original curves. Constraints and deformer stacks continue through the same
scene evaluator after the blended numeric channels are sampled.

Export action writes bounded, data-only `.rigaction` JSON. Reuse action matches
original owner IDs or unique owner names/types, remaps numeric parameter references,
adapts FPS and creates a new independent clip. Ambiguous or incompatible owners
fail without partial imports. This is compatible-rig reuse; semantic retargeting
between different anatomies remains a later milestone. Existing `.rigmotion`
deformation exchange remains available in Mesh / Deform.

Onion shows adjacent evaluated poses; Compare retains a chosen frame; Trails
samples 25 world-space poses per clip revision. These optional CPU previews never
change the document or transport frame. Playback speed is transient; stepping and
looping remain on the shared transport. They are disabled during rest/mesh editing.

Python clients use `AnimationEditingService(document)` from
`rigora.application_services.animation_editing` for these same undoable commands.
No Qt import is required. CLI evaluation of saved edited projects uses the existing
`rigora --evaluate PROJECT --frame FRAME` command.

## Live action layers and production tools

Placed Animation actions additionally support layer order, body masks,
Override/Additive blending, weight, Mute/Solo and linear fades. These are live
composition settings; the older clip blend/transition commands above still bake
new independent clips. Foot contacts add ordinary parameter keys, and the
state-machine panel previews conditions against existing actions on a fork.
Typed markers, multitrack audio, game regions/particles, shot transitions and
Bezier paths share the canonical evaluator. See [production workflows](production-workflows.md)
for authoring steps, limits and engine differences.

In the tween graph, Ctrl+arrows select points and arrows move the selected
interior point by 0.01. Shift uses 0.1 steps; Alt uses 0.001. Home/End select the
fixed anchors, Insert adds a point, and Delete removes the selected interior
point. The native point selector and named Time/Value fields provide equivalent
numeric editing with local graph Undo/Redo. Endpoints stay fixed, time ordering
is preserved and all graph edits remain transient until Apply.
