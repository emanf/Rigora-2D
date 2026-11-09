# Selection properties and timeline

Select artwork, a character, a folder or bones to populate the main toolbar next
to the eye control. Values follow evaluated playback and live transform previews.
The property strip scrolls horizontally on smaller windows.

- **X / Y** place a single object's pivot in its parent's pixel coordinates.
  Multiple objects show the left/top of their combined scene bounds.
- **W / H** measure a single object's dimensions before rotation. Multiple objects
  show their combined scene bounds. The padlock keeps their proportions together,
  including when resizing with the canvas handles. Property groups have consistent
  gaps, with each `X:`, `Y:`, `W:` and other label kept close to its input.
- **R** edits local rotation. Multiple objects rotate together around the center
  of their selection, using the first artwork node's rotation as the reference.
- **O** controls opacity in percent. **V** changes rendered visibility, including
  held visibility keys. **Flip H / V** mirror artwork and its character rig.
- **Reset** restores a single object's unscaled dimensions, centers its pivot,
  removes rotation and mirroring, sets full opacity/visibility and places it in
  the camera center. Folders retain their parts' arrangement. Multiple selected
  roots are reset as an assembly and recentered together; their internal part
  transforms are retained. Bones retain their base-joint pivot.

Numeric edits commit on Return or when leaving the input. An edit is undoable.
Auto key records unanimated properties at the playhead and seeds the initial pose.
Editing an already animated property records the displayed frame, preserving its
other keys. This includes canvas move, rotate, resize and pivot gestures with Auto
key off. Empty tracks remain editable as static transforms until keyed. Reset
follows the same rule and commits one Undo operation.

Drag the pivot crosshair to snap to a corner, edge midpoint or the object's center.
Alt bypasses snapping. The pivot can be grabbed again even when it overlaps a
resize grip; its hit target takes priority there.

## Property lanes

Object/character headers are distinct neutral bands. They expand/collapse the
property list and are not editable animation lanes. **TRANSFORM** combines
position, rotation, scale and pivot channels on one row. **VISIBLE**, **OPACITY**
and other properties occupy their own rows. Existing scalar channels and key
identities stay intact in saved projects and in the precision/curve editors.
Vertex position channels appear together in a **MESH DEFORMATION** lane beneath
their artwork, keeping dense mesh animation editable without hundreds of vertex rows.

The **Eye** enables or disables the row's animation in preview, playback and
export. Disabled rows retain their keys and return control to the underlying
animation or authored pose. **Lock** prevents key changes, deletion, pasting and
insertion into that row. Linked Animation spans also support locking: locked
spans cannot be moved, trimmed, removed or extended with new actions. Their
source keys remain protected independently. Both controls support Undo and save.

**Add tracks** shows searchable objects, folders and bones on the left, with a flat
property list on the right. Click **+** beside Transform, Visible, Opacity or Mesh
Deformation to add that complete property. Color, Outline and named deformation
effects appear when supported by the selected object. Mesh Deformation includes
all editable points together; vertices and internal binding data are not separate
choices. Transform includes position, rotation, scale and pivot. Each row shows
one property, including combined color components and built-in effect parameters.
Each choice shows Available, Partly added or Added; adding a partial property
fills only its missing channels. Adding tracks creates empty lanes and is undoable.
Double-click and multi-selection still work; drag a property onto a frame to
capture its value there.

Click or right-click a frame slot to move the playhead there. A translucent circle
shows an empty key slot under the pointer. Double-click an empty slot to capture
a key; double-click a tween body to open its graph. Right-click targets the clicked
property and offers key, tween, curve, clipboard and precision commands.
Keys, playheads and ruler labels sit in the center of each frame cell. Frame 0
has enough leading space to show its whole cell and ruler handle, including
after rebuilding or zooming.

With **View → Snap to whole frames** enabled, pausing playback or starting a
viewport edit holds the nearest whole frame. Automatic keys and Insert key
therefore land at cell centers even after fractional playback times. Disable
Snap to author subframes. Continuous playback and explicit frame-field seeks
retain their precision; an edit snaps the cursor before recording.

Each frame has a light grid line when zoom permits. Every fifth/tenth frame has
a stronger tick; frames 0, 10, 20 and so on each have a darker frame column.
At distant zoom levels the spacing adapts to remain readable. Use the visible
zoom buttons or Ctrl+wheel, Shift+wheel to scroll time, and F to fit keys.

## Tracks versus keys

Focus determines the clipboard and Delete scope:

- In the **property list**, right-click or use Delete / Ctrl+X / Ctrl+C / Ctrl+V
  to remove, cut, copy or paste whole selected lanes, including empty channels.
- In the **frame grid**, those shortcuts edit selected keys. Removing keys retains
  their lanes. Removing a lane removes all its keys and can be undone.
- Pasted tracks retain their original object ownership and relative key spacing,
  starting at the playhead. New lanes retain their blend/editor settings. Matching
  existing lanes receive keys without changing their settings. Overlapping keys,
  missing owners and locked destinations reject the entire paste.

Scene locks and track locks are honored. Whole-track edits use the same Qt-free
`AnimationEditingService` as headless clients; the toolbar uses
`SelectionPropertyService` over the existing scene and character services.
