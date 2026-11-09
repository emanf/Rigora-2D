# Vector character collection

Open **Assets → Content → Templates** and choose **Characters** or **Animals**.
The View filter offers Front, Front 3/4, Side, Back 3/4 and Back. Select a Performance to
preview, apply or drag into the scene. Refresh after rebuilding packs. Existing
placed instances keep their embedded artwork and personal edits.

| Collection | Identities | Views | Actions per template |
| --- | --- | --- | --- |
| People | Milo, Luna, Theo, Iris | Front, side, Front 3/4 | 17 |
| Small children | Nico, Poppy | Front, side, Front 3/4 | 17 |
| Reference children | Blue Sneakers, Red Sneakers | Front, side, Front 3/4 | 17 |
| Robot | Bolt | Front, side, three-quarter | 3 |
| Animals | Scout the dog, Cleo the cat, Pip the rabbit | Front, side, three-quarter | 3 |

The original cast has **36 complete templates**, including 24 modular humans.
The new creator catalog adds **36 animals and 60 household Objects**. Three-quarter
human faces show both eyes; profiles show one. Redundant Ari/Nova catalog entries
were removed. Their previously saved project instances remain valid.

## Editing and motion

Each template is one compound Object in Main Scene. Move, rotate or scale its
container to carry the entire character, including planted feet. Double-click to
edit SVG parts, bones, skin, clothing and source actions. Object Editor uses the
rig's bind space even after stage transforms. Source actions have separate
timelines. Place an action as a Main Scene motion block to trim, repeat or change
speed; global Object transforms remain above the source action.

Recipe-backed characters also expose five **Object Views**; only one rig is active
at a time, and each view retains its edits. Human armatures include Root and
shoulder point controls around the two-segment torso.

Humans include Stand · Still, Idle · Breathe, Idle · Look around, three walk
styles, sprint, jog, hop, fidget, hello/goodbye waves, crouch, cheer, hit reaction,
reach and punch. Identities use different authored pose beats, holds,
arm gestures, body carriage and cadence. Hop includes anticipation, takeoff,
airborne tuck and recovery. These are stylized in-place cutout performances;
travel through the scene is a separate global transform animation.

Standing constrains each complete foot transform to its contact control. Walk,
run and jump release constraints through the action's FK bone list. Main Scene
motion blocks preserve those rules, including restoring idle after a run.
Imported action keys preserve seconds when the project frame rate differs.

Heads overlap necks. Hands render above arms, shoes/paws above legs; forearms and
shins remain behind upper segments. Circular socket caps meet at the same bone
pivot, without dark limb join outlines. Frontal animals have two forelegs and two
farther hindlegs. Runtime parts are SVG with embedded source bytes and small
editable meshes, without external fonts or raster cutouts.

## Authoring and rebuilding

The [character wizard](character-wizard.md) uses the same assembler as the human
catalog. Recipes live in `assets/characters/catalog.json`; runtime art and
choreography are in `src/rigora/infrastructure/character_art/`. Tools wrappers
preserve older generator imports.

Run in order from the repository root:

```text
.venv/Scripts/python.exe tools/build_component_posters.py
.venv/Scripts/python.exe tools/build_character_catalog.py
.venv/Scripts/python.exe tools/build_vector_catalog.py
.venv/Scripts/python.exe tools/build_creator_motion_posters.py
```

`tools/review_templates.py PACK OUTPUT --match NAME --action "Run · Sprint"`
renders evaluated motion sheets and animated WebP reviews. Omit the action filter
to inspect all actions. Saved PNG library posters are baked during builds;
browsing never assembles character geometry to generate icons.
