# Main Scene character track choices

This records the initial picker implementation. Its nested option presentation
and separate Motion blocks page are superseded by
[flat scene action rows](validation-scene-action-lanes.md).

Reviewed on 29 October 2026 using source tests with `QT_QPA_PLATFORM=offscreen`.

Selecting a placed Object and opening Add tracks now exposes its saved animations,
clothing alternatives and skin presets. Categories expand independently and retain
their disclosure state when authoring refreshes the picker. Regular property tracks
and their drag-to-key behavior remain available.

Animations use the existing motion-window services and open Motion blocks for
duration, position, speed and repeat editing. Multiple selected actions are placed
consecutively in one Undo step. Clothing and skin choices create ordinary step keys
with the existing appearance-group metadata. They hold until the next choice.
The Clothing None choice restores uncovered body parts.

Keyed choices no longer rewrite saved appearance selection/default metadata.
Clothing occlusion decisions use the evaluated choices at the playhead. Source
actions, reusable Object definitions and other linked instances remain unchanged
when a Main Scene appearance key is authored.

Validation: **36 distinct focused tests pass**, covering full Milo action discovery,
real inline picker buttons, sequential motion placement, exclusive clothing,
uncovered-part restoration, skin holds, linked-instance isolation, source/default
preservation, save/reopen, Undo/Redo and existing timeline/character workflows.
Ruff lint/format checks and mypy also pass. Generated UI evidence is saved to
`build/main-scene-animation-choices.png`.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_scene_character_tracks_gui.py tests/test_character_objects.py tests/test_timeline_redesign_gui.py tests/test_template_tracks_gui.py
```

Review score: **9/10** — behavior **4/4**, shared-data isolation **3/3**, UI and
accessibility **1.5/2**, platform validation **0.5/1**. The UI offers saved presets;
new clothes and skin presets are authored in Object Editor. Appearance timing uses
hold keys rather than a separate duration-block editor. Native Linux/macOS window
behavior and exhaustive keyboard/screen-reader interaction were not tested.
