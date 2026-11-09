# Object views, skin selection and Camera actions validation

Reviewed on 29 October 2026 using the source application with Qt offscreen.
No executable bundles were compiled and no foreground application received input.

## Verified behavior

- Real Milo and legacy Bolt templates open at Default, select their existing
  artwork, and expose independent empty sides without disabling the selector.
  New side artwork survives view changes; inactive parts leave the editable
  scope, deformation and owner-specific physics evaluation. Compressed authored
  views from older documents load without replacing Default identities.
- Scene View keys hold the chosen representation, preserve the base before the
  first key, and survive persistence and Undo. Object Editor ignores scene View
  keys while editing a slot. Scene/Camera creation controls are hidden there.
- First Skin insertion works on a plain Object and the real Milo template with
  no existing scene tracks, including a cleared card selection. Saved palettes
  retain the clicked color's role/source identity after refresh and Save.
  View-local skin scope and saved sheets exclude inactive-side artwork.
- Camera channels share flat Transform, Cut, Animation and Effect rows. Cut keys
  use camera icons and choose the active output camera at the exact frame while
  retaining the previous camera beforehand. Editing a motion restores its target
  camera even when another camera is active at the playhead.
- All 14 motion presets change evaluated camera matrices, preserve rest transforms,
  survive save/reload, and support Undo/removal. All 15 lens presets produce valid,
  deterministic SVG output and expire after their interval. Overlapping effects
  retain the strongest weighted intensity and its speed.
- Offscreen Main Scene renders the same evaluated lens overlay generator used
  by exported SVG and the existing raster/video frame pipeline. Visual review
  replaced stepped vignette bands with a smooth radial fade and increased film
  grain density. Preview renderers accept the generated SVG.

## Checks

**111 distinct tests have passing latest results** across these reports:

- `build/views-cameras-regression.xml`: 109 cases; two stale assertions failed
  initially (expanded Camera channel catalog and existing saved-Object asset
  protection wording). Both assertions were corrected and their tests passed
  in the following focused run.
- `build/views-cameras-final.xml`: 57 passed, including those two cases and an
  added legacy-view persistence test.
- `build/view-skin-scope-final.xml`: 40 passed, including view-local appearance,
  source-action selection and weighted effect overlap checks.
- `build/camera-visual-final.xml`: 34 passed after the visual adjustments.
- `build/camera-edit-final.xml`: three passed with the added target-camera,
  speed/duration edit and Undo assertions in the existing Camera UI case.

Ruff lint and format checks cover 607 Python files; mypy covers 220 source
modules. UI review captures are `build/camera-action-rows.png` and
`build/camera-effects-review.png`. The overlay contact sheet uses original
geometric scenery to make the effects visible against a consistent background.

Re-run the principal focused checks:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_editable_view_slots.py tests/test_view_and_camera_actions_gui.py tests/test_skin_insert_and_swatch_gui.py tests/test_camera_presets.py tests/test_cameras.py tests/test_cameras_gui.py tests/test_object_views.py
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m mypy
```

## Review score and limits

**9/10**: editing/persistence correctness **4/4**, ownership and view isolation
**3/3**, visual clarity **1.5/2**, platform coverage **0.5/1**.

Missing sides are authorable empty slots; selecting an angle does not invent
artwork. Camera lens presets are 2D vector graphics, with no optical refraction,
fluid simulation, depth-of-field or motion blur. Preset moves use sampled scalar
keys and intervals are limited to 7,200 frames. Existing native engine adapters
do not create camera components; the shared output guarantee here applies to
preview and the SVG/raster/video renderer. Linux/macOS window behavior was not
validated. See [the workflow guide](object-views-and-camera-actions.md).

## Active camera frame emphasis

The main workspace now draws the camera active at the evaluated frame in solid
white at two logical pixels. Other camera frames, labels and inactive-camera
selection handles use 28% opacity. Drawing the active frame last protects it at
overlapping edges. Painter state is restored before other workspace overlays.
Camera cuts do not change the editing selection or author document changes.

`build/camera-frame-focus.xml` records **16 passing tests** across camera GUI,
camera services and View/Camera action workflows. The added GUI check samples
actual viewport pixels before/at a cut and after elapsed-time playback crosses
it. It also checks coincident cameras, retained selection and unchanged history.
`build/camera-frame-highlights.png` shows the active white frame with the selected
inactive camera dimmed. Ruff lint/format pass for 608 Python files; mypy passes
for 220 source modules. All GUI tests ran offscreen; no bundle was rebuilt.

Review score: **9/10** — evaluated-frame correctness **4/4**, selection/history
preservation **3/3**, visual clarity **1.5/2**, platform coverage **0.5/1**.
Native Linux/macOS rendering was not validated.

## Live camera card previews

Camera Cut, Animation and Effect cards now preview in the main workspace by
default. Moves/effects loop on a 33 ms presentation timer; changed settings are
coalesced over 90 ms before constructing a new scratch document. Existing source
cuts are excluded only from that scratch arrangement, keeping the inspected
camera visible. Canonical CameraService commands construct the preview, and the
shared animation preview ViewModel publishes its evaluated pose. The viewport,
camera frame, backgrounds, lens overlays and an open Camera preview window use
that same pose. No extra asset generation occurs.

Close/Escape, preview-off, Apply/Remove, external document edits and context
changes release the transient pose/timers. Applying commits only the inspected
action. Preview does not add authoring history, move the source playhead, or
overwrite another tool's display preview.

**19 distinct focused tests pass** across `build/camera-action-preview.xml`
(11 passed) and `build/camera-preview-final.xml` (12 passed; four overlap).
Coverage includes real card clicks, automatic field changes, retained scratch
identity during looping, target-camera visibility across conflicting saved cuts,
source/history/clip/cursor isolation, Apply, preview-off, Escape, pending-timer
cleanup and external edits. Existing camera, scene-action, curve and animation
preview cases also pass. Captures are `build/camera-preview-cards.png` and
`build/camera-action-live-preview.png`.

Ruff lint/format pass for 609 Python files; mypy passes for 220 source modules.
GUI tests remained offscreen, with no executable build. Review score: **9/10** —
preview correctness **4/4**, source/lifecycle isolation **3/3**, UI clarity
**1.5/2**, platform coverage **0.5/1**. Native Linux/macOS execution was not tested.
