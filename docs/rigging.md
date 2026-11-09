# Rigging workflow and solver contract

Prompt 5 adds a rest-bone editor, original templates, symmetry tools and transform
constraints. `RigService` commits validated `ScenePatch` commands to the canonical
`DocumentService`; successful authoring edits support undo/redo. Geometry and
solvers remain Qt-free and share the normal animation evaluator.

## Desktop workflow

Create a project and press **B** to draw a bone. A circular cursor previews the
placement point and snaps to the root or tip circle of a visible editable bone
within 14 screen pixels. Starting at either circle attaches the new bone as that
bone's child, at local zero for a root or local length for a tip. This also works
when constraints have moved the parent. Coincident joints prefer tips. Starting
elsewhere creates an independent root. Hold **Alt** to bypass snapping and
parenting, including during an active drag; releasing Alt restores snapping.
Hold **Shift** while dragging to lock the drawn direction to 0°, 45°, 90°, 135°
and the remaining 45° directions. Pressing or releasing Shift updates the live
preview immediately. Alt still bypasses joint magnets independently; magnets
cannot pull a Shift-constrained endpoint away from its locked direction.
The drawn endpoint also snaps to joints for geometric alignment; existing bones
are not reparented or welded into cycles. Hidden and locked joints are excluded.
Bones use the gray armature SVG with circular joints and a live drawing preview.
While drawing, bones remain visible over artwork on every Object Edit page,
including appearance pages and when the normal bone overlay is hidden. The
overlay preference is retained when returning to selection.
**V** or the selection arrow selects bones in red and exits
drawing and specialized mesh editing. Repeating **B** also exits drawing; Add bone
and Add pin in Bone Editor are toggles. Closing Bone Editor restores selection.
Right-click clears selection
and cancels a gesture. **R** toggles rest-rig editing and animation playback. Rest
mode ignores tracks but evaluates constraints; set an IK rule to FK or disable it
when editing its rest angles. Each tab retains its rig mode/tool/selection.

The viewport shape comes from the editable `assets/shapes/bone.svg`, including
both circular joints. Replace that asset and restart to change the appearance;
the [asset guide](../assets/README.md#replacing-the-bone-shape) specifies its root
and tip anchors. Rendering and hit testing both follow the SVG silhouette.

The **Rig** inspector provides selection, drawing and endpoint editing. Gestures
preview actual bones and skinned artwork on every pointer move, then commit once
on release. **V** selects and transforms using grouped toggles beside Grid.
**Chain (FK)** is the default and carries descendants. **Bone** preserves
unselected world poses through child-local compensation. **Ctrl-click** toggles
bones; Ctrl-drag retains the selected set. **IK** poses the ancestor chain with
its root anchored; **Rig** transforms the connected roots and descendants.
Single-bone rotation and scale use the base joint. FK rotation applies the same
angle delta to each selected joint, so selecting two connected bones bends both.
Unselected children inherit motion without changing their local transforms.
The upstream base joint measures the connected selection's drag angle.
Chain body drags rotate; Bone body drags translate. Drag the selected tip or circular rotation grip to rotate;
the selected tip takes precedence at an overlapping child joint. Hold Shift for
15° angle snapping. Hover and drag cursors distinguish movement, rotation,
directional resizing, marquee selection and panning. Drag empty space to box-select; Ctrl+A selects
all editable bones. The same selection box exposes move,
rotate and scale without switching tools. Escape, right-click, focus loss and document changes
cancel an unfinished gesture without dirtying the project or adding undo entries.
Rotation handles show the authored pivot; endpoint edits
handle pivots/scales. Numeric controls edit length, position, rotation, pivot and
scale. Unchanged fields retain stored precision. Color accepts `#RRGGBB`.
Visibility and locks persist. Locked/hidden bones remain inspectable from the tree
for unlocking/showing; viewport hit-testing excludes them. Named groups support
select, hide/show and lock/unlock. Group selection respects ancestors. Ctrl-click
in the viewport toggles selection; contextual properties use the primary bone.

Translation aligns selected joints to other editable joints within 14 screen
pixels. Hold **Alt** to bypass alignment; toggling Alt updates the current preview
without another pointer move. Rotation alignment preserves the pivot and radius.
Alignment never reparents. Use Scene-tree drops for explicit bone parenting,
sibling ordering and rigid artwork attachment; see the
[Scene parenting guide](unified-tools.md#scene-parenting-and-ordering).

**Min joint** edits the minimum interior angle at each selected bone's direct
parent joint. Straight is 180°, a right angle is 90°, and zero disables the
limit. New connected bones use 30°; older bones without a saved value remain
unrestricted. Multiple selected joints receive one value in one undo step.
Mixed values display an approximation prefix. Limits are evaluated after
constraints and springs, before mesh deformation, for GUI, API and exported
frames alike. Rest/bind geometry remains authored. The limit preserves bend side,
joint origins and lengths, including mirrored or nonuniformly scaled parents.
Enabled limits take precedence over selected-only world-pose preservation when
a transform would otherwise fold a joint below its allowed angle.

Chain, Biped and Quadruped are original rest templates. Names gain `.001` suffixes
to avoid collisions; terminal `.L`/`.R` names swap on mirroring. **Frame rig** fits
visible bones. Mirror copies a branch across the chosen scene X axis, with new
UUIDs and reflection scales preserving geometry. Motion/constraints/bindings are
not copied. Reparenting, insertion and deletion preserve children's **rest-world**
transforms. Insertion splits length and creates an intermediate child; deletion
promotes children. Cycles, cross-skeleton parents, unstable inverse spaces and
required shear fail atomically. Referenced bones require binding removal before
deletion. These commands do not retarget arbitrary animated or constrained poses.

## IK and constraints

On **Constraints**, choose an owner, solver and target, then Add. Two-bone IK can
create an independent object target automatically and initially chooses a direct
child. Select the desired second bone when the root branches. Target fields move
object controls in scene space; highlighted target handles are also draggable.
Apply edits to a selected rule; Remove retains its reusable target object.

| Kind | Settings and behavior |
| --- | --- |
| `two_bone_ik` | `end_bone_id`, `mode` (`ik`/`fk`), `bend` (+1/-1), `stretch` (false), `max_stretch` (1.5, valid 1–10), optional `min_reach`/`max_reach`. Analytic planar root/child solution. |
| `aim` | Positive local X faces target origin with optional degree `offset`. Keeps the driven origin even with a pivot. |
| `copy_transform` | Copy target world affine transform into owner parent space. |
| `limits` | Optional `min_x`, `max_x`, `min_y`, `max_y`, `min_rotation`, `max_rotation`; clamp local values. |
| `parent`, `space_switch` | Target world matrix times six-component affine `offset`. Authoring initially preserves world pose; space changes can keep the current solved pose. |
| `pin` | Pin local `point_x`/`point_y` to scene `x`/`y` or target origin. Creation captures the current fixed origin by default. |
| `track` | Follow target position plus `offset_x`/`offset_y`, preserving linear transform. |

IK requires positive lengths, child position `(root.length, 0)`, joint scale
magnitudes 1 and zero joint pivots. Reflections and invertible ancestor transforms
work. Unsupported geometry warns without altering the pose. Targets clamp to
geometric/configured reach. Stretch changes evaluated lengths only, up to its
bound. The editor's maximum reach value 0 means automatic chain reach; the Python
contract permits explicit zero. Bend direction is screen-clockwise/counterclockwise.
Coincident targets use authored root direction for deterministic folding. FK mode
skips IK and uses authored/animated transforms. Interactive chain pulling also
supports more than two bones with length-preserving joint projection and a fixed
root. It clamps unreachable targets rather than stretching. Root, tip, interior
and offset branch attachments retain their authored local offsets. Pulling an
IK end bone moves its target automatically. Other active constraints on the path
still require their explicit controls; transforms requiring shear fail without
mutation. The two-bone constraint remains the animated IK solver. Chain pulling
is geometric posing, without gravity, inertia or collisions.
Skinning and mesh deformation are provided by Prompt 6.

## Evaluation and extension

Animation sampling/blending → hierarchical FK → constraints → deferred deformation
→ render preparation. Dependencies on driven targets and ancestors run first;
same-owner rules follow `(order, stored_index)`. Self/branch and cross-rule cycles
warn. Cyclic/blocked rules are skipped while independent rules continue. Each
solver runs atomically: invalid parameters or numerical/geometry failures restore
its input and add a named warning. Unknown kinds retain data and warn.

`ConstraintSolver` is a callable `(Constraint, ConstraintContext) -> None`.
Context methods `.node`, `.local`, `.world` and `.position` expose working geometry
and propagate descendants. Solvers must write only their owner's branch, use
explicit targets/parameters and remain deterministic. They must not mutate
authoring data or retain previous-frame state.

Inject extra kind identifiers/callables into `SceneEvaluator(..., solvers=...)`,
`AnimationSession(..., solvers=...)` or `DocumentService(constraint_solvers=...)`.
Instances own registry copies; the document exposes a read-only view. Animation
and rest-rig preview use the same injected solvers. Opening a project never
discovers/imports executable plugins. Installation/versioned SDK is later work.

```python
from rigora.application_services.documents import DocumentService
from rigora.application_services.rigging import RigService

document = DocumentService()
document.new("Character")
rig = RigService(document)
root = rig.create_bone((100, 100), (200, 100))
child = rig.create_bone((200, 100), (300, 100), root)
rule = rig.add_constraint(root, "two_bone_ik", end_bone_id=child)
pose = rig.preview_pose()
```

The headless CLI solves saved rigged projects through that same engine.
Bone metadata and solver settings serialize in format 2 with optional defaults.
See [deformation requirements](deformation-requirements.md) for the retained
FFD/customized-deformation request for Prompt 6.
