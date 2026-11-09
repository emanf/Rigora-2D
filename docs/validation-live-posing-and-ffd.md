# Live posing and custom FFD follow-up

`Test_Rigora.bat --no-pause`: **218 passed, 1 existing Windows symlink skip**
in 100.80 s. Ruff lint and formatting passed (130 files); strict mypy passed
across 70 source files. The log is `build/maintenance/live-vector-ffd-final.log`.

The viewport uses transparency across its full working area, with the camera
shown as an outline. Off-camera artwork and bones remain visible and editable.
Selecting and pulling a chain evaluates the actual geometry during movement;
the root stays anchored. Move translates selected branches explicitly. Empty
area dragging selects multiple bones, and Ctrl extends selection.

Custom FFD supports circular controls, marquee selection, group translation and
eight resize handles. Each gesture previews without changing the document and
commits one undo item. Escape, mode changes and document changes cancel previews.

SVG deformation renders the original vector primitives through the mesh's affine
patches. Thumbnails are only used for import validation and source browsing.
Hard pixel-region coverage avoids translucent seams between patches. Compatible
patches share a render when their mappings differ by at most one quarter device
pixel. This preserves vector detail while reducing redundant SVG traversal.

Native Windows checks cover anchored live posing, cancellation, commit/undo,
off-camera manipulation, FFD marquee selection and group resizing. Captures are
in ignored `build/ui-preview/live-vector-ffd-711887a2a6874f7cbfafff41c7a41d85/`.
The example's six deformation updates with synchronous captures averaged about
50 ms on this host; this CPU vector path does not promise 60 fps for complex art.
The chain solver is geometric posing; gravity, inertia and collision simulation
are outside this increment. SVG paths are not rewritten or exported as warped
path data; the viewport retains vector rendering at every zoom.
