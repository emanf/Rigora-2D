# Prompt 17 architecture and implementation record

The canonical model is immutable dataclasses in `domain/entities.py` and
`domain/project.py`. Bone transforms form parent-first skeleton hierarchies;
ordinary groups/objects have their own hierarchy. `SceneEvaluator` compiles
numeric tracks, blends primary motion, resolves constraints, simulates Spring
motion at fixed ticks, applies joint limits and evaluates vector/mesh deformation.
The same evaluator serves preview, playback, scrubbing and export. Skinning maps
object containers through their saved bind matrices rather than parenting bone
records directly to scene groups.

`DynamicsService` already owns Spring configuration, named membership, presets,
test motion and baking. The modeless `SpringEditor` uses those commands and the
same solver for isolated drag/release previews. `SpringCursor` caches fixed
samples with bounded checkpoints and deterministic full-history reconstruction. Ordinary
tracks/clips and scene metadata are saved in version 2 project packages; additive
metadata is retained without changing the package schema. Immutable patches own
undo/redo. Existing `PuppetSession` is a motion-card trigger recorder; it does not
record pointer-driven transforms and will remain a separate card workflow.

The implementation extends these paths. Spring activation uses ordinary stepped
`spring.enabled` and `spring.master` tracks on existing bone/object identities.
Group metadata adds stable IDs/colors while preserving older named groups.
Object motion enters physics in Scene space and returns to bind space before
skinning, so container motion excites inertia without double placement. Baking
retains the procedural source clip and creates editable FK output with a
settling tail, optionally keeping the source selected. Motion Pilot produces
ordinary transform and compatible motion keys through the existing evaluator and
document history, with scratch state for previews and one publication on record.

Implementation and acceptance evidence follow below. The user workflow is in
[Spring and Motion Pilot](spring-and-motion-pilot.md).

All desktop validation for this milestone runs with `QT_QPA_PLATFORM=offscreen`;
no foreground Rigora windows or visible background helpers are used.

## Implemented integration

The domain and engine remain Qt-free. `domain/motion_pilot.py` validates inert
profile data. `application_services/motion_pilot.py` owns mapping, fixed-frame
capture, native clip retargeting, recording preparation and atomic publication.
The view model owns interaction states and background preparation; the modeless
panel owns collapsible controls and scoped Qt mouse/tablet input. No dependency
was added. `Animation → Motion Pilot` and the toolbox open the tool. Existing
hotkey motion cards remain available through Puppet Stage.

Spring metadata lives in scene extras, membership in existing Spring constraints
and root anchor metadata, and activation in normal stepped timeline tracks.
Stable UUID5 fallback identities let older named groups open without rewriting
their files. Editing persists the same identity with a color. Custom presets
embed reusable physical parameters, excluding bone-specific rest angles.
Reassignment moves a bone's activation ownership and adopts the destination's
keyed state. Removal discards that group's activation lanes, retaining ordinary
manual animation.

Evaluation order is primary tracks and recorded/native Pilot controls, ordinary
constraints, Spring input in Scene space, fixed 60 Hz Spring integration, return
to skin bind space, joint limits, then original vector/mesh deformation. Internal
Spring integration subdivides steps up to 240 Hz. Interactive release tests use
the same Spring solver on transient poses; explicit preview drags discard their
temporary authored changes on release. Normal editing outside preview retains
the existing one-command drag behavior.

Each immutable evaluator owns its kinematic cache and Spring cursor. Forward
playback extends completed ticks; fractional evaluation copies state. Backward
seeks restore the nearest preceding checkpoint. At most 64 one-second states
plus the initial state are retained; cold seeks replay from clip start. History
is never truncated to six seconds. Edits create a fresh evaluator, invalidating
its caches. Activation, pins and locked ancestry are checked during integration.

Baking samples actual evaluated output, including final joint limits, at project
frames and authored subframes. A physical decay estimate extends the requested
minimum tail for slow springs. Selected groups bypass only their own subsequent
simulation; unbaked groups stay live. Source clips and rig settings survive.
`fk_bones` controls ordinary constraint bypass; `spring_baked_bones` independently
controls secondary physics bypass. Native baked clips loaded into Pilot carry
editable `motion.fk` / `motion.spring_baked` channels so they cannot be simulated
twice. Reusable action imports remap baked bone identities.

Pilot captures pointer input against project frames, with interpolation across
missed input frames, deterministic follower delays, independent driver state,
and the final fractional sample on Stop. Preview publishes only a transient
pose. Record creates ordinary editable tracks in one Undo command. Existing
manual tracks remain; tagged Pilot output is updated on blended passes and
replaced for selected targets when blending is off. Native clip offsets combine
with pointer controls; source clips remain independently editable. Key reduction
is limited to position and bounded per axis, retaining timing and corners.

Preparation and Spring baking run in workers over isolated immutable revisions.
Cancel, document/context changes and stale results cannot publish partial data.
Input listeners and clocks are released when panels close. The app never moves
the operating-system cursor or captures input outside its viewport.

## Acceptance matrix

Tests use real services/evaluators and real Qt controls, with only file/device
boundaries isolated. File names below are under `tests/`.

| Criterion | Evidence |
| --- | --- |
| S1 automatic follow-through | `test_spring_activation.py`: premade Panda container motion excites its tail, without moving the bind-space root twice. |
| S2 bounciness | `test_prompt17_integration.py`: compare real low/high damping release trajectories and stable overshoot. |
| S3 settling speed | Same physical test compares the settled residual for 0.8 versus 5 Hz. |
| S4 signed gravity | Same test verifies opposing final angular bias for positive/negative gravity. |
| S5 rest rotation bounds | Same test bounds every evaluated sample to independent clockwise/counterclockwise limits. |
| S6 Translate | `test_springs_and_puppet.py`: rotation-only versus axial translation under moving/scaled parents. |
| S7 stretch/squash | Same tests check bounded lengths, connected joints, deep chains and singular-scale protection. |
| S8 multiple groups | `test_prompt17_integration.py`: Hair and Ear use independent rules; baking Hair leaves Ear live. |
| S9 descendants | `test_spring_editor_groups_gui.py`: actual assignment buttons with Include children on/off. |
| S10 reassignment | `test_spring_activation.py`: old membership/gates removed, destination keys adopted, Undo exact. |
| S11 isolated preview | `test_spring_preview_gui.py`: play/pause/repeat, root drag release, close and tab change preserve authored data. |
| S12 activation | `test_spring_activation.py` and `test_spring_timeline_channels_gui.py`: group/master boundaries, filtered context actions, Undo and reload. |
| S13 editable bake | `test_dynamics.py`, `test_prompt17_integration.py` and group GUI tests: faithful keys, adaptive tail, single group/all, repeated-bake protection, background publication. |
| S14 scrubbing | `test_spring_activation.py` and `test_spring_playback_performance.py`: direct/forward/backward/fractional samples match, including beyond six seconds; checkpoints remain bounded. |
| S15 persistence | Activation/integration/group tests save and reopen settings, IDs, colors, custom presets, source and baked animation; legacy named data remains intact. |
| M1 position recording | `test_motion_pilot.py` and `test_motion_pilot_gui.py`: pointer-driven ordinary position keys and real UI capture. |
| M2 rotation recording | Core tests record rotation/scale, move/edit/delete an angular key and Undo the deletion. |
| M3 scale | Core parametrized tests verify independent axes and uniform exponential scale with no initial jump. |
| M4 preview isolation | Core/UI tests compare the immutable project revision before/after Preview and Esc. |
| M5 Stop | Fractional final samples and held post-stop poses survive recording; paused input is ignored. |
| M6 Face Cursor | Core tests verify signed flip, Turn/forward angle, smooth versus immediate turning, and initial virtual reference isolation. |
| M7 Wave | Core tests combine independent move, rotate and scale waves with Transform disabled. |
| M8 mouse wave | Core tests verify stationary input holds phase and movement advances it. |
| M9 native clips | Four trigger-mode tests cover native animation, speed, reverse, click once/loop and follower retargeting; GUI imports `.rigaction` through the shared importer. |
| M10 in place | Native tests compare root X retained versus suppressed. |
| M11 Flock | Core tests verify follower offsets, uniform delay and repeatable seeded random delay; each target receives editable output. |
| M12 blending | Two-pass tests verify prior movement survives blended rotation and is replaced when blending is off; follower profiles are retained. |
| M13 optimization | Core tests compare key counts and turning samples; optimization can be disabled. |
| M14 editing | Recorded keys use the existing timeline/service edit and delete operations; affected timeline regression tests verify these operations. |
| M15 persistence | Core/integration tests save/reload profiles, recorded tracks and native clip combinations. |
| I1 combined physics | Integration test records a premade walking Panda, primary object motion and live tail Springs, comparing mesh vertices and bone matrices. |
| I2 playback/scrubbing | Same test seeks backward/forward and compares identical poses; general playback tests cover pause/speed/reverse. |
| I3 baking | Selective and native-baked tests verify bypass and faithful output after reload; an actual Godot rig export reconstructs matching combined mesh geometry. |
| I4 Undo/Redo | Core and GUI tests cover recording, groups, activation, presets, source retention and background baking. |
| I5 regression | Existing physics, timeline, constraints, rigging, project, character attachment, prior skin/hand crash and export suites are rerun offscreen. |

## Validation and scored review

Across separate acceptance and affected-regression batches, **295 distinct tests
have a passing latest result**, with no remaining failures or skips. This is a
targeted impact sweep, not a claim that the entire repository suite was run.
`build/prompt-17-validation.json` records each test's latest report and source
hashes so overlapping batches are not double-counted.

| Report under `build/` | Result |
| --- | --- |
| `prompt-17-spring-pilot-regression.xml` | 80 passed, 113.61 s: Spring/Pilot core, GUI, physics, preview, examples, compatibility and incremental playback. |
| `prompt-17-affected-regression.xml` | 193 passed and one dock-restoration failure, subsequently fixed and rechecked below; includes timeline, engine, rigging, projects, prior skin/hand fixes and real output formats. |
| `prompt-17-layout-final.xml` | 12 passed: saved/default/reset layout, timeline title and Pilot GUI. |
| `prompt-17-edit-export-final.xml` | 24 passed: recorded rotation/scale edits/deletion, smooth turning, missing references, long recording and actual combined Godot skin export. |
| `prompt-17-final-impact.xml` | 54 passed, 94.56 s: final workspace/layout, editor lifecycle, Pilot GUI/core and animation/channel authoring. |

Ruff lint and format checks pass for all 328 Python files; strict mypy passes
all 201 source modules. A bundled reusable `.rigpilot` profile was also decoded
through the domain validator. Existing Qt drag-event deprecation warnings do
not affect these outcomes.

The layout rechecks distinguish saved dock geometry from Qt's safe main-window
clamping to a smaller available display. They simulate the same display size
for exact dock comparisons. Scene timeline pixel height now survives restoration,
Object Editor shutdown preserves its separate Scene height, and tab-container
minimums permit timeline resizing. The shelf drag regression compares imported
parts with the actual source pack, replacing an outdated fixed part count.

Review score: **9/10**, using behavior/physics 35%, integration and persistence
30%, UI/lifecycle 20%, and validation/documentation 15%. The scored review checked
actual offscreen captures in `build/prompt-17-review/`, source impact paths and
automated behavior. It found and resolved filtered-lane scope, reassigned group
activation, explicit-preview drag publication, native baked-clip double physics,
remapped baked bone references, immediate-close profile persistence and layout
restoration/resizing. Physical pen hardware remains unverified;
repeatable validation instructions are in the user guide.

## Reference differences and explicit bounds

The subsequent [object-root and capture correction](validation-object-root-motion-pilot.md)
allows the first bone of an object to spring around its fixed attachment point,
and adds a visible Start action while preserving selection before capture.
Earlier standalone kinematic-root behavior remains available for unowned rigs.
