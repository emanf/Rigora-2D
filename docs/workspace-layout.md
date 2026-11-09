# Workspace layout

The default workspace places **Scene on the left**, **Preview in the middle**,
**Assets on the right**, and **Timeline across the bottom**. The main toolbar
stays above them. Inspector starts closed, including when entering Object Editor.
Open it from **View → Inspector** when needed; its default position is to the
right of Assets, at the same height. Explicit visibility choices are retained.
Older stacked Object Editor Inspector layouts migrate to this horizontal split
once; later manual layout changes remain under the user's control.

Assets → Content starts with two complete card columns at common desktop window
sizes. Resizing Assets still changes the number of columns normally.

Empty **Objects** and **Imports** grids show centered **Create empty object** and
**Import assets…** actions with a short hint. These are ordinary shared commands;
the empty prompt is not a selectable card. Adding an entry hides the prompt and
removing the final entry restores it. Imports keeps its compact add button when
files are present; empty grids remain available for drag-and-drop.

The main toolbar wraps intact command groups onto additional rows as the window
narrows. Position, size, appearance and other groups each have a small dot grip.
Drag a grip to rearrange the groups; an insertion line previews the new position.
An out-of-toolbar drop or Escape cancels. Focus a grip and use arrow keys or
Home/End for keyboard arrangement. Group order saves immediately in workspace
preferences and returns on the next launch. **Reset Workspace Layout** restores
the original order. Rearranging commands does not edit a project or its history.

Welcome opens as a separate startup window, with New/Open, searchable recent
projects, recovery and a quick-start link. It closes and releases its widgets
after creating, opening or recovering a project. Cancelling creation or failing
to open a file leaves it available. **Continue to workspace** or the close button
dismisses it without creating a project. **View → Welcome** opens it again.
Welcome never occupies a project tab or replaces the active document, canvas
zoom, selection or undo history. Only projects appear in the tab strip.

Scene remains visible on startup behind the startup window.
Opening a project shows **Scene → Preview (with Tools) → Assets**.
Opening Welcome, closing the last project, or refreshing the UI keeps the panel arrangement.
View choices and layout changes made without a project are saved just like changes
made with a project open. Reset Workspace Layout also works on Welcome.

Tools belongs to the Preview workspace. Drag its six-dot grip to the **left, right,
top or bottom edge inside Preview**. A neutral highlight marks the valid drop
area. Left/right placements use a 44-pixel vertical strip; top/bottom placements
use a 44-pixel horizontal strip. The canvas receives the remaining space, so tools
never cover editable artwork. Controls remain 34-pixel rounded squares, with a
10-pixel inset before the first tool. The dots show an open-hand cursor while idle
and a closed hand throughout dragging.

Drops over Scene, Assets, Timeline, project tabs, preview options or outside the
application leave Tools at its current edge. Tools cannot become a desktop window
or merge into other panels. Press **Escape** during a drag to cancel. Focus the
grip and use arrow keys to select an edge, or **Home** to restore the left edge.
Tools has a grip without a close button. **View → Tools** hides or shows the strip.
It appears only when Preview is visible,
including Object Edit Mode; Welcome has no Tools strip.

Scene, Assets, Timeline, Inspector and plugin panels share a compact themed
**Title — Close** caption, both docked and floating. Drag a caption to float or
redock a panel; no separate float button is shown. Closing a panel hides it;
its View menu entry can show it again. The main application's standard window
controls and dialog controls remain available.

Older profiles migrate once to the default panel arrangement because their saved
dock trees can retain invisible Scene/Tools slots. Window geometry and internal
panel settings remain available; subsequent panel positions and visibility choices
persist. Choose **View → Reset Workspace Layout** to restore the arrangement.
Reset changes UI
placement and dividers, without editing project data. Tools' preview edge and
visibility persist alongside other panel settings. Older left/right placements
retain their side inside Preview; obsolete floating placements reset to the left.

Scene shows vertical hierarchy guides, smaller part icons and still smaller
visibility/lock icons. Their click targets remain wider than the glyphs. Project
assets use shorter rows with square checkerboard thumbnails and small subdued
source-format badges. Thumbnail changes do not affect original artwork or its
rendering resolution.

Timeline's Lock and Show columns use compact icon headings. The channel pane
starts narrower and gives additional window width to the animation area. Its
divider and manually adjusted channel column widths persist; document refreshes
do not reset them.

Timeline keys and the scrubber share the same frame mapping at every zoom and
horizontal scroll offset. The right-facing End flag and the shaded area
begin at the edge after the last playable frame cell. Seamless looping clips can
have a closing key one frame after their last playable frame; that key joins the
start pose without adding a duplicate held frame to playback. The flag has no
text label covering the ruler; the exact End frame remains in the title bar field.

Dividers reserve a single pixel, without spacer margins or a second bar above
Timeline. Hover highlights that line. Dock resize targets overlap nearby content
by a few pixels so the line stays easy to grab without reserving extra space;
internal Qt splitters provide the same overlapping hit area. Focus a dock divider
and use its axis's arrow keys to resize in 32-pixel steps.

Resize attached panels by dragging their dividers. Preview tool options overflow
within a horizontal scrolling row when space is limited; they do not reserve
their combined minimum width across the workspace or prevent panels from growing.
The row also stays contained when no project is open.

Skeleton-template drops on empty scene space create their own Object. A drop
onto an unlocked existing object joins that object, preserving the artwork and
the skeleton's placed pose. A previous selection does not change the drop target.
Dropped skeletons stay in the main Scene workspace, where their whole object can
be selected and transformed. Bare skeleton objects use their visible joints for
their selection area and transform handles; Object Editor still exposes bones.

Right-click the scene-name row in Scene and choose **Rename scene** to edit it
inline. Enter commits one undoable rename; Escape cancels. Scene identity and
settings are retained. Text and numeric fields use contrasting neutral selection
backgrounds and text in both themes, including Ctrl+A and embedded spin editors.

Use the **+** button beside the Scene filter, or **Add scene** in the scene-name
context menu, to create another scene. Click a scene header (or its eye), or press
Enter on it, to activate it. Only the active scene shows its objects and owns an
animation runtime. Scene switching pauses playback, closes scene-specific live
editors, releases their previews, and restores that scene's selection, zoom and
timeline cursor. Inactive scenes retain authored records without running their
animation or physics. All scenes save in the same project and share source assets.
Scene headers also offer Rename and Delete; the project keeps at least one scene.
Activate an inactive scene before dropping artwork onto its header.

Deleting a whole Object also deletes its owned armature, spring constraints,
helper controls, artwork and private actions. Reusable source assets remain in
the project. An Object whose bones have all been deleted remains selectable and
removable from Scene. Visibility icons are white when visible (dark in the light
theme for contrast), gray when hidden, and locks are muted green when unlocked
or muted red when locked.

Inside Object Editor, Delete removes the selected contents while preserving the
Object being edited, even after the last shape or bone is removed. Select All and
marquee selection exclude its container and outside scene folders. A single solid
shape becomes an empty container with the same Object identity when its artwork
is deleted. Undo restores the contents in one step. Return to Scene to delete the
whole Object, including an empty one.

Bindings displays connected relationships in expandable folders. Selecting a
folder and choosing **Unbind selected connections** releases its connections in
one Undo step. Object containment is structural: unbinding keeps parts inside
their Object. Rigidly bound artwork moves with its driver when either endpoint
is dragged. Bone parenting and skinning keep their ordinary rig-editing behavior.
In Object Editor, binding sources and targets are limited to the edited Object.

The preview toolbar's **Show scene context** eye button appears in Object Editor.
It displays the rest of the paused scene at reduced opacity as a reference.
Reference geometry never enters selection, marquee or transform hit testing.
The reference sample is cached while the source scene is unchanged and released
when the option is disabled or Object Editor closes. The option defaults off.

Assets now has **Objects | Imports | Content** tabs. New scene Objects are saved
automatically in the project-local Objects library. Drag a scene Object onto
Objects, or right-click it and choose **Save as Object**, to publish an existing
Object from an older project and reveal its card. Scene folders are organization
containers rather than saved Objects.

Double-click an Object card or drag it into the preview to place a linked copy.
Artwork, parts, meshes, bones, clothing, skin, bindings and Object actions are
shared. Editing any placement updates its definition and other placements in the
same Undo step, including inactive scenes. Each placement retains its own root
transform, visibility, opacity, scene arrangement tracks and motion-block timing.
Editing shared actions refreshes placed motion blocks while retaining their timing.
Deleting the final placement retains the saved definition and its source assets.
Removing a saved definition detaches existing placements; it does not delete them.

Use **Ctrl+C / Ctrl+X / Ctrl+V / Ctrl+D** to copy, cut, paste or duplicate selected
Objects. The same actions are in the Scene tree, preview and Object-card context
menus. Select a scene header to use these shortcuts on the entire scene. Pasting
a scene creates and activates a new scene with fresh record IDs, preserving its
links to project Objects. Cutting the last scene leaves an empty scene so the
project remains valid. Text fields retain their ordinary text clipboard behavior.
Pasting copied scene Objects into the Objects tab creates saved definitions without
adding placements to the scene. Duplicating a card creates an independent definition;
duplicating a scene placement retains its existing definition link.

Object/scene clipboard data is project-local because its sources belong to the
project. Use content packs for cross-project exchange. External scene parents,
layers and bindings to objects outside a saved Object are not part of its definition.
Nested parts belong to their containing Object rather than separate live definitions.

Imports dragged into the preview now display a full artwork ghost centered at the
pointer. The ghost follows pan/zoom without changing the project; the committed
artwork and pivot use that same point. The small drag thumbnail hides over the
preview and returns outside it. Drops into the Scene tree and menu/double-click
placement retain camera-center placement. Rig-only and empty Objects also support
centered placement. All placement changes are undoable.

In the timeline channel panel, **Channel** fills the available width. **Lock** and
**Eye** stay in compact columns against the panel's right edge, with consistent
icon padding and no unused trailing column. Resizing the timeline splitter changes
the name column rather than spreading out the state controls. This alignment also
applies after restoring older saved layouts or resetting the workspace.

Select one Object in the main Scene preview to show its pivot crosshair, including
rig-only and empty Objects. Drag the crosshair to move the pivot without moving the
artwork or armature, then use the rotation grip to rotate around that point. Pivot
edits stay with that placement; linked copies keep their own pivots. **Center pivot**
in the context menu resets it. Each pivot drag and rotation commits one Undo step.
Inactive private Object actions do not prevent editing the Scene placement's pivot;
existing animation in the active workspace keeps the normal keyed-pivot behavior.

**Show bone shapes** places skinned armatures using the same Object transform and
inverse binding matrix as the artwork. Bones stay on the character while moving,
rotating, scaling or placing a saved Object, including cursor ghosts and live
Spring previews. Object Editor retains its rig authoring coordinates; returning
to Scene restores the placement. Bone picking, onion previews, motion trails and
SVG bone overlays use the corresponding display geometry.

Drops from Templates, Imports and Objects into Main Scene place and select new
Objects in Main Scene, even when the pointer is over a full-frame background.
They do not open the background's Object Editor. Artwork created or placed at the
same depth is appended in front of the existing arrangement. Intentional rig,
motion and deformation target workflows retain their existing behavior.

The property strip includes **Z: Depth (Z)** for Objects and their parts. Its
default is **0**; larger values draw in front, smaller values behind. Equal Z
uses the existing scene layer/draw order. Parent Z offsets accumulate, so setting
an Object's Z moves all its parts together; part offsets remain relative to it.
This changes drawing/picking order, without changing X/Y position or scale.
The allowed range is −1,000,000 through 1,000,000. Root Z stays local to each
linked placement, and Reset restores it to zero. Bones do not expose Z editing.
