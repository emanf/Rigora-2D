extends Node2D
## Pixel-space editable bones, vector mesh skinning and deterministic scene playback.

signal event_fired(event: Dictionary)
@export var playing: bool = true
@export var use_scene_camera: bool = true
@export_storage var use_authored_nodes: bool = false
var definition: Dictionary = {}
var bones: Array[Node2D] = []
var parts: Dictionary = {}
var selections: Dictionary = {}
var colors: Dictionary = {}
var textures: Dictionary = {}
var time: float = 0.0
var frame: int = 0
var base_path: String
var skeleton: Skeleton2D
var scene_layer: CanvasLayer
var backdrop: Sprite2D
var lens: Sprite2D
var particle_nodes: Array[Polygon2D] = []
var voice: AudioStreamPlayer
var started: bool = false

func _ready() -> void:
    base_path = get_script().resource_path.get_base_dir()
    var parsed = JSON.parse_string(FileAccess.get_file_as_string(base_path.path_join("rig.json")))
    if not parsed is Dictionary or parsed.get("format") != "rigora.editable-rig":
        push_error("Invalid Rigora rig definition")
        set_process(false)
        return
    definition = parsed
    if use_authored_nodes:
        scene_layer = get_node("SceneCamera")
        skeleton = get_node("SceneCamera/Armature")
        backdrop = get_node("SceneCamera/Background")
        lens = get_node("SceneCamera/Lens")
    else:
        scene_layer = CanvasLayer.new()
        add_child(scene_layer)
        skeleton = Skeleton2D.new()
        scene_layer.add_child(skeleton)
        backdrop = Sprite2D.new()
        backdrop.centered = false
        backdrop.z_index = -4096
        scene_layer.add_child(backdrop)
        lens = Sprite2D.new()
        lens.centered = false
        lens.z_index = 4096
        scene_layer.add_child(lens)
    for node in definition.nodes:
        var bone: Node2D = skeleton.find_child(node.name, true, false) if use_authored_nodes else (Bone2D.new() if node.kind == "bone" else Node2D.new())
        if not bone:
            push_error("Missing authored Rigora node: " + node.name)
            set_process(false)
            return
        bone.name = node.name
        if bone is Bone2D:
            bone.set_autocalculate_length_and_angle(false)
            if not use_authored_nodes:
                bone.length = 30.0
        bones.append(bone)
    for i in bones.size():
        var parent: int = int(definition.nodes[i].parent)
        if not use_authored_nodes:
            (bones[parent] if parent >= 0 else skeleton).add_child(bones[i])
    for part in definition.parts:
        var polygon: Polygon2D = skeleton.get_node(part.node) if use_authored_nodes else Polygon2D.new()
        polygon.name = part.node
        var faces: Array[PackedInt32Array] = []
        for i in range(0, part.triangles.size(), 3):
            faces.append(PackedInt32Array(part.triangles.slice(i, i + 3)))
        polygon.polygons = faces
        if not use_authored_nodes:
            skeleton.add_child(polygon)
        parts[part.node] = polygon
    if definition.has("audio"):
        voice = AudioStreamPlayer.new()
        add_child(voice)
        voice.stream = load(base_path.path_join(definition.audio.path))
    if use_authored_nodes and not playing:
        refresh_pose()
    else:
        seek(0.0)
    started = false
    for bone in bones:
        if bone is Bone2D and not use_authored_nodes:
            bone.rest = bone.transform

func _process(delta: float) -> void:
    if definition.is_empty() or not playing:
        return
    var previous: float = time
    var candidate: float = time + delta
    if not started:
        previous = -0.000001
        started = true
    _emit_interval(previous, candidate)
    time = fmod(candidate, definition.duration) if definition.loop else minf(candidate, definition.duration)
    _apply_frame()

func _emit_interval(previous: float, candidate: float) -> void:
    var duration: float = definition.duration
    var last: int = mini(4096, int(floor(candidate / duration))) if definition.loop else 0
    for cycle in range(last + 1):
        for event in definition.get("events", []):
            var at: float = float(event.seconds) + cycle * duration
            if at > previous and at <= candidate:
                event_fired.emit(event.duplicate(true))

func seek(seconds: float) -> void:
    ## Scrubbing is deterministic and never dispatches gameplay events.
    if definition.is_empty():
        return
    time = clampf(seconds, 0, definition.duration)
    started = true
    _apply_frame()

func _sample_transform(sample: Dictionary) -> Transform2D:
    var angle: float = -2.0 * atan2(sample.rotation[2], sample.rotation[3])
    return Transform2D(angle, Vector2(sample.scale[0], sample.scale[1]), 0.0,
        Vector2(sample.translation[0] * 100, -sample.translation[1] * 100))

func _matrix(values: Array) -> Transform2D:
    return Transform2D(Vector2(values[0], values[1]), Vector2(values[2], values[3]), Vector2(values[4], values[5]))

func _bind(values: Array) -> Transform2D:
    return Transform2D(Vector2(values[0], -values[1]), Vector2(-values[4], values[5]), Vector2(values[12] * 100, -values[13] * 100))

func _texture(path: String) -> Texture2D:
    if path.is_empty():
        return null
    if not textures.has(path):
        textures[path] = load(base_path.path_join(path))
    return textures[path]

func _apply_frame() -> void:
    frame = clampi(int(time * definition.fps), 0, definition.parts[0].states.size() - 1)
    for i in bones.size():
        bones[i].transform = _sample_transform(definition.nodes[i].samples[frame])
    refresh_pose()

func refresh_pose() -> void:
    ## Re-skin against editable native bones without resetting their transforms.
    if definition.is_empty():
        return
    var visible_parts: Dictionary = {}
    for part in definition.parts:
        visible_parts[part.node] = part.states[frame].visible
    for group in definition.wardrobes:
        if not selections.has(group.id):
            continue
        for variant in group.variants:
            for part in variant.parts:
                visible_parts[part] = false
            for part in variant.occludes:
                visible_parts[part] = true
        for variant in group.variants:
            if variant.id == selections[group.id]:
                for part in variant.parts:
                    visible_parts[part] = true
    var covered: Dictionary = {}
    for group in definition.wardrobes:
        for variant in group.variants:
            if variant.id == selections.get(group.id, group.selected):
                for part in variant.occludes:
                    covered[part] = true
    var sample: Dictionary = definition.scene_samples[frame]
    for part in definition.parts:
        var polygon: Polygon2D = parts[part.node]
        polygon.visible = visible_parts[part.node] and not covered.has(part.node)
        polygon.z_index = sample.render_order.find(part.object_id)
        var tint: Color = colors.get(part.node, Color.WHITE)
        tint.a *= part.states[frame].opacity
        polygon.color = tint
        polygon.texture = _texture(part.texture_states[frame])
        var points := PackedVector2Array()
        var uv := PackedVector2Array()
        var matrices: Array[Transform2D] = []
        for j in part.joints.size():
            matrices.append(skeleton.global_transform.affine_inverse() * bones[int(part.joints[j])].global_transform * _bind(part.bindposes[j].values))
        for i in part.positions.size():
            var point := Vector2(part.positions[i].x * 100, -part.positions[i].y * 100)
            if not part.corrections.is_empty():
                var correction: Dictionary = part.corrections[frame].vertices[i]
                point += Vector2(correction.x * 100, -correction.y * 100)
            var deformed := Vector2.ZERO
            for j in 4:
                var weight: float = part.weights[i].values[j]
                if weight > 0:
                    deformed += (matrices[int(part.weights[i].indices[j])] * point) * weight
            points.append(deformed)
            uv.append(Vector2(part.uv[i].x, part.uv[i].y) * polygon.texture.get_size())
        polygon.polygon = points
        polygon.uv = uv
    _particles(sample)
    _camera(sample)
    if voice and voice.stream:
        var source_time: float = time + definition.audio.offset
        var audible: bool = playing and not definition.audio.muted and source_time >= 0 and source_time < definition.audio.duration
        voice.volume_db = linear_to_db(maxf(0.0001, definition.audio.gain))
        if audible:
            if not voice.playing:
                voice.play(source_time)
            elif absf(voice.get_playback_position() - source_time) > 0.12:
                voice.seek(source_time)
        else:
            voice.stop()

func _particles(sample: Dictionary) -> void:
    while particle_nodes.size() < sample.particles.size():
        var polygon := Polygon2D.new()
        skeleton.add_child(polygon)
        particle_nodes.append(polygon)
    for i in particle_nodes.size():
        var polygon: Polygon2D = particle_nodes[i]
        polygon.visible = i < sample.particles.size()
        if not polygon.visible:
            continue
        var particle: Dictionary = sample.particles[i]
        var points := PackedVector2Array()
        var count: int = 32 if particle.shape == "circle" else 4
        for p in count:
            var angle: float = p * TAU / count
            points.append(Vector2(cos(angle), sin(angle)) if count == 32 else [Vector2(-1,-1), Vector2(1,-1), Vector2(1,1), Vector2(-1,1)][p])
        polygon.polygon = points
        polygon.transform = _matrix(particle.matrix)
        var tint := Color(particle.color)
        tint.a *= particle.opacity
        polygon.color = tint
        polygon.z_index = sample.render_order.find(particle.owner)

func _camera(sample: Dictionary) -> void:
    backdrop.visible = false
    lens.visible = false
    if not use_scene_camera:
        # A character placed in a game must share its parent's canvas/Camera2D.
        if skeleton.get_parent() != self:
            skeleton.reparent(self, false)
        return
    if skeleton.get_parent() != scene_layer:
        skeleton.reparent(scene_layer, false)
    var camera: Dictionary = sample.camera if sample.camera != null else {
        "matrix": [1, 0, 0, 1, 0, 0], "width": definition.canvas.width,
        "height": definition.canvas.height, "background": "", "lens": ""}
    var size := Vector2(camera.width, camera.height)
    var viewport_size: Vector2 = get_viewport_rect().size
    var factor: float = minf(viewport_size.x / size.x, viewport_size.y / size.y)
    var offset: Vector2 = (viewport_size - size * factor) / 2.0
    var projection := Transform2D(0, Vector2.ONE * factor, 0, offset) * _matrix(camera.matrix).affine_inverse()
    scene_layer.transform = projection * global_transform
    for pair in [[backdrop, camera.background], [lens, camera.lens]]:
        var control: Sprite2D = pair[0]
        control.texture = _texture(pair[1])
        control.visible = control.texture != null
        # Cancel the layer's camera transform for screen-space images.
        if control.texture:
            control.transform = scene_layer.transform.affine_inverse() * Transform2D(0, size * factor / control.texture.get_size(), 0, offset)

func set_clothing(group_id: String, variant_id: String = "") -> bool:
    for group in definition.get("wardrobes", []):
        if group.id != group_id:
            continue
        if variant_id != "" and not group.variants.any(func(v): return v.id == variant_id):
            return false
        selections[group_id] = variant_id
        refresh_pose()
        return true
    return false

func set_part_color(part_name: String, color: Color) -> bool:
    if not parts.has(part_name):
        return false
    colors[part_name] = color
    refresh_pose()
    return true

func get_regions() -> Array:
    ## Regions are sampled source-pixel polygons; game code owns collision policy.
    var samples: Array = definition.get("regions", [])
    return samples[frame].regions.duplicate(true) if not samples.is_empty() else []
