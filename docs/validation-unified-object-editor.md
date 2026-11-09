# Unified Object Editor validation

Validated on 2026-11-04 using the source application and offscreen Qt. No desktop
bundle was compiled, and no native window was brought into focus.

## Workspace

Object Tree replaces the duplicate Parts/Bones pages. Artwork, folders, Skeleton
and Rig Root share one hierarchy, which remains visible on Skin, Clothing and
Animations. Switching tasks preserves tree expansion and selection. The divider
resizes the tree and detail area. Assets opens the shared library without leaving
the edited Object or changing the document.

Compact actions above the tree provide Assets, Add Bone, folder, remove, bind and
unbind. Binding options, material/shape controls and saved skins use disclosures.
Empty saved-look grids and empty color palettes do not reserve blank card areas.
Palette editing, saved looks/defaults, clothing variations, animation creation,
duplication/removal, preview, key editing, speed and timeline placement remain
available. Shared Material icons recolor when the theme changes.

## Root controls

Add Bone prepares an owned Skeleton and selectable Rig Root before the first
deforming segment. The root is centered on artwork, or starts at an empty Object's
origin. Fresh and converted images reuse this skeleton when their first bone is
drawn; drawing preserves the actual Object owner and its placement basis.

Bone mode repositions, rotates or scales Rig Root while compensating its direct
children to retain deforming-chain world poses. FK/Rig modes carry the skeleton.
Root controls stay out of automatic skin weights and spring simulation. The first
deforming segment may spring. Independent root and Skeleton deletion are blocked
inside Object Editor; deleting the whole Object or a containing Scene folder still
removes the complete owned rig, and Undo restores it.

The drawing-origin viewport controller, marker, hit testing, snapping descriptors,
cursor handling and gesture filter were removed. Existing internal origin metadata
remains readable for project compatibility; it is not an invisible mouse target.

## Verification and limits

**174 tests passed, 2 deselected** in the final affected suite. Coverage includes
real pointer drags, early root visibility, first-bone image binding, independent
root transforms, protected/whole-object deletion, tree state across all four tasks,
skin/clothing/action controls, all 20 flexible-chain presets, skinning, IK, retiming,
motion recording, save/load and editable Unity/Godot/Unreal export geometry.

The focused GUI run substitutes an empty initial `ContentLibrary.entries` result
to isolate unrelated full-catalog discovery. Document services, imported assets,
artwork decoding, widget signals, geometry and pointer routing remain real.
Two legacy tests requiring the old catalog browser/art pack were deselected:
`test_template_bones_follow_overlay_toggle_in_main_scene` and
`test_real_character_all_four_tasks_are_renderable`. This run does not validate
full-catalog startup. One existing deprecated Qt drag-event constructor warning
remains in a test; no application warning or test failure was suppressed.

Ruff lint and formatting passed for 487 Python files. Mypy passed for 267 source
files. Dark/light captures of Object Tree, Skin, Clothing and Animations were
visually inspected; local evidence and the focused discovery-isolation plugin are
retained in `build/object-editor-validation/`. Disposable test directories were
removed after verification. Native desktop interactions and target-engine runtime
imports were not manually exercised.

## Review

**9/10** for hierarchy and ownership correctness, mode consistency, retained editing
controls, state preservation, theme clarity and regression coverage. Remaining
validation limits are full-catalog startup, native desktop interaction and runtime
import in external engines.
