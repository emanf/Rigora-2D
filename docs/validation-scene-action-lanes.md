# Flat scene action rows

Reviewed on 29 October 2026 against the source application, with Qt offscreen.

The Main Scene dope sheet presents Animation, Skin and Clothing directly beneath
each Object. Appearance collections do not create additional tree levels. Object
headers overlay their visible key times and motion intervals as a read-only
overview. Overview geometry is deduplicated during rebuilds, rather than drawing
the same interval once per source track on every repaint.

Animation intervals share the dope sheet's ruler, zoom and scrolling. Bundled
Material running icons mark both ends; the name and speed sit in a gap in the
connecting line. Pointer drags move/trim existing motion-window records, committing
one Undo command on release. Escape and focus loss discard unfinished timing.
Right-click/double-click opens source cards and numeric start/end, speed and loop
settings. Changing speed preserves the chosen interval. Source keys remain intact.

Palette and shirt icons represent ordinary grouped appearance step keys. Their
editor offers one collection selector and a flat card grid, including saved skin
swatches, cached garment artwork, clothing show/hide, and None. Opening, browsing
or selecting cards never edits the document; Apply is explicit. Icon updates do
not rebuild the card grid. Unused animation fields stay hidden in appearance
editors. Skin presets are labeled Skin sheets in Object Editor.

Keys remember the selected preset's identity/name in additive metadata, retaining
the canonical scalar values used by the existing evaluator. Older keys without
that metadata can be recognized from their stored values or evaluated clothing.
Replacing a choice removes obsolete scalar keys for that collection at the
edited frame. Placed instances, linked defaults, other instances and reusable
source clips retain their existing ownership rules. Stale scene/clip/object
contexts and removed motion actions reject edits.

The Add tracks picker exposes flat Animation, Skin and Clothing rows, with saved
option counts and explicit empty guidance. Animation cards support multiple
selection and sequential insertion in one Undo operation. The old separate Motion
blocks tab is hidden; existing arrangement data remains compatible.

Validation covers the real Milo template and small linked Objects, flat rows,
both endpoint glyphs, read-only overview hit testing, pointer movement/trimming,
Escape, speed/loop edits, track visibility, appearance replacement and removal,
held values, stale-context rejection, Undo/Redo, save/reopen, source preservation,
and existing timeline/curve/placement workflows. UI captures are generated under
`build/`: `milo-scene-actions.png`, `milo-clothing-action.png`,
`milo-add-tracks.png`, `scene-action-lanes.png` and `scene-animation-span.png`.

Results: **61 distinct focused tests pass** across the 60-test regression run
and the seven-test action-polish run (six overlapping tests, one added check).
The final Selected only/source-name filter check also passes. Ruff lint and
format checks pass for 598 files; mypy passes for 217 source modules. Tests use
offscreen Qt only, and no executable bundles were compiled. JUnit reports are
`build/scene-actions-final.xml`, `build/action-polish-final.xml` and
`build/action-filter-final.xml`.

Run the focused regression suite:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_scene_action_lanes_gui.py tests/test_scene_character_tracks_gui.py tests/test_template_tracks_gui.py tests/test_character_objects.py tests/test_timeline_redesign_gui.py tests/test_object_scene_actions_gui.py tests/test_timeline_title_gui.py tests/test_selection_timeline_gui.py
```

Review score: **9/10** — editing correctness **4/4**, source/instance isolation
**3/3**, visual clarity/accessibility **1.5/2**, platform coverage **0.5/1**.
Appearance alternatives must already exist on the Object. Overlapping animations
retain the evaluator's existing blend/order behavior; automatic crossfades are
not added. Motion spans use their action editor for source/timing/removal; ordinary
key clipboard commands remain for scalar and appearance keys. Native Linux/macOS
window behavior and comprehensive screen-reader operation were not validated.
