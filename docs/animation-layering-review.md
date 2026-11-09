# Animation and FFD layering review

Reviewed 2026-11-06. This is a source inspection, a local offscreen reproduction,
and a survey of official documentation for thirteen established animation tools
and engine editors. It is not a hands-on benchmark or market ranking of those
products. The proposed behavior below is not implemented by this review.

## Finding

Layering deformation can be useful: breathing and a short squash can act together.
Drawing two independent actions directly over one another in a single timeline
row makes that capability difficult to understand and edit.

The local reproduction applies **Soft breathing** and **Squash and stretch** to
one promoted ellipse Object at frame zero. Both source clips remain present,
both Scene placements span frames 0–38, and two distinct FFD stages remain on the
mesh. Both labels are drawn at the same vertical position. Muting one placement
changes evaluated mesh positions at frame 12; Undo restores the combination.
Thus the observed overlap does not mean the second clip replaced the first.

Relevant code:

- `application_services/ffd_motion.py::FfdMotionService.apply_item` creates a new
  stage and, in Scene, a named source action for each applied preset.
- `application_services/characters.py::CharacterService.place_motion` retains a
  distinct placement ID, source, start/end, speed and loop settings.
- `presentation/widgets/timeline.py::Timeline.refresh` groups motion windows by
  Object and the generic Animation lane; it does not assign separate visible rows
  for overlapping placements or distinguish FFD motion from skeletal motion.
- `presentation/widgets/key_canvas.py::KeyCanvas.draw_motions` assigns every
  placement in that lane the same vertical center.
- `engine/deformation.py::DeformationEvaluator` evaluates mesh stages in their
  explicit deformation order. This geometric composition is separate from motion
  priority when multiple clips drive the same parameter.

The existing engine already supports action order, override/additive blending,
weight, fades, mute, solo and masks. `SceneActionEditor` exposes these in the
action dialog. `SceneEvaluator.mesh_values` also applies weighted sampling to
deformation parameters. These capabilities should be preserved and surfaced,
rather than replaced with a second animation engine.

An important limitation: two presets currently create different stage IDs.
Choosing Override on the second placement does not automatically replace the
first stage, since their channels have different owners. Also, the dialog's body
mask lists Objects, Groups and Bones; deformation-owner mapping needs explicit
handling before presenting this as a complete FFD mask workflow.

## Documentation comparison

| Tool | Documented pattern relevant to Rigora |
| --- | --- |
| [Blender NLA](https://docs.blender.org/manual/en/latest/editors/nla/strips.html) | Reusable actions are referenced by timed strips; transition strips connect neighboring actions. |
| [Maya Time Editor](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-Animation/files/GUID-B3FFE1AA-F44D-4EC3-A570-316A3BF3DF88.htm) | Clip layers have explicit additive/override modes and weights. |
| [3ds Max Motion Mixer](https://help.autodesk.com/cloudhelp/2024/ENU/3DSMax-Animation/files/GUID-5579D04E-A731-4431-B608-4A09B7B09696.htm) | Each object's mix contains tracks, clips and transitions; trackgroup filters restrict affected parts. |
| [MotionBuilder Story](https://help.autodesk.com/cloudhelp/2019/ENU/MotionBuilder/files/GUID-4626C953-DD99-431B-9DFB-F7DAE7CAAD0C.htm) | Horizontal clip blending is distinct from vertical track priority and additive/override behavior. |
| [Cinema 4D Motion Layers](https://help.maxon.net/c4d/2024/en-us/Content/html/MT_LAYER.html) | Reusable Motion Sources are placed as clips on separate layers; direct animation layers remain distinct. |
| [Houdini Motion Mixer](https://www.sidefx.com/docs/houdini/ref/panes/motionmixer.html) | Visible tracks, weights and separate effect rows expose mute, solo, masks and blend modes. Its documentation explicitly marks this feature as under development. |
| [Toon Boom Harmony](https://docs.toonboom.com/help/harmony-25/premium/reference/node/deformation/deformation-composite-node.html) | A named deformation composite exposes enable state and explicit selection of deformation chains. This is a deformation-graph reference, not an assertion that Harmony uses NLA strips for everything. |
| [Spine](https://esotericsoftware.com/spine-applying-animations) | Runtime AnimationState separates queuing, crossfading and numbered layering tracks. This comparison concerns its runtime API, not a claimed NLA layout in the Spine editor. |
| [Rive](https://rive.app/docs/editor/state-machine/layers) | A state-machine layer plays one state; multiple layers support concurrent animation, with documented property priority. |
| [Adobe Character Animator](https://helpx.adobe.com/adobe-character-animator/desktop/recording-and-playback/refining-a-recorded-performance.html) | Parameter takes have separate bars, explicit blend handles and a visible precedence rule for overlapping takes. |
| [After Effects](https://helpx.adobe.com/after-effects/desktop/apply-effects-and-animation-presets/effects-and-animation-presets/effects-animation-presets-overview.html) | Effects have a named, reorderable processing stack. Effect order is distinct from layer compositing order. |
| [Unity Timeline](https://docs.unity3d.com/2019.2/Documentation/Manual/TimelineBlendingClips.html) | In Mix mode, overlapping compatible clips produce a visible blend region with incoming/outgoing curves. This linked manual documents a legacy version of the workflow. |
| [Unreal Sequencer](https://dev.epicgames.com/documentation/unreal-engine/cinematic-animation-track-in-unreal-engine) | Adding animation over an occupied time creates another track layer; sections expose weights, blend handles and independent active/locked states. |

These tools do not share one universal stack direction or mixing rule. The common
lesson is to show which clips exist, which properties they affect, and how they
combine. Rigora should adopt those distinctions with a simpler 2D presentation.

## Recommended user-facing structure

Keep flat sibling rows under the Object, preserving the existing preference
against deeply nested timeline trees:

```text
Milo
  Transform          o-------------------o
  Animation          [Walk 1×] [Run 1.2×]
  FFD · Breathing    [Soft breathing · loop--------------]
  FFD · Impact                        [Squash----]
  Skin               palette key
  Clothing           shirt key
```

1. An Object's Animation lane is for its primary reusable character actions.
   FFD motions have named deformation lanes. Names reflect the preset and target
   part when relevant, with deterministic suffixes for duplicates.
2. A Scene drop occurs at the playhead. An FFD drop creates its own visible lane
   and selects the new placement; existing motions stay available. The drag ghost
   says which target, time and layer will receive the effect. This preserves
   timing intent while exposing the composition instead of concealing it.
3. A timeline drop uses its target row and snapped time. Non-overlapping clips
   can share a lane. Overlapping independent effects receive separate rows.
   A collapsed summary can show a count, but cannot paint several editable labels
   directly on top of each other.
4. Offer clear **Play after previous**, **Layer with existing**, and **Replace
   selected clip** commands. Replacement targets a specific placement and is one
   undoable operation. No ordinary drop silently destroys another source.
5. Selection exposes target, start/end, speed, loop, strength, fades, mute and solo
   in a compact editor. Keep advanced blend mode, masks and operation order
   available without making a beginner configure them for the first drop.
6. Show crossfade regions only when there is a real compatible blend. Different
   FFD grids/controllers must not be advertised as blendable merely because their
   clips overlap. Mute disables evaluation; Lock prevents edits independently.

## Recommended implementation boundaries

- Retain canonical source actions and the shared application services. Add a
  stable lane/controller identity and explicit motion kind to placement metadata;
  do not use a row number or displayed label as persistent identity.
- Distinguish **source clip**, **timed placement**, **visible lane**, and
  **deformation stage**. Moving a placement changes its time. Reordering a lane's
  presentation need not change geometric stage order unless that is the explicit
  operation the user chooses.
- Same-controller motion blending mixes compatible control values in one rest
  space. Separate-controller FFD composition runs named deformation stages in a
  documented order. A nominal Override on an unrelated stage cannot mean global
  replacement. Different lattice resolutions need a validated remapping before
  any direct control-value blend.
- Map part masks through ownership to affected meshes and stages. Keep influence
  masks distinct from the choice of which source properties a clip keys.
- Outside an effect placement's interval, define neutral/bypass behavior explicitly.
  Static FFD shapes remain a separate authored feature; disabling a motion must
  not accidentally leave a persistent animated deformation or erase a static one.
- Preserve current saved projects without retiming or rebaking them. Migrate only
  lane metadata where it can be derived safely; old simultaneous effects should
  remain simultaneous and simply become visible on separate rows.
- Cache lane packing when placements/timing change. Playback should update time
  and active influences, not reconstruct source keys, card images or hierarchy
  widgets. Virtualize offscreen lanes if large compositions require it.

## Score and acceptance bar

**Current FFD placement workflow: 5.8/10**, using five equally weighted criteria:

| Criterion | Score / 10 | Evidence |
| --- | ---: | --- |
| Source preservation and reversibility | 9 | Separate sources/stages/placements survive both drops; Undo and independent mute work. |
| Timing and reusable action structure | 7 | Source timing, speed and repeat are explicit; loop/frame alignment has focused tests. |
| Mixing foundation | 7 | Weighted sampling and ordered stages exist, but unrelated FFD controllers and body masks need clearer semantics. |
| Visibility and selection of overlapping actions | 2 | Both labels occupy exactly the same vertical center in the reproduction. |
| Discoverability and predictable defaults | 4 | Advanced controls exist in a dialog, but the generic lane hides the distinction between sequence, layer and deformation order. |

This score covers the reviewed workflow, not the whole application. No animation
performance score is assigned from this reproduction.

The proposed workflow's acceptance target is at least **9/10**, measured after
implementation rather than granted to a design. Required validation includes two
and ten simultaneous FFDs, same/different grids, masked parts, sequence/crossfade
boundaries, independent mute/solo/lock, retiming, source editing, Undo/Redo,
save/reopen, linked Objects, exports, high-DPI selection, and measured playback
costs at representative mesh and lane counts.
