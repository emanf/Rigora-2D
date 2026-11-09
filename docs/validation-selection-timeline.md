# Selection properties and timeline validation

The combined regression run passed **112 tests** across animation editing,
channel discovery, real Qt timeline/curve gestures, bone animation, unified
selection tools and shape/pivot workflows. The final layout run passed seven
checks, including a new narrow-window case, for **113 distinct passing tests**
across the runs. Reports:

- `build/selection-timeline-regression.xml`
- `build/selection-timeline-layout.xml`

The new checks cover live property values, proportional and independent sizing,
parent-space pivot positioning, flip/visibility/reset, one-step Undo, animated
visibility holds, animated transform edits, grouped Transform keys, inert owner
headers, frame shading, hover key slots, click/right-click seeking, zoom anchors,
whole-track cut/copy/paste/Delete, empty tracks, retained blend/editor settings,
lock/collision validation and reachable toolbar controls in smaller windows.
Existing IK/draft-bone and attachment checks also exercise stale selection
handling while preview records differ from the saved scene.

Final tests used `QT_QPA_PLATFORM=offscreen` so their Qt windows never appear on
the desktop or take keyboard focus. The content-poster isolation plugin omits
only the unrelated library-thumbnail decoder; actual scene artwork, SVG decoding,
widgets and mouse/key routing remain enabled. Offscreen Windows text rendering
can differ from the native desktop platform; these checks verify geometry,
widget values and interactions, not cross-platform font fidelity.

Example automated invocation in PowerShell:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = (Get-Location).Path + '\build'
.venv/Scripts/python.exe -m pytest -p gesture_validation_plugin tests/test_selection_properties.py tests/test_selection_timeline_gui.py -q
```

Ruff lint and formatting pass over 229 Python files. Mypy passes over all 144
source modules. No dependency, project-format or scalar animation-channel schema
changes were required. The live property strip caches immutable local mesh
extents and does not render textures or create project history while refreshing.

## Transform and layout follow-up

The shared scene-editing service now records move/rotate/scale and compensated
pivot edits into an existing animated Transform lane with Auto key off. Empty
lanes remain static until keyed. New checks exercise actual canvas gestures,
retained earlier poses, one-step Undo, all eight side-grip lock states, every
pivot reference, Alt transitions and re-grabbing a pivot at a resize corner.
The main caption retains its logo without the RIGORA text; numeric property
groups have explicit gaps without stretching their labels. Tenth-frame shading
marks individual frame columns rather than alternating ten-frame blocks.

These checks ran offscreen, including the final nine-case toolbar/pivot run in
`build/toolbar-pivot-followup.xml`. Lint, formatting and mypy remain clean.

## Automatic key centering — 2026-10-23

Stopped playback and authoring gestures now share whole-frame snapping with the
timeline grid. Offscreen checks stop fractional playback and compare stored key
times with actual painted key centers, including toolbar transforms, direct scene
drags, numeric bone edits, mesh-pose keys and Insert key. Disabling Snap retains
subframes; explicit application-service times remain untouched.
