# Cameras

New projects and newly added scenes start with a locked **Main Camera**. Select it
in the Scene panel and click its lock icon to enable viewport editing. Additional
cameras start unlocked. Saved cameras retain their existing lock state; projects
without cameras keep their original canvas view until a camera is added.

- Open the camera icon beside the Scene filter to **Add camera**. Each camera is
  a separate selectable Scene row. Double-click its row or frame for settings;
  F2 renames it. The eye hides its editing outline and the lock protects editing.
  Locked entries remain selectable in the Scene panel. The viewport ignores them
  for hover, selection and transforms, allowing pointers to reach editable artwork
  underneath. Locking the Main Camera leaves its output border visible.
- Select a frame to move it or use the standard rotation and scale handles.
  The property strip reads **X, Y, Z**, followed by size/rotation. Z controls artwork
  drawing priority and is disabled for cameras. Scaling a camera frame larger
  zooms out; making it smaller zooms in. Camera scale must remain nonzero.
- **Key camera transform** creates a combined Transform timeline row. Turn on
  **Auto key**, seek, and edit the selected camera to animate movement, rotation
  and scale with the normal timeline controls. **Add tracks** also lists cameras.
- **Switch camera at playhead** records exclusive stepped Active Camera keys for
  every camera together. Use that menu to make cuts. **Set as default camera**
  changes the starting view; existing camera-cut keys retain precedence.
  Cuts can activate or deactivate locked cameras because they select scene output.
  Camera transform locks and explicit timeline track locks still apply.
- **Camera preview** opens one live output window. It uses evaluated camera
  transforms, cuts, and original vector artwork while the main workspace remains
  editable outside camera frames. Inactive scenes are still not evaluated.

The active output camera at the playhead has a solid white, two-pixel frame and
an **Active** label. Other camera frames and their labels use 28% opacity. The
white frame follows timeline cuts immediately during scrubbing and playback;
it is drawn last so overlapping frames cannot cover it. Selecting an inactive
camera keeps its editing handles dimmed and does not change the output camera.
Playback and scrubbing preserve the current editing selection and document data.

Settings offer scene-matched or custom frame dimensions, transparent/solid/image
backgrounds, hexadecimal color with optional alpha (`#RRGGBBAA`), background
opacity, packaged image import, existing project image selection, and Cover/Fit/
Stretch modes. Color remains behind an image so Fit can have an intentional
letterbox color. Transparent is the default. Apply commits one undoable change;
Cancel does not import an image or change the camera.

Camera projection and backgrounds are used by SVG frame export and the raster/
video output pipeline. Export resolution remains an output setting; differing
camera/output aspect ratios retain the frame aspect ratio. Camera outlines and
editing handles are not exported. Cameras and their animation are preserved in
`.rigora` documents, scene duplication, and ordinary Undo/Redo. Native engine
planar rig adapters retain camera metadata without driving camera components.
The native Godot 2D package plays evaluated cameras and lens/background layers;
preflight directs unsupported editable adapters to this route or baked output.

Deleting a camera removes its channels. If the active camera is deleted or
disabled, the first remaining enabled camera is used. With no enabled cameras,
the original scene-canvas view is used. Cameras remain outside reusable Object
artwork definitions, skin/bone data and template-generated character fragments.

The Qt-free `rigora.api.RigoraAPI` also exposes `camera_list`, `camera_create`,
`camera_edit`, `camera_activate` (optional `frame` for a cut), and `camera_delete`.
The CLI and MCP adapters discover the same operations. Camera transform keys use
existing `keyframe_set` paths such as `transform.x`, `transform.rotation` and
`transform.scale_x`; `camera.active` is the stepped cut channel.

The dope sheet groups every camera under one **Camera** header: Transform, Cut,
Animation and Effect. Camera-icon cut keys choose the main camera. Motion and
lens-effect preset cards support editable intervals, speed and strength. See
[Object views and camera actions](object-views-and-camera-actions.md) for the
14 motion presets, 15 lens presets, editing gestures and rendering behavior.

**Animation → Camera shots** adds ordered shot cards with background thumbnails,
editable blend duration/easing and target-follow offsets. Thirds/safe guides stay
inside the active camera border and never render. Shot transitions appear as
ordinary progress channels; removing a shot retains other camera motion/effects.
For draggable camera/Object paths, use **Animation → Bezier artwork & motion
paths**. See [production workflows](production-workflows.md) for steps and bounds.
