# Binding system review and Scene attachment proposal

Reviewed from the current Windows source on 2026-11-06. Application behavior was
not changed. Existing tests ran offscreen; reproduction documents were in memory.

## Assessment

**Overall: 4.2/10. Ease of use: 3/10.** The overall score is the equal-weight
average of these criteria, specifically for binding and Scene prop interaction:

| Criterion | Score | Basis |
| --- | ---: | --- |
| Functional correctness | 4/10 | Ordinary object following works; placed-character and whole-object cases have confirmed failures |
| Ease of use/discovery | 3/10 | Several meanings of Bind, long flat target lists, a consequential Rigid checkbox and object roots labelled as folders |
| Animated pickup/release | 2/10 | Parent following exists, but target switching, influence and attachment state lack a complete keyed workflow |
| Relationship management | 5/10 | Searchable grouped inspection and selective removal exist; connected-component grouping mixes rig internals with Scene relationships |
| Undo/data protection | 7/10 | Atomic transactions, cycle/lock rejection and persistence are tested; unexpected internal unbinding is reversible but still unsafe behavior |

This is a focused engineering/usability judgment, not a measured user study.
Frame-time performance was not benchmarked in this review and is not assigned a
score. No full application regression sweep or executable build was necessary
for this read-only behavior assessment.

## How binding currently works

`BindingService.bind` routes several operations through one command:

| Input | Current result |
| --- | --- |
| Bone to bone | Change skeletal parenting inside the same skeleton |
| Artwork to bone, Rigid off | Skin the artwork to the bone's rig |
| Artwork to bone, Rigid on | Detach its skin/pins and add a rigid parent constraint |
| Artwork to another image, shape or group | Detach its skin/pins and add a rigid parent constraint |

`SceneEditingService.attach` already supports objects/groups following another
object/group or bone with a keep-world offset. It rejects dependency cycles.
Structural Object membership is separate and is deliberately excluded from
removable binding rows. The manager also shows skin influences, area pins,
springs and other constraints in connected groups.

Main Scene can access these commands through Object/Rig menus. Its Scene tree
offers an Attach to bone submenu. The Bindings dialog's target selector is flat
and includes raw ID suffixes; Object-container groups are labelled Folder.
In Object Editor, its endpoints are scoped to that object's contents. That
scope is appropriate for definition editing but does not provide an external
Scene pickup workflow.

Object-to-object translation currently redirects a follower's drag to its driver
so the linked group moves together. This follows an existing owner choice.
A new directed attachment tool should coexist with that grouping behavior,
using an explicit offset-edit action rather than silently replacing it.

## Confirmed findings

### P1: a Scene prop does not follow placed-character translation

Reproduced with both a Creator Little character and the cached Dash template:

1. Create an independent Scene prop Object.
2. Rigid-bind its Object root to `hand.R`.
3. Move the character Object by `(100, 40)`.

The displayed hand moves by `(100, 40)`; the prop moves by `(0, 0)`. Evaluation
reports no warning. Creation preserves the initial prop transform, so the defect
can remain hidden until the character moves.

The attachment offset and parent solver use the raw bone matrix. Skinned bone
display positions also incorporate the owning Object placement, exposed through
`ScenePose.bone_placements` and `for_display`. The attachment route does not
resolve that placed target space. Internal skin/solver coordinates must remain
intact when fixing this; globally applying display placement to every bone would
conflict with the existing skinning contract.

Relevant source: `application_services/scene_editing.py:487`,
`engine/constraints.py:144`, `engine/evaluation.py:520`, `engine/state.py:82`.

### P1: binding a complete Object can remove its internal rigging

Binding a complete Creator character Object to another Scene Object through
`BindingService.bind(..., rigid=True)` changed its internal skinning deformer
count from **48 to zero**. Undo restored the original project. Calling the
existing lower-level `SceneEditingService.attach` instead retained all 48.

The general Bind route collects descendant meshes and calls
`ImageRigService.detach` before creating the root constraint. That is suitable
for intentionally rebinding individual parts; it is inappropriate for attaching
an already-rigged Object as a unit, such as a rider to a vehicle.

Relevant source: `application_services/bindings.py:137` and `:159`.

### P2: “Space switching” does not implement the requested pickup timeline

The `space_switch` solver currently aliases the same single-target parent solver.
The parent parameters contain an affine offset, but no evaluated attachment
influence or keyed target state. The animation-channel picker exposes existing
numeric constraint parameters; the target ID and enabled flag are not supplied
as attachment channels. Changing the stored target changes the setup rather
than authoring a pickup/release event at one frame.

Relevant source: `engine/constraints.py:276`,
`application_services/animation_editing.py:302`,
`presentation/widgets/rigging.py:176`.

### P2: one manager combines too many different authoring tasks

Mesh weights, bone parenting, spring anchors and external Scene attachments are
different operations with different cleanup rules. Their connected components
can encompass an entire character, making a simple prop relationship difficult
to identify. The dialog provides removal but no focused grip/offset workflow,
named attachment points or direct target picking.

## Professional reference workflows

- **Blender:** Child Of provides following relationships with keyable influence
  and inverse-offset correction. It distinguishes this from building a connected
  bone chain. This supports changing which object/bone drives a prop over time.
  [Official Child Of manual](https://docs.blender.org/manual/en/4.2/animation/constraints/relationship/child_of.html).
- **Spine:** Transform constraints can simulate changing a bone's parent for
  weapon equipment and object throwing. They offer offsets, target picking and
  keyable mixes. This is a skeleton-centric reference, not a claim that Spine
  supplies Rigora's proposed multi-object Scene system.
  [Official transform-constraint guide](https://esotericsoftware.com/spine-transform-constraints).
- **Unreal Engine:** Sockets are named, editable transforms relative to bones.
  Scene objects can attach through target picking or the hierarchy. Attachment
  operations offer keeping the current world pose or snapping to a socket, and
  runtime operations support attachment/release.
  [Official socket documentation](https://dev.epicgames.com/documentation/unreal-engine/skeletal-mesh-sockets-in-unreal-engine).

The recommendation below combines these established concepts with Rigora's
existing Object Editor, Scene instances and timeline. It is a design proposal.

## Recommended structure

Keep three explicit responsibilities, backed by the existing canonical services:

1. **Rig binding:** mesh weights, artwork-to-bone binding and bone hierarchy in
   Object Editor. Existing unbinding/physics-cleanup behavior belongs here.
2. **Attachment points (sockets):** named points such as Right Grip, Left Grip,
   Head and Back. Store them in the reusable Object definition, relative to a
   bone or object transform, with optional view-specific offsets. An axe can
   define its own Grip point. Picking arbitrary objects/bones must also work
   without requiring sockets.
3. **Scene attachments:** an independent Object instance follows another
   instance, a bone or a socket. Store a directed target reference, offset and
   inheritance options. Keep this relationship local to the Scene instance.
   Attaching a whole Object must never unbind its own meshes or springs.

Use a typed Scene attachment interface over the canonical stored relationship;
do not persist a second competing copy of the same constraint state. Reuse
matrix math, dependency validation, Undo and service access for GUI/API/plugins.

### The pickup interaction

Select the axe and choose **Attach to…**, then pick the hand or Right Grip in
the viewport. Show the resolved target as `Milo / Right hand / Grip`, with a
preview line and target highlight. Escape cancels target picking.

Offer two clear placement choices: **Keep position** and **Snap grip**. The
first preserves the evaluated world pose; the second aligns the prop's chosen
grip to the destination. Offset editing should move/rotate the prop relative
to its attachment, with an explicit separate action for moving the linked group.
Advanced options can control inherited rotation/scale/mirroring and drawing
the prop in front of or behind the hand while respecting explicit depth choices.

Distinguish a setup attachment from **Key attachment here**. Honor Auto Key and
also provide an explicit timeline command so a pickup never silently rewrites
the relationship for the whole Scene. The Attachment row uses held state keys:

| Frame | Axe attachment state |
| --- | --- |
| 0 | World / independent |
| 40 | Milo / Right Grip |
| 90 | World / independent, preserving its release pose |

Insert an initial World state when adding the first pickup later in the Scene.
Calculate switch offsets when authoring the key and store them with that state;
random/backward seeking must not depend on the previously played frame. Release
preserves the current pose; a subsequent fall/throw requires transform animation
or an explicitly enabled physics feature.

### Management

Provide an Attachment card for the selected Object: target, point, placement
mode, offset controls, key diamond, Select target and Detach. A Scene Attachments
view should show concise directed rows such as `Axe → Milo / Right Grip`, with
search, current-frame status and direct selection of either endpoint. Keep rig
skin/constraint details available in a separate advanced view.

Scene props stay separate reusable Objects. Releasing one removes only its Scene
relationship and preserves its evaluated pose; it must not remove the character's
skin, pins, springs or skeleton. Socket definitions are shared by reusable Object
assets; picking up an axe in one placed instance does not attach every copy.

For a two-handed weapon, use one primary grip to drive the weapon and have the
second hand's IK follow a second grip on the weapon. Do not create two competing
parents or a hand/weapon dependency cycle.

### Evaluation and implementation order

First fix and regression-test placed-bone target resolution and preservation of
whole-Object internals. Scene following must consume the final placed bone pose,
including relevant animation/IK/spring results. Existing attachment rules run
before spring evaluation; the final-pose dependency boundary needs deliberate
coverage rather than a blanket solver-order change.

Then implement direct Scene target picking, keep-position/snap and explicit
offset editing. Follow with named sockets and keyed attachment states. Reuse
the compiled dependency graph and indexed held-state lookup; avoid scanning all
skins, meshes or relationship UI rows during each frame. Treat two-hand IK as
an additional dependency case with cycle validation.

Acceptance should include translation, rotation, nonuniform/negative scale,
view changes, simulated targets, attach/transfer/release, reverse/random seeks,
Undo/Redo, save/reopen, duplicate/package identity remapping and representative
editing/playback timings. Unsupported engine adapters should bake evaluated
Scene transforms or explicitly report the relationship limitation.

## Evidence

Existing `test_bindings.py` and `test_bindings_gui.py`: **18 passed**. Those
tests cover internal rig/part operations and ordinary following, but did not
exercise the two whole-Scene failures reproduced here. Passing them does not
make Scene pickup correct.

Retained local evidence: `build/binding-system-review/probe.py`,
`verified-probes.json`, `scene-attachment-probe.json`, `bindings.xml` and
`tests.log`. No application source file or persistent user project was modified.
