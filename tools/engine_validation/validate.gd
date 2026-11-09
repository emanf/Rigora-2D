extends SceneTree

func _initialize():
    var packed = load("res://animation.tscn")
    assert(packed != null)
    var sprite = packed.instantiate()
    var frames = sprite.sprite_frames
    var animation = frames.get_animation_names()[0]
    assert(frames.get_frame_count(animation) == 3)
    assert(frames.get_animation_speed(animation) == 12)
    assert(frames.get_animation_loop(animation))
    assert(frames.get_frame_texture(animation, 1).region == Rect2(64, 0, 64, 64))
    assert(frames.get_frame_texture(animation, 2).region == Rect2(0, 64, 64, 64))
    print("RIGORA_GODOT_VALIDATED: 3 frames, 12 FPS, ordered atlas regions, loop, native scene")
    sprite.free()
    quit(0)
