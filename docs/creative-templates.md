# Creative Templates

Assets → Content → Templates contains editable presets rather than flattened
illustrations of animation. Only populated categories appear. First use prepares
PNG posters in a versioned local cache, with progress and cancellation; browsing
reuses those posters. No source-tree preview PNG collection is required.
Rig and motion posters use dark silhouette edges and a light halo to keep bones
readable on transparency tiles. The live viewport uses the same contrast approach.

## Included data

| Family | Count | Result |
| --- | ---: | --- |
| Skeleton templates | 11 | Human, child, quadruped, bird, hand and flexible-chain bones |
| Human walks | 12 | Ten original forward cycles, backward Walk and one credited MIT demo cycle |
| Human runs | 9 | Eight retargeted run styles and one credited MIT demo cycle |
| Animal motions | 12 | Cat, fox and rabbit Walk, Run, Idle and Jump |
| Human idle & stand | 2 | Subtle original full-body cycles |
| Gestures & actions | 15 | Jump, Hop, High jump, Crouch, Stretch, Wave, Bow, Cheer, Point and six MIT demo motions |
| Work & interactions | 8 | Push, pull, lift, carry, throw, catch, pick up and open a door |
| Combat & reactions | 9 | Punches, kicks, sword slash, dodge, hit reaction and fall |
| Social gestures | 7 | Salute, nod, shake head, shrug, clap, laugh and talking hands |
| Exercise & poses | 6 | Stretch, jumping jacks, squat, sit, stand up and balance |
| Dance & celebrations | 3 | Side groove, disco point and victory bounce |
| Jumps & climbing | 2 | Climb ladder and swimming crawl |
| FFD motions | 20 | Breathing, squash/stretch, ripples, sway, rubber and entrance/exit motions |
| FFD shapes | 6 | Bend, taper, pinch and inflate lattices |
| Spring dynamics | 20 | Hair, tails, cloth, ears, ropes, antennas and general follow-through |
| Shapes | 39 | Geometric silhouettes, stars, arrows, clouds, bubbles and symbols |
| SVG props | 73 | Interiors, nature, tools, adventure, food, drink, vehicles and balls |
| Animated Objects | 25 | Fire/smoke, water/weather, atmosphere/magic and moving mechanisms |

The 279 presets complement eight separate original character templates: 287
Template entries in total before any user-installed content.
Natural, relaxed, heavy, funny, cartoon and anime-style locomotion are choreography
choices on compatible rigs; they do not imply motion-capture realism.

Human runs adapt CC0 KayKit lower-body trajectories, with separately authored arms and
restrained torso lean. Jump/Hop/High jump adapt the same source pack’s short/long jump
trajectories. Source pins, licenses and reproduction notes are in
`assets/motions/kaykit-run/` and `assets/motions/kaykit-jump/`. Walk choreography is unchanged.

## Skeletons and binding

Drag a skeleton onto an unlocked Object to add its editable rig without moving
the existing artwork. Drop into empty space to create bones in a selectable empty
Object. Moving or deleting that Object carries or deletes its owned bones.
The viewport enables bone display for a new bare-rig placement.

Adding bones and binding artwork are distinct operations. Fit the bones to the
artwork, then use the existing Bind controls to choose which parts they deform.
The template does not guess weights or silently bind unrelated artwork.

## Applying skeletal motion

Drag a motion onto a compatible rigged Object. In the Scene, it becomes an
ordinary named Animation segment at the current frame, backed by an editable
Object source clip. Existing speed, repetition and segment-duration controls
remain available. In Object Editor, it adds an editable local source action.

Double-click applies to the current compatible selection. The context-menu
**Add to Scene** command creates a standalone demonstration. Dropping in empty
space also creates an animated bone-only Object, without importing artwork or
opening Object Editor.

Motion channels map through semantic bone identities, such as `hips`, `spine`,
`thigh.L` and `forearm.R`. Human/biped/robot rigs need the corresponding semantics;
arbitrary bone numbering is not enough. Secondary hair/cloth/ear/tail channels are
optional. Relative channels preserve authored rest transforms and bone lengths;
root travel scales with leg length. Locomotion cycles are authored in place.
Animate the placed Object's Transform to move it through the scene.

## FFD

Drag an FFD preset onto artwork. Its normalized lattice adapts to that mesh and
keeps the original SVG or image source. FFD motions add editable control-point
keys to the current animation timeline; FFD shapes add a static deformation
stage. The existing FFD controls provide strength, speed and repeat settings.
Drop in empty space for an original vector specimen with the same editable data.

An FFD target is one artwork mesh, not an entire multi-part character. For a
character, choose the intended part in Object Editor. Multiple FFD stages can
stack, so remove an earlier stage if replacing it instead of layering another.

## SVG props and animated Objects

Static props retain their original SVG source in a named editable Object. Shapes
include 39 silhouettes, rather than counting color variants as separate assets.
Props cover interiors, nature, food, vehicles, tools and adventure items.

Animated Objects include Torch, Campfire, Bonfire, Candle, Lantern, Brazier,
Water surface, Ocean waves, Waterfall, Fountain, Water splash, Dripping tap,
Rain, Snow, Bubbles, Steam, Smoke, Dust puff, Sparkle burst, Magic portal,
Electric arcs, Windmill, Turning gear, Pendulum and Flag in wind.

Drag one into the Scene to place a named Animation segment. Its separate vector
layers, transform/opacity keys and any wave FFD stages remain editable in Object
Editor. They are stylized 2D effects, not fluid or fire simulations. Moving and
deleting their Object carries their entire content. Additions inside Object
Editor remain inside the edited Object, including drops on empty preview space.

## Spring dynamics

Drag a spring preset onto a bone to configure its descendant chain. Dropping onto
a rig selects secondary hair, tail, ear or cloth bones when available; otherwise
it uses the rig's nonroot bones. Inspect the chosen group in Spring Editor before
using a general whole-rig preset for a production character.

The preset installs real live constraints and an activation key, keeping existing
primary animation. Springs react to movement; a stationary rig may show little
change. Hover previews use an isolated test driver. An empty-space drop creates
a flexible-chain Object with an editable motion-test driver, making the response
visible immediately. Physics and driver keys remain editable and undoable.

## Ownership, source and limits

An FFD motion dropped into an empty Scene creates an editable SVG specimen and
a named Object animation. Its linked placement appears on the Scene **Animation**
row. Double-click the Object and open **Motions** to select that animation. Its
**Deformation** keys support selection, moving, deletion and curve editing.
Source edits update the linked Scene placement through the common action system.
A targeted Scene drop retains the named action on the existing Object without
replacing its other tracks. In Object Editor, applying FFD layers its keys into
the selected local action, or creates a named action if none exists.

Previously authored Scene-only deformation channels remain editable on their
**Deformation** row; existing keys are not automatically converted on editor entry.
**Add Track** lists each deformation stage on the selected Object, including stages
on nested artwork parts. Direct vertex keys appear under **Mesh deformation**.

Each placement is a single Undo command. Hover previews use scratch documents,
without changing the source project. Rigs, keys, lattices and constraints survive
normal project save/reload and Object ownership.

The catalog uses editable 2D sources. Whole-character multi-mesh FFD, arbitrary
3D motion projection and fluid simulation are not implemented by these presets.
