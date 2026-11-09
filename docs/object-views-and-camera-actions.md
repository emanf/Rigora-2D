# Object views and camera actions

## Edit an Object view

Object Editor's view selector starts at **Default** for unpartitioned artwork.
Default retains the original parts and bindings. If a template identifies its
original angle, that named angle also shows the original representation. The
selector always offers Default, Front, Front 3/4, Side, Back 3/4 and Back.

Selecting another view loads its saved parts, bones and bindings into the editable
scope. Missing views stay empty. Add images, draw shapes or bones, and edit them
normally; new parts belong to the current slot. Switching back restores the
previous view's records and edits. Previously compressed, authored sides are
loaded when selected, retaining the original Default representation. Selecting
a missing side does not generate replacement artwork.

Views share the outer Object's placement. Inactive representations remain stored
in the document, while their mesh deformation and constraint owners are excluded
from evaluation. Object Editor uses the edited view independently of scene keys.
Its Path/Parts and Bones layer lists show the current editable scope. Add Scene
and Camera controls belong to Main Scene and are hidden in Object Editor.
Skin sheets, clothing choices and source animations in Object Editor follow the
edited representation. Scene action editors retain the Object's complete saved
choice collection.

In Main Scene, select the Object and choose **Add tracks → View**. Choose a card,
set the frame and insert. The View row uses a turnaround icon and held keys.
Right-click or double-click a key to replace its view; use an empty cell for
another view key. The base representation remains visible before the first key.
Keys, slot membership and all source artwork survive save/reopen and Undo.

## Animate cameras

Choose a camera in Add tracks. Transform adds ordinary camera transform channels;
Cut, Animation and Effect open card editors. All camera channels share a single
**Camera** header with one row per type:

```text
Camera
  Transform
  Cut
  Animation
  Effect
```

**Cut** cards choose the main/output camera at a frame. Camera-icon keys switch
all camera activation channels together and hold until the next cut. The
previous camera remains active before the cut. Right-click a camera key to
change its camera or frame.
The main workspace highlights the evaluated output camera with a white border
and dims the other camera frames. This follows cuts when scrubbing or playing,
without changing the editing selection.

**Preview in scene** is enabled when the camera action editor opens. Selecting a
camera, motion or effect card temporarily previews it in the main workspace.
Animation/effect previews loop and refresh when you change camera, start/end,
speed or strength. The preview begins inside the interval so fade-in effects are
visible immediately. The inspected camera stays active during the preview even
when the saved arrangement cuts elsewhere. An open Camera preview window also
shows the temporary output.

Preview uses a retained isolated document; browsing cards adds no keys or Undo
steps and does not move the saved playhead. Turn Preview in scene off, close the
editor, or press Escape to restore the saved display. Apply ends the preview and
commits the chosen action. Editing the source scene or changing workspace cancels
a stale preview. A short debounce coalesces rapid field/card changes; looping
evaluates the existing scratch scene rather than rebuilding preset tracks per tick.

**Animation** offers 14 motion presets: Pan left, Pan right, Rise, Descend, Push
in, Pull out, Handheld drift, Earthquake, Impact shake, Recoil, Zoom pulse, Gentle
sway, Dutch tilt and Whip pan. Choose the target camera, start/end, speed and
strength. Camera-icon endpoints delimit the interval; drag the middle to move
it, or an endpoint to adjust its duration. Right-click to edit the preset.

Moves use portable additive camera transform keys. They combine with authored
camera transforms without rewriting the rest camera. Pan/tilt/zoom moves hold
their final offset; shake and pulse moves settle. Speed changes curve progress
or oscillation frequency within the interval. Editing an interval regenerates
its preset keys. One action is limited to 7,200 frames.

**Effect** offers 15 screen-space presets: Rain on lens, Blood at edges,
Vignette, Dust specks, Snow flurries, Fog wash, Cinematic bars, White flash,
Blackout pulse, Whiteout pulse, Scanlines, Film grain, Damage pulse, Warm wash
and Cool wash. Strength fades in/out over the chosen interval. Speed controls
animated droplets, snow, grain and damage pulses. Several effects can coexist;
overlapping instances of the same preset use the strongest intensity.

Lens effects are original vector overlays clipped to the target camera. Preview,
SVG frames, and the raster/video pipeline use the same evaluated strengths and
overlay generator. They are 2D graphics rather than optical refraction, fluid
simulation, depth-of-field or motion blur. They apply when their camera is the
active output camera. The full workspace stays editable outside the camera frame.

These preset categories were informed by [Apple's camera behavior reference](https://support.apple.com/en-ph/guide/motion/motn17c69ccb/mac),
[Epic's shake-pattern reference](https://dev.epicgames.com/documentation/fortnite/camera-shake-effect-in-unreal-editor-for-fortnite?lang=en-US),
and [Epic's lens-effect reference](https://dev.epicgames.com/documentation/unreal-engine/post-process-effects-in-unreal-engine).
Rigora's curves, overlay drawings, and implementations are original.

## Saved skin editing

Skin actions can be the first keys in a scene, including at frame zero. The
action editor uses the first available card if its current selection was cleared;
an empty collection gives an explicit authoring message. Color cards in Object
Editor retain their role/source identity across saving and refreshes. Opening
their picker uses the clicked card's evaluated color, and Apply edits that same
paint rather than the first palette entry.
