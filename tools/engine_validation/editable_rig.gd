extends SceneTree
## Check native skeleton animation, mesh parts, wardrobe removal and per-part color.

func _initialize() -> void:
    call_deferred("validate")

func validate() -> void:
    var packed = load("res://rig.tscn")
    assert(packed != null)
    var rig = packed.instantiate()
    root.add_child(rig)
    assert(rig.parts.size() > 20)
    var skeletons = rig.find_children("*", "Skeleton3D", true, false)
    assert(skeletons.size() > 0)
    var bone_count = 0
    for skeleton in skeletons:
        bone_count += skeleton.get_bone_count()
    assert(bone_count >= 15)
    assert(rig.motion != null)
    rig.seek(0.0)
    var before: Array = []
    for skeleton in skeletons:
        for bone in range(skeleton.get_bone_count()):
            before.append(skeleton.get_bone_pose(bone))
    rig.seek(1.0 / 24.0)
    var changed = 0
    var index = 0
    for skeleton in skeletons:
        for bone in range(skeleton.get_bone_count()):
            if not skeleton.get_bone_pose(bone).is_equal_approx(before[index]):
                changed += 1
            index += 1
    assert(changed > 0)
    var group = rig.definition.wardrobes[0]
    assert(rig.set_clothing(group.id, ""))
    for variant in group.variants:
        for part in variant.parts:
            assert(not rig.parts[part].visible)
    var part_name = rig.definition.parts[0].node
    assert(rig.set_part_color(part_name, Color.RED))
    rig.seek(0.0)
    assert(rig.parts[part_name].material_override.albedo_color.r > 0.99)
    assert(rig.parts[part_name].material_override.albedo_color.g < 0.01)
    print("RIGORA_EDITABLE_GODOT_VALIDATED: native bones, meshes, animation, clothing, independent color")
    var preview = load("res://preview.tscn").instantiate()
    root.add_child(preview)
    assert(root.get_camera_3d() != null)
    assert(root.get_camera_3d().size > 0)
    print("RIGORA_EDITABLE_PREVIEW_VALIDATED: fitted orthographic camera")
    preview.queue_free()
    rig.queue_free()
    quit(0)
