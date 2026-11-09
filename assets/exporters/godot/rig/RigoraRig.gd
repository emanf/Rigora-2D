extends Node3D
## Native glTF rig playback with replaceable wardrobe and independently tinted parts.

signal event_fired(event: Dictionary)
@export var playing: bool = true

var definition: Dictionary
var parts: Dictionary = {}
var selections: Dictionary = {}
var colors: Dictionary = {}
var motion: AnimationPlayer
var voice: AudioStreamPlayer
var base_path: String
var textures: Dictionary = {}
var event_time: float = 0.0
var started: bool = false
var playback_seconds: float = 0.0

func _ready() -> void:
    base_path = get_script().resource_path.get_base_dir()
    var parsed = JSON.parse_string(FileAccess.get_file_as_string(base_path.path_join("rig.json")))
    if not parsed is Dictionary or parsed.get("format") != "rigora.editable-rig":
        push_error("Invalid Rigora rig definition")
        set_process(false)
        return
    definition = parsed
    for part in definition.parts:
        var node = find_child(part.node, true, false)
        if not node is MeshInstance3D:
            push_error("Missing Rigora mesh: " + part.node)
            continue
        parts[part.node] = node
        var material = node.get_active_material(0)
        if material:
            node.material_override = material.duplicate()
    for node in find_children("*", "AnimationPlayer", true, false):
        motion = node
        for animation in motion.get_animation_list():
            if animation != "RESET":
                motion.play(animation)
                motion.get_animation(animation).loop_mode = Animation.LOOP_LINEAR if definition.loop else Animation.LOOP_NONE
                motion.pause()
                break
        break
    if definition.has("audio"):
        voice = AudioStreamPlayer.new()
        add_child(voice)
        voice.stream = load(base_path.path_join(definition.audio.path))
        voice.volume_db = linear_to_db(maxf(0.0001, definition.audio.gain))
    _apply_state(0.0)

func _process(delta: float) -> void:
    if definition.is_empty():
        return
    if playing:
        var candidate: float = event_time + maxf(0, delta * (motion.speed_scale if motion else 1.0))
        var previous: float = event_time if started else -0.000001
        started = true
        var first: int = int(floor(event_time / definition.duration)) if definition.loop else 0
        var last: int = mini(first + 4096, int(floor(candidate / definition.duration))) if definition.loop else 0
        for cycle in range(first, last + 1):
            for event in definition.get("events", []):
                var at: float = event.seconds + cycle * definition.duration
                if at > previous and at <= candidate:
                    event_fired.emit(event.duplicate(true))
        event_time = candidate if definition.loop else minf(candidate, definition.duration)
    playback_seconds = fmod(event_time, definition.duration) if definition.loop else minf(event_time, definition.duration)
    if motion and playing:
        motion.seek(playback_seconds, true)
    _apply_state(playback_seconds)

func _apply_state(seconds: float) -> void:
    var frame = mini(int(seconds * definition.fps), definition.parts[0].states.size() - 1)
    var visible_parts: Dictionary = {}
    for part in definition.parts:
        visible_parts[part.node] = part.states[frame].visible
        var node = parts.get(part.node)
        if node and node.material_override is BaseMaterial3D:
            var tint: Color = colors.get(part.node, Color.WHITE)
            tint.a *= part.states[frame].opacity
            node.material_override.albedo_color = tint
            var path: String = part.texture_states[frame]
            if not textures.has(path):
                textures[path] = load(base_path.path_join(path))
            node.material_override.albedo_texture = textures[path]
    var covered: Dictionary = {}
    for group in definition.wardrobes:
        if not selections.has(group.id):
            continue
        var selected = selections[group.id]
        for variant in group.variants:
            for part in variant.parts:
                visible_parts[part] = false
            for part in variant.occludes:
                visible_parts[part] = true
        for variant in group.variants:
            if variant.id == selected:
                for part in variant.parts:
                    visible_parts[part] = true
    for group in definition.wardrobes:
        for variant in group.variants:
            if variant.id == selections.get(group.id, group.selected):
                for part in variant.occludes:
                    covered[part] = true
    for name in parts:
        parts[name].visible = visible_parts.get(name, true) and not covered.has(name)
    if voice and voice.stream:
        var time: float = seconds + definition.audio.offset
        var audible: bool = playing and not definition.audio.muted and time >= 0 and time < definition.audio.duration
        if audible:
            if not voice.playing:
                voice.play(time)
            elif absf(voice.get_playback_position() - time) > 0.12:
                voice.seek(time)
        else:
            voice.stop()

func set_clothing(group_id: String, variant_id: String = "") -> bool:
    ## Select a wardrobe variant, or an empty ID to remove that clothing category.
    for group in definition.get("wardrobes", []):
        if group.id != group_id:
            continue
        if variant_id != "" and not group.variants.any(func(v): return v.id == variant_id):
            return false
        selections[group_id] = variant_id
        _apply_state(playback_seconds)
        return true
    return false

func set_part_color(part_name: String, color: Color) -> bool:
    ## Tint one separate part without replacing another garment's color.
    if not parts.has(part_name):
        return false
    colors[part_name] = color
    return true

func seek(seconds: float) -> void:
    ## Scrub native animation and its visibility/audio to an exported time.
    playback_seconds = clampf(seconds, 0, definition.duration)
    event_time = playback_seconds
    started = true
    if motion:
        motion.seek(playback_seconds, true)
    _apply_state(playback_seconds)
