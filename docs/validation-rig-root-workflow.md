# Rig Root workflow validation

Validated on 2026-11-03 against the source application. Desktop bundles were not rebuilt.

The 2026-11-04 follow-up adds early empty-rig controls, mode-specific root movement
and the unified Object Tree. See [current validation](validation-unified-object-editor.md).

## Hierarchy and behavior

Each nonempty skeleton has one zero-length **Rig Root** above its independent
deforming chains. It is a selectable master control in Object Tree and a
circle/crosshair in the viewport. FK/Rig transforms carry descendants, including
locally locked children, without rewriting child poses. Bone-mode transforms
reposition the master and compensate direct children to preserve chain world poses.
It remains kinematic and is excluded from automatic skin weights. It cannot be
reparented, lengthened, duplicated alone or deleted independently of its Object.

The first deforming segment can spring around its anchored base. IK stops below
the master and keeps the deforming chain base anchored. Draw new chains directly
in the viewport; there is no separate drawing-origin marker or hit target.

New rigs receive a master automatically. Entering Object Editor upgrades a
nonempty legacy skeleton in one undoable operation. Its identity transform
preserves existing bone IDs, rest matrices, keys and bind data. Empty skeletons
receive a selectable master as soon as Add Bone is activated, before drawing.

Object Editor uses local coordinates and frames its own geometry. It does not
draw the Scene camera rectangle. The Fit command frames local content. Scene
placement is removed before storing local bone edits, preventing doubled owner
translation. Clip offsets target the master once and preserve authored curves.

## Evidence

Baseline result: **130 tests passed** in the affected regression suite. Ruff lint and
format checks passed for all 487 Python files; mypy passed for 268 source files.

The affected regression suite covers root insertion and save/load, one-step
Undo, real tree selection and pointer dragging, movement in Bone/FK modes,
master rotation and scale, locked-child inheritance, first-segment physics and
baking, all 20 flexible-chain presets during Scene dragging and settling, skin
movement, linked source actions, IK, retiming, deformation, motion recording and
editable Unity/Godot/Unreal export geometry.

Run with the development interpreter and `QT_QPA_PLATFORM=offscreen`:

```text
python -m pytest tests/test_rig_root_workflow.py tests/test_rig_root_workflow_gui.py tests/test_template_spring_drag_gui.py tests/test_rigging.py tests/test_dynamics.py tests/test_object_root_springs.py tests/test_spring_activation.py tests/test_image_rigging_and_soft_drag.py tests/test_animation_editing.py tests/test_bone_animation.py tests/test_deformation_services.py tests/test_editable_rig_export.py tests/test_motion_pilot.py tests/test_engine.py -q
python -m ruff check src tests
python -m ruff format --check src tests
python -m mypy src
```

The offscreen screenshot is generated locally at
`build/bone-structure-audit/rig-root-editor.png`; it is not a runtime asset.

## Review

Score: **9/10**. Criteria: hierarchy/ownership correctness, predictable transforms,
spring/IK separation, reversible legacy upgrade, animation/export compatibility
and editor clarity. Automated tests and the offscreen visual inspection cover
the changed behavior. Native desktop pointer interaction and target-engine
runtime import have not been manually exercised in this validation.
