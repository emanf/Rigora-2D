# SVG Creator and shared card layout — working state

Updated 2026-11-03. The current art direction is SVG stick figures. The supplied
references distinguish a Simple line torso and a white, outlined Rounded rectangle
torso with deliberately uneven sides and corners. Both are implemented. Earlier
PNG character generation, prescribed fantasy proportions and approval requests
are superseded. Reference files are never runtime dependencies.

## Completed in this increment

- Rebuilt Character Creation around a centered, independent preview stage, shared
  viewport navigation, zoom percentage, camera/figure fit, backgrounds and view
  overlays. Play/Repeat float at the bottom; preparation has a thin progress bar.
- Replaced nested scrolling/list choices with expandable grids and actual artwork
  previews. Click selects the default; the separate checkbox retains alternatives.
  Current defaults are always exported. Disclosure and scroll state stay stable.
- Added complete presets, nineteen coordinated outfit sets, twenty-four clothing choices,
  pants/skirts, shoes, ties/scarves, headwear/headphones, glasses, watches/bracelets,
  necklaces, belts, bags/capes, thirteen hairstyles, hand poses and facial hair.
  Clothing front panels, sleeve coverage and accessory depth are authored layers.
  New options include formal suits, tuxedos, blazers, polo/cropped/striped tees,
  tank tops, cardigans, robes, raincoats, formal trousers, capri and cargo shorts.
  Sleeves outline their exposed sides and hems, leaving attachment roots unlined.
  Facial choices include nine visible mustaches, ten beards and seven noses, plus None.
- Card previews default to fixed cached PNGs. View → Preview choices on current
  character enables adaptive SVG previews without changing export choices, rig
  identities or playback time. Mode identity is tracked separately from recipe
  equality, including the canonical/default appearance.
- Hands use twelve distinct mirrored glove silhouettes at a common wrist socket.
  Only one hand per side is visible after variant swaps. Feet use a rounded,
  flattened charcoal silhouette with ankle overlap and view-correct toe direction.
- Shared transparency backgrounds, card paints, badges and controls follow the
  live dark/light palette across Scene, Object Editor, Creator, Face and tracking
  previews. Creator navigation uses the Scene's Material icons and one Fit character
  button; camera fit and actual size remain distinct commands in the View menu.
- Added nine eye styles and nine complete lip-sync mouth sets, ten shared visemes,
  expression cards and Open/Blink/Wink previews. Speech timing keys every retained
  mouth set; blink controls preserve the bound facial pivot.
- Added Stand, Idle, Walk, Run, Jump, Wave, Bow, Cheer and Point as ordinary editable
  source clips. Export selection is independent of preview; zero selected actions
  correctly exports artwork plus its rig. Complete outfit sets are available in
  Object Editor Clothing and can use existing appearance keys.
- Live palette and per-variant paints reuse bones, meshes and animation keys.
  Cancelling a color picker restores the preceding recipe and playback time.
  Preparation uses one cancellable worker and publishes the rig before thumbnails.
- Standardized square grids across Creator, Content, Objects/Imports, saved looks,
  appearance sheets, timeline/camera actions, curve presets and Puppet Stage.
  Cards are 128 square, image wells 82 square and both gaps 8 logical pixels.
  Face cards use the same fixed dimensions and spacing. Small SVG features render
  at thumbnail resolution; checkerboards preserve dark/white artwork readability.
  New/reset workspaces give Assets a 340-pixel default width for two card columns;
  saved user layouts remain respected.
- Corrected backward gait timing: ground strokes travel backward and airborne
  recovery travels forward. Walk torso lean stays below half a degree;
  Run is preset-specific, bounded below 3.2 degrees. Human and animal bone
  lengths and periodic boundary poses remain fixed/matched.
- Source clips carry stable recipe-motion metadata so renaming an action before
  changing an Object View preserves source identities and placed timeline blocks.
- Removed the unused legacy ChoiceCards/CardSection widgets and retired-asset
  dependencies from migrated Object/view regression fixtures.

## Validation and review

The focused regression command covers test_card_grid, test_creator_visual_options,
test_stick_character_shapes, test_facial, test_object_library, test_object_views,
test_face_workspace_gui, test_camera_action_preview_gui and
test_video_rig_gui, plus test_creator_gloves_feet and test_local_template_packs:
**119 passed** in the combined run. The additional canonical PNG/SVG preview-mode
regression is checked separately with Creator integration tests.
All GUI checks use QT_QPA_PLATFORM=offscreen. Source Ruff lint/format, mypy
(257 source files) and Run_Rigora.bat --no-pause --headless also pass.
No executable bundle was compiled.

Actual UI captures and original-vector motion strips/GIFs are disposable files in
build/creator-visual-review/. The latest measured isolated animation evaluation
averaged 1.603 ms; live color input dispatch took 20.204 ms on this host. These are
engine/input measurements, not a claim about full rendered frame rate.

Visual review: 8.5/10, based on aligned card/image bounds and equal gaps, legible
feature previews, stable anatomical framing, distinct replaceable options and
continuous motion/joins. This score does not claim final approval of every animal
turnaround or all possible garment combinations.

## Remaining broader work

- Broader animal turnaround and style/choreography review remains a separate art
  pass. Current tests verify animal gesture lengths, cycle seams and gait direction.
- Saved Objects retain their authored source clips. Generator gait changes apply
  to newly generated characters; existing characters must be regenerated to adopt
  the new motion. Do not silently overwrite user-authored animation.
- Older unrelated tests and documentation still reference the removed 487-item
  catalog, old motion names or the retired character_art modules. Migrate those
  fixtures to current generated catalogs; do not restore rejected assets. The
  focused checks above do not imply the entire historical test suite passes.

## Preservation and storage

Templates and Creator have separate identities: eight character Templates,
275 creative presets and nine Creator presets. SVG is the editable source; generated PNGs are disposable poster caches.
The cache revision is 18, generated atomically with progress and cancellation.
There are 188 fixed option-card posters in addition to the separate preset catalogs.
Existing saved projects, Custom Templates, imported media, fonts, icons, the
owner's bone.svg, audio, import/export adapters and plugins are preserved.

Retired resources were moved out of source before authoring new artwork, without
inspecting/reusing their designs. They remain in ignored
build/retired-content-20261102/ after automatic review rejected irreversible broad
deletion. Its removed-from-source.json is the relocation manifest. Do not inspect
or reuse those designs. There is no dependency on Desktop or Downloads at runtime.

The new original/credited catalog contains 275 presets, plus eight character
Templates: 283 built-in entries. It includes 11 skeletons, 81 skeletal motions,
26 FFD motions/shapes, 20 spring profiles, 112 original SVG props/shapes and 25
layered animated Objects. Motions include varied human locomotion, interactions,
combat, social gestures, exercise, dance, climbing/swimming and animal actions.
Eight numeric motions adapt the MIT Godot Skeleton2D demo with its notice and
provenance. The remaining 267 presets are independently authored CC0 data/art.

Reusable actions retarget rest-relative channels without changing bone lengths.
Periodic cubic endpoint derivatives and an explicit continuous-loop endpoint
preserve scene segment timing. Imported animated Objects rescale both key times
and Bezier tangent times to the target FPS. FFD presets retain normalized lattice
keys; spring presets configure the existing live solver and activation channels.
New bare rigs have identity local bind space and selectable Object ownership.
Object Editor additions stay inside the active Object even in empty preview space.

Static SVG Objects cover interiors, nature, vehicles, tools, adventure props, food,
shapes and symbols. Animated Objects include torches/campfires, candles/lanterns,
waterfalls, fountains, waves, rain/snow, smoke, sparkles and moving mechanisms.
The effects are editable stylized vector layers and keys, not fluid simulations.
PNG posters render actual evaluated geometry once into the cache. Startup reports
500 generation steps across Templates, Creator presets and option-card posters.

Research and license decisions are scored in
[the source-selection record](creative-library-research.md). Instructions and
limitations are in [Creative Templates](creative-templates.md).

## Creative library validation and review

The combined creative-template service/Object/GUI run passed **394 tests**.
The existing dynamics, card grids, Creator options, local packs, Object Views and
Object Library regression run, together with reference-only pack exclusion,
passed **93 tests**. The retired Panda fixture in the root-spring regression now
uses the current original Sumi SVG character. No retired artwork was restored.

Bone contrast and existing rig drawing/selection checks passed **25 tests**.
The final focused GUI/contrast recheck passed **21 tests**. These overlap the
earlier runs and are not additional unique checks. Visual evidence is under
ignored `build/creative-library-review/`. All desktop checks use Qt's
offscreen platform. Source Ruff lint/format, mypy (266 source files), and
`Run_Rigora.bat --no-pause --headless` pass. No executable was built.

Visual evidence includes contact sheets for every new SVG prop/effect, seven
actual-animation GIFs, five actual source-window category captures, and a
before/after bone-contrast comparison. The live viewport and generated posters
trace the owner-supplied SVG with a dark edge/light halo. Round joints, red
selection and original geometry remain preserved; outline caches are bounded.
