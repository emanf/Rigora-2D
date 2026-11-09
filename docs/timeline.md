# Timeline workspace

The timeline keeps playback controls in its dock title bar, including the clip,
current frame, end frame and speed. Editing commands stay above the timing area;
there is no separate playback row. Drag the dock's top grip upward for more
height; the focused grip also responds to Up/Down. The Dope sheet is the primary
timing workspace. Curves now open in a contextual popup; Clips & markers remains
a separate page. Track/key commands and Auto key are inside the Dope sheet.

Playback buttons occupy the center of the title bar's control area. Clip and
current-frame fields sit on the left; end frame, speed and range/FPS sit on the
right. Dropdowns and fields have 8-pixel gaps, with wider separation between
control groups. Clips & markers, key details and scene action editors use the same
field spacing.

## Character action rows

Main Scene keeps one level of properties under each Object: Transform, Animation,
Skin, Clothing, and other supported channels. The Object header shows a combined
read-only overview. It never moves its underlying keys.

Add tracks offers flat Animation, Skin and Clothing entries. Each opens a card
grid populated from that Object's saved data. Appearance collections use a single
selector in the editor, without adding child rows to the timeline. No changes are
made until Insert action or Apply changes is pressed.

Animation spans have running icons at both endpoints, with their name and source
speed between them. Drag the middle to move the interval, or either icon to trim
it. Right-click or double-click for source choice, start, end, speed and looping.
Speed controls source playback within the chosen interval; it does not resize the
interval. The arrangement uses existing motion-window records and preserves saved
source actions. The former separate Motion blocks tab is hidden.

Skin keys use palette icons; Clothing keys use shirt icons. Right-click or
double-click a key to replace its saved choice, or an empty action cell to insert
one at that frame. One icon can represent several keyed collections at the same
frame; choose the collection to edit in the popup. These are hold keys: their
values persist until the next choice. None in a clothing collection restores
uncovered parts. A key drag moves all of that icon's represented channels together.
Saved skin sheets and clothing alternatives are created in Object Editor.

Attachment keys use link icons on a separate flat row under each Object. They
hold an independent, attached or released state. Use Add tracks → Attachment,
the Object menu, or the Inspector's Key here control to choose the target and
grip. Right-click a key to edit it. See [Scene attachments](scene-attachments.md).

The action editor supports removing a choice, keeps edits in one Undo operation,
and rejects pending edits after switching scenes, clips, or Object Editor context.
Clothing and skin keys remain local to the placed instance. They do not change
shared appearance defaults or other linked copies.

## Add channels and key them

1. Select the object or bone on stage, then choose **Add tracks**. The owner
   selector prefers that selection. It supports searching by name/type; the
   property search filters labels and canonical paths.
2. Select **Transform**, **Visible**, **Opacity** or other properties. Ctrl/Shift
   select multiple rows. **Add selected tracks**, or double-click a picker row,
   adds empty lanes to the current clip as one undo step. A first clip is created
   if needed. Existing lanes are reused; adding a lane does not change the pose.
3. Double-click an empty timeline cell to capture a discrete held key at
   that frame (or an interpolated key with Auto key enabled). The Transform lane
   captures all its components together. Select a property and press **K** to
   capture at the playhead. Object headers are inert and expand/collapse their lanes.
4. Alternatively, drag a channel/group from the picker onto the timing area.
   A translucent prospective key marks the destination. Release adds the lanes
   and keys at that frame as one undo step. Dragging from another document session
   is rejected; names are never treated as target identities.

The catalog includes real supported transforms, appearance values, bone length,
FFD/lattice controls, pins, vertex coordinates and registered deformer numeric
parameters. **Include individual vertex channels** exposes the advanced vertex
owners without crowding the ordinary owner list. Unsupported camera/audio/facial
features do not appear as pretend working tracks.

## Navigate and edit

The ruler stays above both axes of scrolling. Frame labels use adaptive spacing;
marker names have a separate clipped lane. The owner tree and key body share
24-pixel rows and the same vertical scroll range, including partial-row offsets.

| Gesture | Action |
| --- | --- |
| Wheel | Scroll channels vertically |
| Shift+wheel | Scroll time horizontally |
| Ctrl/Alt+wheel | Zoom time around the pointer |
| Middle-drag or Alt+left-drag | Pan time/channels |
| Drag ruler | Scrub; Shift-drag selects a time range |
| Left / Right arrow with ruler or key area focused | Previous / next frame; holding repeats within playback bounds |
| Click or right-click frame slot | Move the playhead there; right-click opens commands |
| Click / Ctrl-click key | Seek and select / extend selection |
| Drag empty key area | Box-select keys |
| Drag keys or collapsed summary key | Move in time; one undo step on release |
| Click / drag tween body | Select its endpoints / move the complete span |
| Drag a tween endpoint | Shorten or lengthen the animation, preserving its graph |
| Double-click empty lane | Capture a key or grouped keys |
| Double-click tween / G | Open its transition graph popup |
| Double-click discrete key / Enter | Open Key details |
| F | Frame selection or current keys |
| Ctrl+X / Ctrl+C / Ctrl+V / Ctrl+D / Delete | Cut / copy / paste / duplicate / delete |
| Ctrl+A | Select keys visible on the active surface |

Dope-sheet drags preserve vertical lanes and relative time spacing. Snap moves
the time delta in whole frames while retaining stored subframe offsets. Locked
members reject editing as a whole; timing collisions are reported and reverted.
Compound keys select their constituent channels at that frame. Source records
are not changed while dragging. The precision and graph editors retain canonical
scalar values. Empty slots show a translucent circle on hover; the frame grid
uses minor ticks and darker columns at frames 0, 10, 20 and so on, with visible zoom buttons.

Focus the property list to cut/copy/paste or Delete complete tracks, including
empty channels. Focus the timing grid to operate on selected keys instead.

**Filter tracks** searches owner names, display labels and paths. **Selected
only** follows stage selection and includes related descendant tracks. Selecting
a property row selects its stage owner; a deformer/vertex row resolves to its
artwork object. The Lock and Show columns retain their established behavior:
Show hides editing keys/curves, without muting animation playback.

Object Editor defaults to **Group property tracks**: all parts share one
**Transform**, **Opacity**, **Visibility** or other property row. Grouped keys
retain their original owners and scalar channels, and edits remain undoable.
Use **View → Group property tracks** to inspect individual part/bone lanes.
Scene view always keeps each character or Object under its own named header,
with its property rows beneath it. Grouping changes presentation only.

Filtering a grouped property narrows its members, so **head rotation** shows
and edits only matching head rotation channels. In the individual view, matches
temporarily open collapsed ancestors; clearing the filter restores disclosure.

**Key details** contains time, value and interpolation. Apply changes preserves
relative spacing/value offsets across a multi-key selection. The **View**
menu holds frame snapping, onion poses, trails and retained-frame comparison.
**Marker labels** hides ruler text such as Passing, Action and Opposite, while
keeping marker ticks and saved annotations. Onion skin and motion trails appear
on stage during animation, including bone posing. **Compare retained pose**
captures the current frame once and keeps it while scrubbing or toggling other
overlays; turn it off and on to retain a different frame. Rest-rig construction
and mesh editing suppress animation overlays.

## Tween spans and contextual graphs

Select two keys on a channel and choose **Convert to tween** from the right-click
menu. Linear interpolation displays a connected `o════════o` span. A discrete
held key has no outgoing connector. **Create tween** (T) either connects selected
endpoints or captures the chosen tracks at the playhead and the duration field's
end frame. Edit endpoint values in Key details to create the desired movement.
An equal start/end value holds the same pose even when its progress graph changes.

Dragging the body moves both endpoints. Dragging a single endpoint stretches or
compresses its timing, with the other endpoint fixed. Endpoints cannot cross.
The stage evaluates the prospective animation during movement; release commits
one command. Copy/cut/paste preserve graph data; Duplicate starts after the last
key on the selected channels. Reverse reverses the selected ranges and graphs.
**Frame-by-frame / hold** restores discrete outgoing interpolation.

Double-click a span or choose **Edit tween graph**. The custom-titlebar popup
contains 24 original offline presets (linear, polynomial, sine, exponential,
back, bounce and spring variants). Click to preview, or drag a preset onto its
graph or directly onto a timeline span. Double-click to add a dot; drag interior
dots; Delete removes them. Endpoints remain fixed. Add/Delete, local Undo/Redo,
Linear, Reverse, Smooth dots, Snap dots and Repeat easing provide drawing tools.
Ctrl+Z / Ctrl+Shift+Z in the graph undo/redo scratch edits. Repeat easing divides
the span into repeated time/progress sections; it does not loop the whole clip.

The popup loops its prospective animation by default. Its scrubber previews any
point without changing the real playhead. Apply saves one undoable change;
Cancel and titlebar Close discard the preview. Switching documents/clips or
changing the source revision closes a stale edit. Final graphs appear inside
their spans and drive the same evaluator used by headless rendering and export.

**Auto key** records ordinary scene transform edits and mesh/FFD scalar edits at
the current frame. New channels receive their initial pose at the scene start,
so a later first key does not replace the whole earlier pose. Timeline and mesh
recording switches stay synchronized. Selecting a bone keeps the timeline and
playhead available. With a clip or Auto key active, posing records the displayed
frame, including IK control targets. Drawing and configuring rig structure remain
editable construction operations. Recording is off by default for an unanimated scene.

## Maximum playback frame

New projects end at frame **120**. Change **End** beside the current-frame field,
or drag the ruler's end flag. The drag previews its boundary and commits once on
release. Playback and scrubbing follow the selected clip's cap (or the scene's
cap before a clip exists). Shortening it preserves all keys beyond the boundary;
they remain visible in the shaded region. Undo restores the earlier range.

Normalized graph metadata is stored in the outgoing key's `extra.transition_curve`:
2–257 strictly time-ordered `(time, progress)` points, fixed `(0, 0)`/`(1, 1)`
anchors, and a `smooth` flag. Linear segments interpolate dots directly; Smooth
uses cubic Hermite interpolation. Interior progress can overshoot within −4–5.
Legacy Bézier tracks remain evaluable; opening their graph samples their existing
shape for editing. A plugin that supplies its own track sampler must be baked
before replacing its sampling with a transition graph.

Clip retiming, reversal, baked transitions, reusable actions and range previews
remain in [animation-editing.md](animation-editing.md). This is numeric key editing,
not a new nonlinear clip compositor or a commercial application's full feature set.

## Spring motion channels

Creating a motion test in Spring Editor selects the clip in the active editing
context, clears filters that would hide its keys and expands its **Spring** row.
Expand that row to edit its Position X/Y and Rotation keys individually. In Scene,
the row remains under its owning hierarchy; Object Editor combines the relevant
drivers in its property view. Normal row visibility, locking and Undo apply to
the underlying tracks. Older Spring motion-test clips are recognized as well.

The row displays authored driver animation. It does not add keyed frequency or
damping parameters to spring constraints.

## Developers

`AnimationEditingService.channels()` returns Qt-free `AnimationChannel` values
with owner, canonical path, display group/label and authored base value.
`add_channels([(owner_id, path), ...])` creates empty lanes;
`add_channels(..., frame=12)` captures keys. Both use canonical validation and
undo; captures use existing track samplers and preserve raw weighted/additive
track values. Batches allow 1–512 unique supported channels. Invalid or locked
members leave the entire operation unchanged.

Deformer numeric leaves, including nested dictionaries/lists, are discovered
automatically through the same engine parameter contract. Binding matrices,
field bounds and lattice topology remain non-animatable. Plugins can add optional
`animation_channels` metadata to their existing deformer registration:

```python
context.register(
    "deformers",
    context.manifest.id + ".wave",
    "Wave",
    solve,
    parameters={"wave": {"amplitude": 12.0, "phase": 0.0}},
    animation_channels={
        "parameters.wave.amplitude": {"group": "Secondary motion", "label": "Wave height"},
        "parameters.wave.phase": {"group": "Secondary motion", "label": "Phase"},
    },
)
```

The solver receives sampled nested parameters normally. Labels/groups are optional,
bounded strings and cannot create an unsupported engine path. The metadata is
transient, injected by the active plugin registry and retained in document forks;
keys and parameters remain ordinary saved project records. Disabling a plugin
retains data and exposes existing missing-solver diagnostics. Custom `track_types`
samplers continue to support complex numeric sampling; no executable code is
accepted through channel drag payloads. See [plugin-sdk.md](plugin-sdk.md).

## Spring and Motion Pilot channels

Expand **Spring** for master/group activation and motion-test drivers. On/Off keys
are stepped ordinary channels. Right-click their rows/keys to key activation or
bake one/all groups; filtering limits summary actions to visible channels.
Motion Pilot recordings appear in ordinary Transform lanes. Native motion may
also add **Motion → FK pose** and **Baked secondary pose** channels to retain
constraint/physics bypass for evaluated clips. All use existing editing,
clipboard, Undo and persistence. See [the workflow guide](spring-and-motion-pilot.md).

## View and Camera actions

Main Scene Objects offer a flat **View** row alongside Skin, Clothing and
Animation. Its turnaround-icon keys select Default or a saved angle without
changing the source artwork. Missing angles remain editable empty slots.

Camera channels share one **Camera** header with Transform, Cut, Animation and
Effect rows. Camera-icon Cut keys choose the active output camera; motion and
lens presets use editable intervals in the same dope sheet. See
[Object views and camera actions](object-views-and-camera-actions.md) for presets,
timing, strengths and preview/export behavior.

