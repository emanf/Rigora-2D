# Selection, rigging and the consolidated toolbox

The left toolbox contains Select & transform (V), Pan (H), Bone Editor,
Spring Editor and Mesh editing (M). File actions occupy the top left; Undo,
Redo and Commands occupy the top right. The Parts / Images / Bones selector
replaces three separate target buttons. Duplicate move/rotate/scale tool buttons
and command-palette aliases are removed; underlying service entry points remain
compatible for automation and existing clients.

Mesh editing (M) toggles on/off. Select & transform (V) exits mesh, weight-paint,
pin and drawing tools and releases any read-only subdivision preview. To edit FFD
controls, activate Deformation tools explicitly; their own transform grips remain
available in Move mode. Bone Editor and Spring Editor buttons toggle their windows.
Add bone and Add pin inside Bone Editor also toggle independently. Closing an editor
returns to ordinary selection. Editors close on a project-tab change so an old
window cannot capture the new project's input.

## Everyday transforms

The preview header keeps tool settings on the left and camera dimensions at the
far right, after the view buttons. **Show bones** beside Grid toggles bone shapes
and labels while keeping picking, marquee selection and transforms active.
Selected bones retain transform handles for positioning while the overlay is off.

- Drag selected artwork to move it. Resize squares and a circular
  rotation grip are visible together. Artwork corners resize proportionally;
  side handles resize one axis. A single bone rotates/scales about its base joint;
  FK rotation applies the same angle at each selected joint. The upstream pivot
  measures the drag; children inherit each selected ancestor's rotation.
  Artwork rotation uses the selection center; artwork resize uses the
  opposite grip. FFD controls and mesh vertices also expose resize and rotation
  grips without requiring a different tool.
- The grouped **Bone / Chain (FK) / Rig / IK** toggles replace the scope dropdown.
  **Chain (FK)** is the default: a selected bone carries its descendants without
  moving ancestors. Each selected joint receives the drag angle once: selecting
  a parent and child bends both joints. Unselected children retain their local
  transforms and inherit motion. Enabled IK endpoints continue to move their targets.
- **Bone** drags affect selected bones only. Unselected parents and children retain
  their world geometry. Child local transforms compensate when their parent is
  selected; this preserves the hierarchy without moving those child bones.
  Ctrl-click adds/removes bones; marquee and Ctrl+A select multiple bones.
  Dragging a selected set moves that set together, with no double translation.
- Bone joints align within 14 screen pixels while translating. **Alt** bypasses
  alignment, including when pressed or released mid-drag. Rotation can align a
  upstream selected joint only to a target on its existing rotation radius,
  preserving bone length and the anchored pivot. Independent FK branches do not
  use a shared rotation magnet. A white target marker indicates alignment. Snapping
  excludes moving, hidden and locked bones and never changes parenting.
- Choose **IK** beside Grid for connected-chain posing.
  The chain root stays anchored, joint lengths remain constant, and enabled IK
  endpoint targets use the existing target solver. This gesture deliberately
  allows movement of ancestor bones outside the current selection.
- **Rig** transforms the selected connected roots and descendants; unselected
  independent roots remain fixed. Ctrl-drag retains the selected set.
- The selected tip is a direct rotation handle, including where a child starts.
  A pivot marker shows the rotation origin. Shift snaps rotation to 15° increments.
  Bone, artwork and mesh/FFD grips share directional native resize cursors and a
  Material rotation cursor; active drag cursors remain latched until release.
- Tool-specific header options replace irrelevant controls: scene selection
  filters, bone movement scope and minimum joint angle, drawing guidance, mesh
  wireframe and selection guidance, or pan guidance. Grid and zoom remain shared.
- **Min joint** applies to the selected bones' direct-parent joints. New joints
  default to 30°, 90° permits right-angle corners and zero disables the limit.
  Existing bones without saved limits remain unchanged. Limits evaluate after
  constraints/springs and before deformation, including playback and export.
- Transient poses and skinned geometry update during the drag. Release creates
  one undo step; Escape cancels. At an animated frame the same services produce
  timeline keys, including child compensation. Unsupported shear and locked
  compensating children are rejected rather than silently changing geometry.

## Bind imported artwork

1. Open Bone Editor and choose the artwork in its image picker.
2. Add bones over the artwork. Select a bone from the intended skeleton.
3. Press **Bind image to bones**. With a single skeleton, explicit bone selection
   is optional. With multiple skeletons, selection determines which one is used.
4. Use **Preview / pose** and manipulate the bones with the universal handles.

Drawing, adding image pins, binding and entering Pose leave temporary subdivision
preview so it cannot block authoring clicks. Subdivision settings still preview
live when adjusted; Apply retains the prepared topology explicitly.

## Scene parenting and ordering

Drop bones onto a bone in the same skeleton to reparent their selected branches.
Drop onto the skeleton or scene root to detach; drop above/below a sibling to
change sibling order. Parent/child selections move once as a branch. Cycles,
cross-skeleton transfers and locked targets are rejected. Parenting changes that
require animation or constraint rebaking are rejected with an explanation.

Drop artwork or folders onto a bone for rigid attachment. The tree displays the
attachment under that bone. Drop onto another bone to reattach, or into a folder
or the scene root to detach. Attachment keeps the evaluated world placement;
bone reparenting keeps rest-world placement. Each drop is one undo step.
For deforming artwork, use **Bind image to bones** instead of rigid attachment.
