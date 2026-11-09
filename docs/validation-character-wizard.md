# Character Creator validation

Validated on Windows with Python 3.12/PySide6 6.12, 2026-10-24. GUI checks use
`QT_QPA_PLATFORM=offscreen` and isolated preferences. The owner's running app is
never opened, restarted or focused by this validation.

## Implementation

- Human creator: 271 component choices, 204 clothing/accessory choices, 25 Sets,
  18 style combinations, six eye states, seven hand poses and 17 source actions.
  All 506 option posters and 17 action posters are saved PNGs; original SVGs remain
  the editable/rendered sources.
- Creator categories add 36 original animals and 60 original household Objects.
  The complete offline library has 398 entries. Animal actions include idle,
  walk, run and jump. Props have purpose-specific mechanical/secondary motion.
- Clicking actions starts and loops the isolated preview. Appearance edits use
  a cheap composite vector and do not build dense action timelines while browsing.
- Five Object Views preserve stage placement, matching action identities and
  independent local edits. Inactive views are compressed snapshots, not evaluated
  rigs. Snapshot assets stay protected from deletion and resolve by digest after
  portable import. Old Three-quarter recipes load as Front 3/4.
- Human Root and shoulder point controls retain authored world poses, skin bind
  matrices, planted feet and unique pelvis retarget mapping. Two torso segments
  retain breathing and counter-rotation.
- Preview-only transparent/studio/park/room/city backgrounds never become scene
  assets. Back turns hide facial features and use rear clothing/shoe details.

## Crash investigation

The owner's Windows event/dump for exit `0xC0000409` showed `abort → _purecall`
through QObject destruction and Shiboken deletion. This supports a Qt wrapper
lifetime/thread failure; the original crash was not independently reproduced.
Job signal objects now retain GUI-thread ownership until queued completion, and
application cyclic garbage collection runs on the GUI thread. Closing a creator
invalidates pending work before any destroyed widget can receive a result.

The playback stress check paints all 17 actions twice, wraps each loop three
times, forces collection, changes wardrobe and closes during a worker rebuild.
A separate check verifies that worker allocations cannot trigger cyclic widget
finalizers. Passing stress checks are evidence for the fix, not a guarantee that
all possible native-library failures are eliminated.

## Evidence

The final focused runs pass:

| Evidence | Result / coverage |
| --- | --- |
| `build/creator-release-gui.txt` | 38 passed: creator, actual PNG decoding, library placement, native drag/drop, category navigation and Object Editor UI |
| `build/creator-idle-final-validation.txt` | 12 passed: per-identity normalized choreography, complete studio performances, connected joints and planted feet |
| `build/creator-playback-view-final.txt` | 9 passed: loop/switch/teardown stress, GUI-thread collection, renamed action identities and portable saved views |
| `build/creator-view-art-final.txt` | 10 passed: five view projections, rear artwork, protected source assets and save/import restoration |
| `build/creator-controls-cards-final.txt` | 7 passed: Root/shoulder world poses, retargeting and fitted animal/household previews |

Ruff lint/format and strict mypy logs are `build/creator-final-lint.txt`,
`build/creator-final-format.txt` and `build/creator-final-mypy.txt` (176 modules).
The earlier broad core run passed 72 checks and exposed three idle-rhythm
regressions; those are fixed and superseded by the successful choreography run.
Three Qt deprecation warnings in the GUI run concern test event constructors,
not runtime failures.

Six clothing changes measured **12.05 ms median**, **13.07 ms maximum**.
Five animal changes measured **5.70 ms median**, **6.01 ms maximum**.
These measure local appearance commands, not a frame-rate guarantee for other
machines. Browsing starts no full animation-build jobs. One isolated complete
17-action human build measured 3.18 seconds; full preparation runs in a worker.

Captures in `build/creator-redesign/` include desktop/compact/dress room, animal
and household creators, and the five-view contact sheet. Their framing, active
cards, silhouettes and rear shoe/face details were visually reviewed. Canonical
animal/household cards fit cropped artwork to 112 pixels before saving, and the
library reuses those cards instead of rebuilding geometry while browsing.

## Scope

Object Views switches static authored representations; it does not generate a
continuous turning animation. These are simple original stylized vector assets,
not anatomical simulation. Cloth collision and sitting clips remain outside this
increment. Saved `.rigchar` files are recipes; `.rigpack` files embed portable
vectors, wardrobe and source actions. Existing project instances keep their own
embedded art and edits; new templates load after refreshing/reopening the library.

See [Character Creator](character-wizard.md) for controls and rebuilding details.
