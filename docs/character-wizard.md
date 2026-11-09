# SVG Character Creation

Open **Create character…** from the toolbox or command palette. The Creator has
an isolated preview document. Appearance changes, colors and playback do not edit
or play the main Scene. **Add to Scene** places the character, retained SVG parts,
rig and checked source actions in one Undo step.

## Preview controls

The toolbar above the preview contains the five character view slots, View
options, Background, Zoom out, editable zoom percentage, Zoom in and one
Fit character button. Zoom and fit use the same Material icons as the Scene.
Fit camera and Actual size are available in View options, keeping distinct
framing commands out of the main button row. Mouse wheel zoom and middle-drag/Space-drag pan
use the same navigation as the Scene preview. F fits the camera and 1 selects
100 percent.

Resizing the Creator preserves the viewed scene center and any manual zoom or
pan. Use Fit character or Fit camera to reframe deliberately.

The character is centered inside a dedicated 640 × 480 preview camera; taller
proportions enlarge this stage. The whole viewport displays transparency, with
an optional border around the camera. Scene geometry is visible beyond it.
All preview viewports and artwork cards use the same theme-aware checkerboard:
medium-light neutral grays in dark mode and pale grays in light mode. This includes
the Scene, Object Editor, Content/Templates, Face and tracking previews. It is a
display background and never becomes exported character artwork. Cards, badges,
captions, transport controls and hover/selection colors follow the active palette.
View options toggle Grid, Transparency and Camera border.
They also contain **Preview choices on current character**. It is off by default:
cards use fixed, locally cached PNG previews and remain unchanged while the
character is edited. Enable it to render choices using the current character's
proportions, view and colors. This changes only card previews, not exported art.

Background offers Transparent, White, Gray, Black, Studio, Park, Street and a
custom color with live preview. These settings affect only the Creator preview;
they do not become character artwork or change the project camera.

Play/Pause and Repeat float at the bottom center. A thin progress strip attaches
to the preview's bottom edge, with a status message while rigs or cards load.
Ready animation can play while the remaining option thumbnails are prepared.

## Visual choices and defaults

The right pane uses square preview cards inside expandable categories. Only the
outer pane scrolls. Individual grids expand to show every item. Disclosure and
scroll positions remain stable while changing choices and colors.

Square grids throughout Character Creation, Content, Objects, appearance sheets,
action choices and curve presets share 128 × 128 logical-pixel cards, fixed
82 × 82 image wells and 8-pixel horizontal and vertical gaps. Resizing changes
the number of columns rather than stretching the cards. Small SVG features are
rendered at thumbnail resolution so eyes and lips remain readable and sharp.
New/reset workspaces give Assets enough default width for two card columns.

- **Click a card** to set the visible default. A Default badge identifies it.
- **Check a card** to retain an additional alternative. Clicking the artwork
  does not toggle its checkbox. Space toggles inclusion on the focused card.
- The current default is always saved, including when its alternative checkbox
  is clear. Unchecked non-default choices are excluded.

Preset characters include their silhouette, palette and outfit. Coordinated
outfit sets include Everyday, Business, Evening, Runner, Garden, Winter,
Explorer, Celebration, Courtroom, Black tie, Smart casual, Summer, Weekend,
Tennis, Studio, Training, Bookshop, Scholar and Rainy day. Clicking a set applies
its complete look; checking
sets retains all the pieces required to use them later, including empty choices
needed to clear accessories from a preceding outfit.

Component categories include lip-sync mouth sets, eyes, clothing, pants/skirts,
shoes, ties/scarves, headwear/headphones, glasses, watches/bracelets, necklaces,
belts, bags/capes, hair, hands, optional noses, mustaches and beards. Expressions
and Open/Blink/Wink eye poses have their own preview grids. Cards are rendered
from the actual SVG artwork before selection, then cached as PNGs by default.
Human facial/wardrobe categories are hidden for animal presets that do not
support them.

## Clothing layers and colors

Each category's **Color…** button edits the selected variant independently.
Palette controls set the shared Skin, Ink, Hair, Top, Bottom, Accent and Shoes
fallback paints. Changing colors updates the preview live; Apply keeps the
paint and Cancel restores the preceding recipe. Paint updates are throttled,
and the completed bone rig, mesh topology and animation keys are reused.
New garments have coordinated initial colors, including dark formal suits and
trousers. The category Color control opens the actual selected variant's paint.

Layer placement controls offer:

- Clothing: **Behind accessories** or separate **Front panels**, allowing ties
  and necklaces to sit between the garment layers.
- Watches: **Under sleeves** or **Over sleeves**. Opaque long cuffs cover an
  under-sleeve watch. Bracelets use the same wrist socket.
- Belts: **Under outerwear** or **Over outerwear**.

Long dresses and coat hems have separately bound secondary parts. Glasses sit
over facial features; headwear sits over hair; bags and capes sit behind the body.
This is authored layering, not fabric collision or cloth simulation.

In Object Editor → Clothing, retained components are ordinary appearance groups.
**Saved outfit sets** applies a coordinated set together. The existing
**Key choice at playhead** option can key it in the timeline. Individual retained
eyes, mouths and accessories can also be changed using their appearance cards.

## Face and lip-sync

Nine eye styles are available: Soft, Dot, Anime, Round, Lashes, Narrow, Sleepy,
Happy and Robot. Lip-sync mouth sets are Soft, Graphic, Ink, Small, Wide, Round,
Toon, Teeth and Fangs. Every retained mouth set contains the same ten registered
visemes: Rest, AI, E, O, U, FV, L, MBP, WQ and TH.

Facial timing keys are written to every retained set; its parent wardrobe group
determines the visible artwork. Switching mouth style keeps speech timing.
Blink controls preserve the facial part's local pivot through its bone binding.
Mustaches share the nose/mouth projection anchor, narrow in profile and scale
with head proportions. Rear views hide facial hair. Profile mouths are narrowed
to stay within the head silhouette.

## Shape and motion

**Shape and proportions** offers Simple line and Rounded rectangle bodies. The
rounded body has a white fill with fixed, uneven cubic contours, gently bowed
sides and asymmetric corners. It does not randomly jitter during playback.
Head size/shape, body length/width, arm/leg length, limb line width, outline
weight and Classic/Color/Outline/Sketch treatments are customizable.

Source animations are Stand, Idle, Walk, Run, Jump, Wave, Bow, Cheer and Point.
Click any action card to preview it; check the actions to export. They contain
ordinary editable bone tracks, with fixed segment lengths and matching boundary
poses. Stand/Idle/Walk/Run are looping cycles; the gestures and jump return to
their boundary pose as one-shot actions. Repeat in the preview can loop either.
Source motion is previewed independently of the exported-action checkboxes.
All actions may be unchecked when only artwork and an editable rig are needed.
Walk and Run use backward ground strokes and forward airborne recovery.
Walking torso lean stays below half a degree; running lean varies by preset below
3.2 degrees. A higher pelvis and smaller recovery lift keep the support leg more
extended instead of holding a crouch through the entire cycle. Source-action
identities survive view changes and renaming.
Saved characters retain their authored clips; regenerate a character to adopt
later generator motion changes.

## Hands and feet

Clothing offers 24 choices including none, with formal suits, tuxedos, blazers,
polos, cropped and striped tees, tank tops, cardigans, robes and raincoats.
There are nine pants/legwear choices including formal trousers, capri and cargo
shorts. Sleeves have outlined sides and hems; their attachment edge is left
unlined so the shoulder and elbow joins remain continuous.

Facial options include nine visible mustache styles, ten beard styles and seven
noses, each with a None choice. Long/full, pointed, forked and braided beards
remain replaceable vector parts bound to the head. Mustaches follow the projected
mouth/nose center in each view.

Hands offers nine gestures from the owner's `Untitled.svg`: Relaxed, Open,
Palm out, Fist, Loose fist, Point, Thumbs out, Wave and Curled fist. Each uses
the supplied left/right partners, with all original surface details preserved.
The skin and cuff fills default to white. Only palette and rig/view transforms
are applied; no generated hand contours, crease removal, wrist patches or
additional Sketch-mode outline passes are used. The earlier generated hand
styles are removed from the cards.

All pairs are uniformly resized to the same wrist socket. Clicking a gesture
replaces both visible hands; checking alternatives retains them for
later Object Editor wardrobe swaps. The previous hand is hidden, not overlaid.
Gloves default to white and support independent per-gesture colors. Directional
gesture names describe the thumbnail pose; the hand follows its animated wrist.
Front-view Open, Fist, Point and Thumbs out use the viewer-left artwork on both
limbs; the viewer-right copy is horizontally reflected around its wrist socket.
Back view uses the viewer-right artwork for these four gestures, with a
horizontally reflected copy on the viewer-left wrist.
Front 3/4 Loose fist and Curled fist horizontally reflect the viewer-right hand
about its wrist; Fist uses its unreflected right source. The viewer-left hand
retains its original partner.
The canonical hand artwork lives in `assets/characters/hands/`, is loaded once,
and remains vector geometry in generated characters. Existing saved project
artwork is preserved. Reopening an old Creator recipe resolves removed hand
choices to an available supplied gesture rather than leaving blank hands.

Bare stick feet have a rounded, flattened charcoal silhouette and ankle overlap.
Front/rear feet splay outward; right-facing views point both toes right. Foot
bones follow that direction. Shoes share a consistent sole registration, so
changing footwear does not change the ankle socket or add a second bare foot.

Hair includes sprigs, curls, fitted caps, buns, braids, loose tails, locks and
mechanical antenna/halo options, plus None. Fitted sections follow the head;
loose tails and locks remain on the secondary-motion hair bone. All five views
retain their own registration. Check alternatives to keep them replaceable.

Sleeves overlap the round shoulder and elbow caps; long cuffs reach the wrist.
Their attachment edges have no closing outline, so joined limbs read continuously.
The retained garment variants keep the same bone bindings and independent colors.

## Catalogs and storage

Templates and Creator presets use separate identities. Their generated catalogs
and PNG poster derivatives are cached locally with progress and cancellation.
The character's editable sources remain SVG. New art revisions regenerate the
cache atomically. Desktop/Downloads references are not runtime dependencies.
Generic image import and saved Custom Templates remain independent.

Focused validation covers real card clicks and checkboxes, square geometry,
preview centering/navigation/backgrounds, color cancellation and rig reuse,
retained lip-sync sets, outfit switching and Undo, rendered watch occlusion,
fixed-length gestures and Creator placement. Broader animal turnaround and
choreography review remains separate ongoing work.

## Hand registration and view comparison

Hands use the supplied adjacent vector partners and their registered wrists.
The Hands section offers **Mirror left hand** and **Mirror right hand** for the
current view. These are local transforms; changing one view does not change the
other four, and no path or surface detail is regenerated. Existing approved
orientations remain the defaults. The choices travel with the saved character
recipe and survive view changes.

**Compare all views** opens a static five-view sheet using original SVG sources
and the shared transparency surface. It does not change the preview's current
view or the destination Scene. Live plugin recipe providers appear alongside
built-in preset cards and are removed when their plugin is disabled.

Changing only the included animation checks filters the exported action catalog
on a worker while retaining the ready preview rig and decoded images. Preview
actions remain available independently of which actions are checked for export.
