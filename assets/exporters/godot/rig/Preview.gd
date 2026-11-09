extends Node3D
## Fit an orthographic preview camera around the exported first-frame geometry.

func _ready() -> void:
    var path: String = get_script().resource_path.get_base_dir().path_join("rig.json")
    var definition = JSON.parse_string(FileAccess.get_file_as_string(path))
    if not definition is Dictionary:
        return
    var low := Vector2(INF, INF)
    var high := Vector2(-INF, -INF)
    for part in definition.get("parts", []):
        for point in part.positions:
            low = low.min(Vector2(point.x, point.y))
            high = high.max(Vector2(point.x, point.y))
    if not is_finite(low.x):
        return
    var camera := Camera3D.new()
    camera.projection = Camera3D.PROJECTION_ORTHOGONAL
    camera.keep_aspect = Camera3D.KEEP_HEIGHT
    camera.size = maxf(high.y - low.y, (high.x - low.x) * 0.75) * 1.2
    camera.position = Vector3((low.x + high.x) / 2, (low.y + high.y) / 2, 50)
    camera.far = 100
    add_child(camera)
    camera.make_current()
