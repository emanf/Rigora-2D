# Template root placement

Validated on 2026-11-04 using the source application and offscreen Qt. No desktop
bundle was compiled.

## Resource changes

The 11 skeleton resources now serialize one zero-length, non-deforming Rig Root
at the first anatomical root's authored base. Biped masters sit at the pelvis;
quadrupeds, birds and hands use their primary body/palm base; flexible chains use
their attachment rather than the middle of the chain. Semantic maps retain the
original deforming bone identities and exclude the master.

All eight built-in character/animal Templates and all nine Creator designs use
the same placement policy. Direct children subtract the master's translation,
and their source animation translation keys subtract the identical offset.
Existing rest matrices, bind matrices, artwork, motion curves and drop placement
therefore remain valid. The five skeleton recipes in the rigging service also
place their masters at the authored base.

The generated catalog revision advances from 20 to 21. Catalog publication keeps
the existing atomic generation/progress workflow. Motion and spring resources
that create fallback rigs receive the updated skeleton resources automatically.
FFD/artwork-only resources remain independent of skeletons. Custom packs and
already placed project Objects are not rewritten. Legacy root insertion still
uses an identity master; authored existing masters are never silently relocated.

## Verification

The focused affected suite passed **292 tests**, covering all 11 rig resources,
all 17 character/animal designs and their actions, all 81 reusable motions, all
20 spring presets, FFD resources, Scene/Object Editor root drags, skinning,
undo/save/load, selection modes and preview work budgets.

Resource-specific assertions verify the serialized master, semantic mapping,
original endpoint bounds and anatomical rest matrices. Each character action is
compared against independently authored world joints, including all bone world
matrices, while the master remains kinematic. GUI tests run offscreen.

Ruff lint/format checks pass for all 490 Python files; mypy passes for all 267
source files. Root positioning is resolved during resource construction, with no
new per-frame repair, asset scanning or preview rebuild work.

The local generated cache was refreshed successfully through all 500 generation
steps. An archive audit covered all **283 template items**, including all **19
serialized skeletons** (11 bare rigs and eight character/animal resources). Every
stored master is at its primary attachment, with rebased direct-child translation.

Review score: **9/10**, based on template coverage, pose/animation preservation,
root interactions, compatibility and runtime cost. Existing project instances
retain their current authoring data; re-add a Template to use its revised root.
