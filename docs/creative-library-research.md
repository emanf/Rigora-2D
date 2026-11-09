# Editable template research and selection

## Candidate review

Scores are suitability judgements, out of 10: direct 2D applicability (4 points),
clear reusable licensing (3), and integration/dependency cost (3). A high score
does not certify animation quality or imply that a candidate was integrated.

| Candidate | License/evidence | Score | Decision |
| --- | --- | ---: | --- |
| [Godot Skeleton2D demo](https://github.com/godotengine/godot-demo-projects/tree/master/2d/skeleton) | [README credits rigging/animation to RustyStriker under MIT](https://raw.githubusercontent.com/godotengine/godot-demo-projects/master/2d/skeleton/README.md) | 9 | Selected: eight numeric motion clips, no artwork or controller |
| [Quaternius Universal Animation Library](https://quaternius.com/packs/universalanimationlibrary.html) | CC0; free and paid subsets differ | 8 | Strong future 3D-source candidate; not integrated |
| [Quaternius Universal Animation Library 2](https://quaternius.com/packs/universalanimationlibrary2.html) | CC0; verify the chosen download edition | 8 | Not integrated; needs projection and retarget review |
| [KayKit legacy animations](https://kaylousberg.itch.io/kaykit-animations) | CC0 | 6 | Legacy legless model limits useful foot choreography; not integrated |
| [100STYLE](https://www.ianxmason.com/100style/) | CC BY 4.0; BVH mocap styles | 7 | Valuable future attributed import; full original download is 1.5 GB, not integrated |
| [DragonBones runtime](https://github.com/DragonBones/DragonBonesCPP) | MIT runtime | 6 | Duplicate runtime is unnecessary; not integrated |
| [DragonBones Demos](https://github.com/DragonBones/Demos) | Demo assets CC BY-NC-SA 4.0 | 3 | Excluded from the distributable preset library |
| [Spine runtimes](https://github.com/EsotericSoftware/spine-runtimes) | Spine-specific runtime license | 3 | Excluded; not an unrestricted open asset library |
| [Mannequin.js](https://github.com/boytchev/mannequin.js) | GPL-3.0 | 4 | 3D system and different licensing obligations; not copied |
| [ProceduralWalking2D](https://github.com/Jaeyoung0209/ProceduralWalking2D) | Reuse license not verified | 4 | Reference only; no copied code/data |
| [2D Procedural Hyper Motion Controller](https://github.com/cristhiandrm/2D-Procedural-Hyper-Motion-Controller) | Reuse license not verified | 4 | Reference only; no copied code/data |
| [ozz-animation](https://github.com/guillaumeblanc/ozz-animation) | MIT | 5 | Useful 3D engine, unnecessary C++ integration for this scope |
| [Rive runtime](https://github.com/rive-app/rive-runtime) | MIT runtime; asset terms separate | 5 | Runtime is not a ready motion-data library; not integrated |
| [RGS_Dev modular animated characters](https://rgsdev.itch.io/free-cc0-modular-animated-vector-characters-2d) | CC0 sprites; Inkscape sources are separate | 6 | Not adopted: flattened animation frames do not provide reusable bone curves |
| [RGS_Dev Character Prototype Animated](https://opengameart.org/content/character-prototype-animated) | CC0 PNG frames | 6 | Attack, roll and slide families inform scope; no copied artwork or inferred rig claims |
| [Shepardskin Human RPG Character](https://opengameart.org/content/human-rpg-character) | CC0 pixel sprites | 5 | Useful sprite-sheet source, not a matching SVG skeletal action library; not integrated |
| [ATMANAN Walking Character Set](https://opengameart.org/content/walking-character-set) | CC0 pixel sprites | 5 | Reference only; not presented as reusable skeletal data |

A runtime's license does not license every sample illustration. No unknown-license,
noncommercial-only or paid proprietary motion data was copied. Quaternius and
100STYLE remain candidates, not silently claimed additions.

## Adaptation and provenance

`assets/motions/godot-skeleton2d/motions.json` retains the source `player.tscn` URL
and SHA-256. Its eight clips are Fall, Fly, Idle, Jump, Land, Land hard, Run and
Walk. Local numeric rotations were mapped onto Rigora's human semantic bones,
sampled to rest-relative channels and paired with the source loop flags. The
complete upstream MIT license and explicit animation credit accompany the data.

The other 267 presets are authored independently: 11 skeletons, 73 skeletal
motions, 26 FFD motions/shapes, 20 spring profiles, 112 static SVG compositions
and 25 layered animated Objects. Styles alter stride,
cadence, torso lean, arm swing, head motion and bounce. Fixed-length two-link legs
and periodic cubic derivatives avoid disconnected joints and loop-boundary holds.
These are handcrafted procedural cycles, not mocap claims.

The second research pass expands action families into work, combat, social,
exercise, dance and climbing/swimming. Those additional 36 actions are original,
fixed-length, rest-relative choreography. Existing eight MIT demo motions remain
the only adopted third-party motion data. New fire/water/weather Objects use
original SVG layers and ordinary transform, opacity and FFD keys, with no extra
animation executable or PNG sequence dependency.

## Implementation boundaries

- Domain: Spring is a validated first-class content kind; no Qt dependency.
- Infrastructure: deterministic original skeleton/motion/effect catalogs and
  licensed numeric motion source.
- Application services: transactional placement, semantic adaptation, normalized
  FFD keys, live spring configuration and real evaluated posters.
- Presentation: asynchronous discovery/hover previews, selection-aware application,
  standalone scene placement and existing timeline/editing controls.
- Cache: 275 new PNG posters and five generated packs, published atomically with
  the character/Creator cache. No proprietary archive dependency.

Validation and numeric completion review are recorded in
[content redesign work](content-redesign-work.md). The user-facing workflow and
practical limitations are in [Creative Templates](creative-templates.md).
