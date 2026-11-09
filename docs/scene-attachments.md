# Scene attachments

Implementation contract, authorized 2026-11-06. Scene objects remain independent
placements. Attaching a complete object preserves its internal skinning, bones,
springs and animation. Rig/part binding remains available separately.

Work proceeds through verified slices:

- [x] Regression guards and repair for placed bone targets and whole-object skin preservation.
- [x] Typed attachment state and reusable named points, backed by canonical constraints.
- [x] Held Attachment timeline keys for pickup, transfer and release; deterministic seeking.
- [x] Beginner-friendly attachment card, target picking, point editing and Scene manager.
- [x] Integration with track discovery, API, object reuse, deletion and export evaluation.
- [x] Offscreen interaction, persistence and regression checks; measured playback and scored review.

An attachment has one follower, a target object/bone or World, optional named
target/source grip points and an editable offset. Keep position is the default;
Snap grip explicitly aligns the points. Releasing preserves the evaluated pose
and does not remove the target's rig or physics.

Attachment points belong to their owning object/bone definition. Their IDs are
local to that owner so reusable instances can share point definitions without
sharing Scene relationships. Target references use placed instance identities.

Static relationships are stored once as constraints. A dedicated
`object.attachment` lane holds keyed states in key metadata; normal key identities,
locks, mute state, copying and Undo remain canonical timeline operations. State
offsets are captured on authoring, not computed from the last played frame.
Inserting the first later pickup also writes an initial World state. Explicit
"At this frame" and "Whole scene" modes distinguish animation from setup edits.

The engine resolves final placed target matrices after skeletal evaluation,
without modifying bind-space bones. Compile dependency ordering and held-state
lookup once per immutable revision. Validate cycles, missing targets and point
references at service/project boundaries. No executable rebuild is part of this work.

## Pick up an axe

1. Place a character and an axe as separate Objects in the Scene.
2. Select the axe. Open **Object → Attach object…** or its Scene context menu.
   **Object → Scene attachments…** opens the same searchable manager.
3. Under **Choose what it follows**, expand the character and choose
   **Right hand → Grip**. Search for “hand” to narrow the tree. **Pick in scene**
   also accepts a visible bone or painted object; Escape cancels picking.
   Picking chooses a target and does not attach, move or select Scene artwork.
4. Keep **Keep current position** to retain the axe's placement, or choose
   **Snap grips together** to align the axe's grip with the hand's grip.
5. Choose **Whole scene (setup)** for a persistent relationship, then click
   **Attach object**. Moving the character or posing its hand now carries the axe.
   Dragging the axe itself adjusts its normal transform relative to that relationship.

The selected Object's Inspector includes a **Scene attachment** card. **Edit…**
opens setup controls. **Key here…** opens the same editor at the playhead.
The Inspector is optional; the Object menu and Scene context menu remain available.

## Animate pickup, transfer and release

1. Put the playhead where the character picks up the axe.
2. Open **Add tracks → Axe → Attachment**, or use **Key here…** in the Inspector.
3. Select the hand/grip and **At this frame (key)**. Click **Attach object**.
   If this is the first later pickup, Rigora also writes an initial independent
   state so the axe does not follow the hand before pickup.
4. At a later frame, choose another hand and apply a new attachment to transfer it.
   Keep position avoids a jump at the transfer frame.
5. At the release frame, open the Attachment editor and click **Release object**
   in key mode. The axe keeps its evaluated placement and stops following.

The Object has one flat **Attachment** timeline row with link-icon keys. Keys hold
their state until the next key; they do not interpolate between targets. Right-click
an icon to edit its target, timing, grip or offset. Normal key moving, copying,
deleting, Undo, track locks and evaluation muting apply. Generic key insertion
captures the current relationship, including grip metadata.

**Whole scene** replaces the selected Object's attachment keys across its Scene
clips. It respects track locks. Use **At this frame** to change one pickup or
release while retaining the rest of the performance. Scene attachment tools are
separate from the main Auto Key switch.

## Register grips and adjust the fit

Hands provide **Joint**, **Grip** (halfway along the hand bone) and **Tip** points.
Objects provide **Object origin**. Use **Edit grip points…** to add a named point
on the prop, such as “Handle”. Select it under **Object's grip** before snapping.
**Edit target's grip points…** registers a point directly on the selected target.
In Object Editor, **Object → Attachment points…** edits the selected part or bone.

Point X/Y and rotation are local to their owner. Grips retain stable identities
when renamed or moved. A point used by setup or a key cannot be removed until its
references are changed. The service/API also supports per-view point registration.
Enable **Fine alignment**, then use **Grip offset → Apply offset** to adjust the fit.
The Rotation and Scale
options independently control which target components the prop inherits.

Named grips are reusable Object content. Placed Scene attachments remain local
to each instance and are not copied into saved Object definitions or packages.
Copying an entire Scene remaps attachment targets and held-key references.

## Safety and scope

Attaching a complete character retains its skinning, skeleton, springs and source
animation. Release removes only following behavior. Rig bindings continue to manage
parts, bone parenting, skin weights and their physics cleanup separately; their
manager does not list or remove Scene attachments.

Missing points, self-links, dependency cycles and locked targets fail atomically.
Deleting a target Object or bone repairs dependent setup and key references,
preserves each affected prop's current placement, and supports one-step Undo.
Deleting a bone from Object Editor captures outside props in Scene space.

This workflow has one active target per Object. It does not create automatic
two-hand IK, blended dual grips, collisions or a visual point-drag editor. A second
hand needs separately authored posing; attaching a prop back to its own driving
hand would create a cycle and is rejected.

## Export

Rendered output uses evaluated attachment poses. Editable engine exports sample
the resulting source transforms while retaining the original Scene hierarchy.
Native TRS animation cannot encode affine shear from some rotated, nonuniformly
scaled attachment combinations. Export preflight reports this explicitly; use
uniform target scale, disable Follow Scale, or choose baked sprites/video.
The engine adapters do not recreate a live native attachment solver.

## Shared services and API

`SceneAttachmentService` owns attach, detach, key-current, offset editing and named
point operations. It uses one command transaction per user action. The Qt-free
domain model validates point definitions and held states; the evaluator compiles
dependency order for distinct target states once per revision and binary-searches
held keys during playback. Scene following changes evaluated world matrices and
retains authored local controls and bone bind space.

Plugins use `request.service("scene_attachments")`. Python/CLI/MCP operations are
`scene_attach`, `scene_detach`, `scene_attachments_inspect`, `attachment_point_save`
and `attachment_point_remove`. Supply `frame` for keys; omit it for setup.

```python
# Existing placed Object/bone IDs returned by project inspection:
api.execute("scene_attach", {
    "sources": [axe_id], "target": right_hand_id,
    "point": "@grip", "frame": 40, "snap": False,
})
api.execute("scene_detach", {"sources": [axe_id], "frame": 90})
```

The same API supports dry runs, transactions, revision checks and Undo.
