# Offline content library

Use the docked **Assets → Content** shelf, or open
**Assets → Browse content library** (**Ctrl+Shift+B**). Search names, descriptions,
tags, authors and licenses. Collections include all supported categories, Favorites
and Recent. Category choices include populated collections; no downloaded catalog or network
account is required. The docked **Templates** and **Custom** tabs each list only
categories populated in that tab. A newly saved Custom Template can use an existing
category or a new category name.

The docked shelf reports the number **shown** separately from the number
**available**. A loaded catalog can have zero matches because search, category,
view or family filters are active. Use the filter-off button beside Search, or
**Clear filters** in the empty panel, to show the Templates collection again.
An empty Custom collection offers **Browse templates**; a failed catalog load
offers **Retry loading**. Thumbnail arrivals update existing cards without
resetting selection or scrolling, and Refresh retains the current browse filters.

Select an item to inspect its author, version, license, pack, tags, category and
engine compatibility. Every bundled entry has a prebuilt 144 × 144 PNG thumbnail
inside its pack, also kept under `assets/thumbnails/`. Browsing decodes these
images once and shares the icons between the docked shelf and browser; it never
evaluates a rig to generate list thumbnails. The viewport previews the
prospective result in a separate document; Play preview runs that document's real
animation evaluator. The current project and its playhead stay unchanged.
Animated previews play and loop by default. Speed/strength changes retain playback;
Pause is explicit. Mesh wireframes are an optional **Show mesh overlay** diagnostic,
so layered characters stay readable. Unchanged packs and thumbnails are reused
while browsing.
Choose the target rig for poses/motions or the target mesh for deformation presets.
Incompatible anatomy, missing semantic bones and unavailable targets produce a
reason. A standalone compatible specimen still shows the preset in the preview.
Drop placeable templates on Welcome to create a project, or onto an open scene.
Every project edit is one undo item, including dependent asset imports.

Drag an item onto the main viewport. New rigs, artwork and scene fragments show
a translucent placement preview. Reusable Objects, including scene/background
templates, center their pivot on the pointer; other fragments retain their
root anchor. Motions and poses require a compatible rig under the pointer; FFD requires
artwork. An animation ghost plays without changing the project or its playhead.
Invalid drops explain the required target. Drags use the copy cursor and viewport
placement preview without a floating thumbnail. Double-click a standalone character,
rig or artwork to add it to the main Scene without opening Object Editor. Its
right-click menu offers **Add to Objects** to import it without placement, and
**Add to Scene** for immediate placement. Poses, motions and deformation presets
retain their compatible-target workflow in the content browser.
Dragging onto the library preview inspects
the item without editing the project. Internal drags carry an installed content
identity, never arbitrary file paths. Favorite
and recent browsing history are local preferences, independent of project history.

## Starter content and anatomy

Semantic poses and motions require their declared anatomy and every named bone.
Angles use degrees and translations use authored local pixels. Numeric values
map directly; cross-anatomy and size-normalized retargeting are later work.
Custom rigs use explicit `semantic_mapping`, or unique bone names as semantics.
No creature anatomy is inferred from its display name.

Bundled content lives in `assets/library/starter.rigpack` and is included in the
installed wheel. `tools/build_content_library.py` reproduces its original data and
asset-specific artwork and PNG thumbnails. The generators use the same
domain/evaluation records and optional render dependencies; they fetch no external
content. `python tools/build_content_thumbnails.py` bakes posters for all existing
bundled packs before distribution. Original vectors remain the rendering sources.

## Preview controls

**Scenes & backgrounds** contains twelve flat vector templates: Sunlit meadow,
Pine forest, Coastal cove, Moonlit rooftops, Cozy room and Desert canyon, each as
a five-layer **Scene** and a single-piece **Background**. Both are centered Objects
that can be placed in any scene, edited, animated or saved in Objects. The original
1920 × 1080 vectors remain sharp; static templates contain no bones, running
physics or animation tracks. See [source artwork](../assets/scenes/README.md).

Four obsolete starter entries were retired: **Generic biped** and **Human
side-view** duplicate Human landmarks; **Dog structure** duplicates Cat / dog
quadruped; **Original prop artwork** is the old study prop, superseded by the Props
collections. Their unused starter-pack members and posters are removed. Reusable
character, animal, motion, prop and deformation packs remain available, and
installed user content and existing projects are unchanged. Empty categories are
omitted from both browser selectors; plugin/user categories appear when populated.

The bundled library contains **487 entries**. The original cast has 36 complete
character/animal entries in front, side and three-quarter views: 24 modular human
entries, three Bolt views and nine dog/cat/rabbit entries.
Humans include 17 independent source actions each; the legacy Bolt/animals have three.
The creator catalog has 42 animals (14 bird species), 60 household Objects,
32 layered Environment designs and 18 Vehicles. Rejected generated PNG atlases,
template packs, earlier converted PNG duplicates and static adult cutouts have
been removed. PNG character creation is removed; no replacement PNG character
or experimental rig is included. Cached thumbnails for the original SVG library
remain intact.

Cards show a source-format badge in their upper-left corner: SVG, PNG or the
actual other source type. A PNG poster never changes an SVG source badge. Mixed
image scenes show MIXED; rigs/actions show RIG/ANIM. The same badges appear on
Project assets and creator component cards.

Environment has 68 items: 32 SVG layered designs plus 36 tree, bush and
weather props moved into the appropriate category. Tree/bush/weather/terrain
filters avoid unrelated accessory choices. Vehicles has 18 side-view SVG transport
Objects. Birds & wings includes 14 bird species with Fly loops. Mechanical
clips rotate wheels/propellers or foreshorten rotors; terrain without moving parts
is explicitly static. Scene translation remains separate from in-place action.
Performance selects a preview/action for placement. Source timelines remain in
Object Editor and placed blocks belong to Main Scene. See
[Studio characters](studio-characters.md) and [Create character](character-wizard.md).
Multiword search matches every supplied word across metadata.

The original prop packs contain 144 original SVG props in twelve families;
36 nature/weather entries now live in Environment. Their families include:
balls, hats, tools, bags, eyewear, drinkware, trees, bushes/plants, fruit, weather,
basic shapes and household objects. The **Prop family** selector in both browsers
narrows accessory families to twelve designs; Environment families also include
the new layered designs. These props place as original vector
artwork with a small editable mesh; they are not pre-rigged characters. See
[`assets/props/README.md`](../assets/props/README.md) for sources and rebuilding.

Six SVG **spring examples** live in **Plants & springs**; search `spring-example`
or open them directly from Spring Editor. Flowers, a bush, willow, windsock and
mushroom include named spring groups and Breeze/Strong gust clips. See
[secondary motion](secondary-motion.md).

The preview window separates a template list, large transparency stage, and
Settings/Details/Share tabs. Animated items play and loop by default. Pause/Play,
Restart, Loop, Fit and the preview playhead control the isolated scratch document.
Changing FFD speed, loop count, strength or target rebuilds geometry while retaining
the play/pause preference and relative progress. Reopening the window resumes the
chosen playback mode. Static templates remain static. Character artwork previews
hide the bone overlay; skeleton templates still show their bones.

Native template drags advertise the internal MIME format and copy action. The
docked thumbnail grid supports dragging without consuming its source item.
Welcome accepts new rig/artwork/scene templates; motions need an existing target.

## Install and share

Saved Objects can be exchanged directly with **Export Object Package…** and
**Import Object Package…** in the Objects card menu. **Save to Custom Templates…**
installs a reusable snapshot under Content → Custom for other projects, with a
category picker and a complete composition poster. See [linked Objects](linked-objects.md)
for the editing, placement and package workflow.

**Install pack** reads a local `.rigpack` archive in a worker, validates it and
publishes it atomically under `content-packs/` beside the workspace preferences.
An existing pack identity is preserved rather than replaced silently. Up to 128
user packs are indexed; each supports up to 128 items. Corrupt installed packs are
skipped with diagnostics. Archives are never extracted or executed. Paths, duplicate
entries, encryption, JSON ambiguity and compressed/uncompressed size bounds are
checked before installing; the maximum pack size is 64 MiB.

Enter a name, author and license, then use **Save target rig** for a custom
skeleton or **Share scene pack** for the complete scene, including optional meshes,
weights, original source bytes, animation clips, constraints and metadata. Reuse
allocates fresh entity identities and remaps hierarchy, weights, bindings and
numeric parameter paths. Save the resulting project normally. Another user can
install the shared pack completely offline. Existing `.rigaction` curve-preserving
clip exchange remains in Timeline → Clips & markers.
Newly shared custom scenes and rigs also store a PNG poster at publication time.
Without optional rendering dependencies, sharing uses a bundled static poster.

## Pack format 1

Each ZIP contains `manifest.json` and optional portable relative media entries.
The manifest is a `ContentPack` record with UUID `id`, `name`,
`format: "rigora.content-pack"`, `version: 1`, `author`, `license` and `items`.
Every item has its own UUID, name, description, author, license, version string,
tags, category, optional thumbnail path, `engine_version: 1`, kind and payload.
Unknown optional metadata is retained as inert extension data.

| Kind | Payload | Application |
| --- | --- | --- |
| `rig` | Typed `skeleton` record; extras declare `anatomy`, `semantic_mapping`, and retargeting rules | New independent skeleton and character |
| `pose` | `anatomy`, `channels` of `{semantic, path, value}` | Rest transform components on a compatible rig |
| `action` | `anatomy`, `fps`, `duration`, `loop`, channels of `{semantic, path, keys: [[frame, value], ...]}` | New common-timeline numeric clip |
| `deformation` | Existing `kind`/`parameters`, or normalized FFD `columns`, `rows`, `shape`/`motion` | Non-destructive stage on a targeted mesh |
| `artwork` | `source` path inside the pack | Embedded artwork and UV mesh |
| `scene` | Typed inline `project` or `project_source` naming a JSON pack member; `sources` maps asset UUIDs to pack paths | Atomic scene fragment merge with fresh identities |

Action payloads can retain optional `segments` metadata for start/loop/end
intervals. Starter actions use a loop segment. Format 1 semantic examples contain
linear numeric keys; complete scene sharing preserves full Bézier clip records.
Optional mesh/weight character templates use the `scene` form, which carries the
same project records rather than a competing mesh or skinning schema.

New normalized FFD preset applications convert source timing to project FPS and
snap samples to whole project frames. Their total duration rounds to the nearest
frame, with a minimum of one frame. Colliding samples merge, preserving opening
and closing poses, and smooth interpolation is rebuilt at the resulting times.
This avoids fractional-frame keys when, for example, a 30-fps preset is used in a
24-fps project. Existing project keys are not retimed on load. Set payload
`snap_to_frames: false` to retain precise fractional timing; custom FFD exports
include this setting so their stored sample times survive reapplication.

Detailed built-in scenes keep their project JSON in a separate archive member,
bounded to 32 MiB and validated when used. Catalog browsing reads only lightweight
metadata. Optional `performance_clips` lists clip IDs/names for the picker;
`selected_clip` chooses an existing source clip before identities are remapped.
Legacy inline scenes remain supported. Neither form extracts archive paths.

Python clients use `ContentLibrary` for discovery/install and `ContentService`
for compatibility, scratch previews, application and export. Both live in
`rigora.application_services.content_library`; storage lives in
`rigora.infrastructure.content_packs`. No Qt import is required by these services.
