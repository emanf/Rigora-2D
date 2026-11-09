# Objects, Scene and Object Editor

**Scene contains whole Objects. Object Editor contains their internal parts and actions.**

Object Editor hides the Project and Welcome tab strip until you return to Scene.
Assets keeps its existing visibility, so an open Assets panel stays available for
adding artwork and reusable content. Returning to Scene restores the saved panels.

Imported images start as solid Objects, with no generated bones or root dot. An
Object can contain one image, multiple images, vector shapes and part folders.
Adding bones makes it a rigged Object; a solid Object needs no skeleton.

Click selection follows the visible artwork from front to back. Transparent image
margins, SVG holes and gaps between parts let clicks reach artwork underneath.
Picking follows the evaluated deformation, UV placement, flipping, opacity and
Depth (Z). SVG detail uses the original vectors at the current zoom. Scene selects
the owning whole Object; Object Editor selects its editable part.

Hover feedback, double-click entry, context menus and template targeting share
the painted-coverage rule. Hidden and locked artwork cannot steal an editable
click. Source artwork must finish loading before it has painted coverage; its
tree row remains available. Visible transform handles, camera borders and empty
Object/rig controls retain their explicit targets. Marquee selection and Mesh Edit
keep their geometry-based selection tools.

## Assemble an Object

- Choose **Object → New empty object** to start without artwork or bones.
- Double-click an Object in Scene or the preview to open Object Editor. An empty
  Object has a small editable marker. The right-click menu also offers entry.
- Use **Parts → Add image parts…**, draw vector shapes, or drop project assets
  and external artwork into the editor. PSD/ORA folders retain their hierarchy.
  Successful import, placement and ownership form one Undo step.
- Use **Make object from selection** to combine existing artwork. Adding parts
  to a single animated image retains its identity, transform and authored keys.
- In Object Editor, select individual parts, move them, change their draw order,
  create folders and rename with F2. The divider resizes the Layers area.
  Deliberate edits to a standing foot also carry its contact control, so the
  artwork moves visibly while animation playback retains grounded contacts.
  Foot bones support direct movement, tip rotation and numeric pose edits in
  **Bones**. These edits key the foot and its standing contact together in the
  current action; other actions and the opposite foot retain their poses.
- Outside Object Editor, selecting a part selects its whole Object. Scene lists
  Objects and scene folders; it does not expose internal bones or mesh controls.
  Drawn shapes and imported artwork use the Object icon in Scene, while editable
  parts retain their source thumbnails inside Object Editor.
  Whole-Object visibility preserves individual clothing/part visibility. Locking
  protects the internal parts and rig. Deleting a complete Object removes its
  owned artwork and rig, while imported source assets remain reusable.
- Moving, rotating or resizing a whole Object in Scene carries its body, clothes
  and feet together, including during placed actions. Auto key records the Object
  transform without rewriting its internal rig or source animation keys. A live
  drag commits one Undo step on release.

## Separate editing and playback contexts

The sidebar places the Object/Character name and its view selector on one row.
**Object Tree** combines artwork, folders, skeletons and bones in one hierarchy.
This same tree remains visible while editing **Skin**, **Clothing** and
**Animations**; its divider controls how much room the detail panel receives.
Compact Assets, Add Bone, folder, binding and remove actions sit above the tree.
Assets is the shared place to import artwork and drag it into the current Object.
Per-row visibility and lock controls remain available. Flip controls remain in
the main property toolbar. Binding options and advanced material/shape controls
use collapsible sections.
Bind/unbind icons share the same commands in the main toolbar and the layer
action strip. Bone Editor, Spring Editor and Mesh Edit remain accessible through
the existing toolbox/menu commands. Other sidebar pages use compact Material
action icons with descriptive tooltips and accessible names for create, duplicate,
import and default operations.

Skin color edits preview immediately in the color picker; **Apply** commits one
Undo step and **Cancel** restores the previous look. A channel with existing
color keys updates its current key at the playhead even when Auto key is off,
matching transform editing. Unanimated colors remain base edits unless Auto key
is enabled. Saved skin presets remain reusable snapshots.

Layer expansion, selection and scroll position survive ordinary edits and Undo.
Scene and individual Object Editor contexts keep their own tree navigation.
Skin/clothing/motion cards and project source assets retain surviving selections
and scroll positions when their rows rebuild.

The viewport header shows its current zoom percentage in Scene and Object Editor;
Object Editor exit restores the Scene zoom and its readout. The timeline has its
own independent percentage beside its zoom buttons, with 100% defined as 8 pixels
per frame. Its readout follows wheel/button zoom and Frame curves/keys.

Object Editor offers **Parts, Bones, Skin, Clothing and Motions** pages. It frames
the composition, hides unrelated geometry and skips unrelated mesh deformation
and spring constraints. It shares the document, source assets and Undo history;
it does not create a separately saved duplicate scene. Opening a saved card from
**Assets → Objects** uses a temporary authoring tab linked back to its owning
project; this also supports definitions with no scene placements. Save still
saves the owning project. See [linked Objects](linked-objects.md).

Every named Object animation has an independent timeline and keys. **New empty
animation** can be used before any parts or bones exist. Create Idle, Walk, Run,
Jump or another named action, then author its real keys. Switching actions
remembers their respective playheads. Object timelines support part transforms,
bones, mesh deformation, visibility, opacity, skin, clothing and appearance keys.

The trash button beside **New empty animation** and **Duplicate** removes the
selected animation after confirmation. The dialog names the animation and reports
linked Scene placements that will also be removed. Cancel is the default. Undo
restores the action and its placements together; the Object and artwork remain.
Animations referenced by a state machine must be removed from that definition first.

The **Scene** back button restores the Scene animation, playhead, zoom/pan, docks
and timeline height. Entering or leaving Object Editor never creates a clip or
authors visibility/camera changes. Changing project tabs exits Object Editor and
pauses the previous document; Scene cursors remain independent across projects.

## Bones and mesh

1. Open the Object and choose **Bone Editor → Add bone** from the toolbox. Drawing over
   solid artwork converts and binds it automatically when automatic binding is
   enabled. Bone and mesh tools opened from Scene enter Object Editor first.
2. Draw from a joint to attach a child. Alt bypasses snapping and parenting for
   free placement. Shift constrains direction to 45-degree increments. The live
   drawing preview follows both modifiers.
3. Each skeleton has a **Rig Root** in the bone tree. This zero-length master
   control moves, rotates and scales its chains in FK and Rig modes. It is
   excluded from automatic skin weights and stays kinematic during spring motion.
   The first deforming segment beneath it can spring around its anchored base.
   Independent chains share the master control without joining each other's tips.
   Existing rigs gain this control in one undoable upgrade when opened for editing;
   existing bone IDs, rest geometry, animation channels and skin bindings remain.
   Add Bone prepares a Skeleton and visible, selectable Rig Root before the
   first segment is drawn. Rig Root cannot be deleted individually; deleting
   the complete Object removes its skeleton too.

   Draw new chains directly where needed; snap to a bone joint to attach them.
   There is no separate drawing-origin marker. In Bone mode, moving, rotating or
   scaling Rig Root keeps the deforming chains in their existing world poses.
   Normal Chain/FK edits carry descendants; single-bone edits preserve unselected
   world poses. IK pulls anchor the deforming chain's base and do not pull Rig Root.
   Object Editor fits its local content and omits the Scene camera rectangle.

   Built-in Templates place Rig Root at the authored pelvis/body base or the
   flexible chain's attachment. Child poses and absolute animation translation
   keys are rebased together, so the artwork and animations retain their original
   placement. Existing project rigs keep their edited root positions.
4. Select image parts, choose a bone in Bones, then use the **Bind selected parts**
   icon in the main toolbar or layer action strip. Normal binding
   bends the mesh with its skeleton; **Rigid** follows one bone. Reattachment
   transfers the binding. **Remove binding** makes the artwork solid again while
   retaining the shared rig and reusable source motions.
5. Edit Mesh supports Full/Mask/Grid subdivision, selected vertices and smooth
   area dragging. Mesh deformation keys belong in the Object's named animation,
   rather than the Main Scene's global Dope sheet.

Automatic refinement only replaces untouched coarse import grids. Edited UVs,
topology, protected points, deformation stages and keyed vertices are preserved.
SVG deformation renders original vectors at output resolution, not thumbnails.
**Bone Editor → Add pin** anchors the clicked bound artwork in its displayed pose.
Pin placement picks painted artwork underneath bone controls, independently of
the current artwork selection and scene selection filters. Transparent gaps,
locked parts and empty space do not fall back to the previously selected image.
Clicks map back through evaluated triangles, so posed images accept pins without
jumping to the undeformed source position. **Attach to → Object root** is the
default: bones can pose around a held region while the whole Object still carries
it. Choose a bone to attach that region to the bone instead. Existing saved bone
pins retain their targets.

Pins remain visible across artwork layers while Bone Editor is open. Click a pin
to select it, Ctrl-click to toggle several, drag to reposition, and press Delete
to release selected anchors. Selected pins appear red with their influence radius
and attachment. **Radius**, **Strength**, and **Attach to** edit selected pins; with
none selected they configure subsequent placement. **Add pin** stays active for
repeated clicks. Escape cancels a setup drag. **Preview / pose** leaves pins visible
and makes setup read-only while testing bones; Add pin resumes setup editing.
Each completed edit or group drag has one Undo step. Repositioning preserves the
old vertex and its keys/weights; an interpolated vertex supplies the new anchor.
Release pin preserves ordinary skin weights. Binding errors appear in the Bone
Editor status. Moving an anchor onto another anchor is rejected without changes.

## Skin, color groups and dress defaults

In **Character Creator**, card checkboxes retain alternatives for the created
Object; clicking a card chooses its visible default. Clothing, eye/lip styles,
eyebrows, nose, hair, facial hair and eye/hand poses support retained choices.
Facial and pose checkboxes toggle independently, even for the visible default;
clicking their artwork never checks it. Checking another part does not preview it.
Saved recipes preserve these choices. The visible default and essential blink,
speech and selected-action states remain available when creating the character.
**Keep previous options** preserves clothing when choosing another garment or set.
The creator shows a thin, full-width loading bar attached to the preview's bottom
edge during preparation. Animation
cards choose the preview action; fixed Play/Pause and Repeat icon buttons sit
at the bottom-center of the canvas. Presets and clothes share one ground line.

Created facial alternatives appear as **Eyes styles**, **Mouth styles**, and
other named groups in Object Editor's Clothing cards. Style choices remain
independent of blinking and lip-sync. Hand poses replace each other, and gloves
cover the underlying hand variants during animation.

Hair offers Curtain, Wolf cut, Twin tails and Mohawk alongside the existing styles.
Covered crowns use a fitted base under the tufts to prevent scalp gaps. Foreheads,
temples and the mohawk's shaved sides remain intentionally visible. Retained hair
styles switch their front and back layers together, including the bald option.

Mustaches use 17 distinct silhouettes plus None, from thin Pencil and Dali to
Chevron, Horseshoe, Walrus and curled styles. They use Hair paint, stay fitted
in front/profile views and switch independently in the retained-style cards.
New robots start with gray Hair paint so facial hair contrasts with the visor;
saved artwork and explicitly chosen colors are preserved.

Animal artwork uses neutral outlines. Leg sides and feet are outlined while their
top edges stay open into the body. Matching limb colors and adjusted root/reach
keep standing feet aligned. Bird beaks attach to the head as editable child parts
and use different front/profile placement. Open human/robot hands have four graded
fingers and a separate thumb, with mirrored sides and stable wrist sockets.

**Skin** detects literal SVG fill, border and gradient-stop colors, including
group-inherited paints and literal stylesheet colors. Select image parts or
folders and change their swatches. **Apply colors to all object parts** extends
the scope. Border width and raster tint opacity are also editable. Color pickers
preview changes live: Apply commits one Undo step, Cancel restores the prior look.
The original embedded SVG is retained.
Color groups and saved skins use visual card grids. Skin cards show the saved
palette rather than plain names in a list.

In **Skin → Skin sheets**, create a group such as Body colors or Accessories.
Select its parts, name the look and choose **Save selected look**. A skin stores
the evaluated paints, border and raster tint of those parts; it copies no image
files or mesh geometry. **Set default** marks the group's default option. The
first saved option starts as default. Groups can be chosen independently.

In **Clothing**, create groups such as Dress or Hats. A variation can contain
several imported image layers. **Add clothing…** imports directly into the Object;
**Use selected parts as a variation** registers existing parts. Groups support
one visible variation, several variations, or none, including on solid Objects
without bones. **Set selected as default** saves the group's default variation;
select the group row itself for a default of no clothing.
The category picker and thumbnail cards replace the visible variation tree.
Card checkboxes wear/hide variants, including multiple variants where enabled.
Select a category without a variant for a default of no clothing.

Both workspaces offer **Key choice at playhead**. Enabled, choosing a saved skin
or outfit writes discrete choice keys in the active timeline. Disabled, the
choice changes the base appearance. Before the first choice key, the default or
source action stays in control. Scrubbing reflects the evaluated choice.

Object Editor can animate these choices within an action. Main Scene can make
its own choices at any frame, overriding the Object action from the first Scene
choice key onward without changing that action's keys. Ordinary direct color,
tint and shape-mix edits also support Auto key and continuous RGB interpolation.
Clothing choices switch visibility; they do not generate new garments, masks or
cloth simulation.

## Use Object actions and choices in Scene

Select an Object and open **Inspector → Transform**. Its Object section lists
the animations, skins and clothing groups defined in Object Editor. Choose saved
looks here without opening internal parts.

Drag a whole Object from Scene onto the Dope sheet. The
picker asks for an animation, start frame, duration, speed and repeat. **Add
animation…** opens the same picker. Empty actions need real keys before placement.

- Drag an Animation span to move it; drag its running icons to trim duration. Left trimming
  preserves source phase. Escape cancels a pending drag.
- Right-click a span for **Speed ×**, source choice and looping. Speed changes
  source-time progression independently of duration. Looping cycles within the
  span; disabling it holds the last source pose.
- Remove action or Delete removes the instance and preserves the source action.
- Editing source keys updates placed instances while preserving their timing,
  trim and speed. Overlaps use ordered track blending; automatic crossfades and
  motion-matching transitions are not provided by this arrangement view.

Scene's Dope sheet shows whole-Object Transform, Visible and Opacity lanes,
alongside single Skin and Clothing lanes. Palette and shirt keys open flat saved-choice
card grids, with collections selected inside the popup. Global transforms and appearance choices
remain editable above placed actions. Source bone and mesh tracks are edited in
Object Editor. Each workspace uses the same evaluated geometry and appearance
values for preview, persistence and export.

Shared paint changes batch matching parts into one preview publication, including
existing keyed skin colors. Clothing cards and layer eye/lock controls apply
captured part identities after the native item event completes, so replacing a
hand does not destroy the item while Qt is still handling its click.

Object Editor's sidebar width and Timeline height are remembered separately from
Scene's dock arrangement. Closing from Object Editor restores and saves the Scene
layout before shutdown.

## Draw shapes and place pivots

The Draw tool creates embedded SVG ellipses, rectangles, triangles, diamonds and
stars. Shift keeps equal dimensions; Alt draws from the center. Selection handles
follow orientation. Corner handles preserve proportions; the W/H ratio lock or
Shift constrains side handles too. Alt resizes about the pivot.

The crosshair is the pivot. New artwork starts with it at the center. Drag it to
change the rotation center without moving the artwork. It snaps within 14 screen
pixels to corners, edge midpoints and center; Alt bypasses snapping. **Center
pivot** resets it. Existing transform animation keys the compensated pivot and
position together. Shape tweening supports compatible contours made by the Draw
tool; arbitrary unrelated SVG path correspondence is not inferred.

All authoring operations use common Qt-free application services and the document
history. Complete gestures, placement and multipart look edits commit one Undo
step. No additional runtime dependency or online service is required.
