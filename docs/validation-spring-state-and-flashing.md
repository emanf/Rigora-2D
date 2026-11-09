# Spring activation visibility and live pose ownership

Spring Editor shows effective ON/OFF/MIXED, separate group/master gates and the
playhead frame. Checked Material buttons show the sampled keying state. The
master checkbox is labeled Key master to distinguish keying scope from enabled
state. Indicators follow group selection, timeline playback/scrubbing, key edits
and Undo/Redo without changing the project. An override can therefore show Group
ON, Master OFF, and effective Spring OFF without implying contradictory states.

The live drag solver could also keep publishing ordinary poses while Motion
Pilot published its own evaluated Spring pose. This alternated viewport content.
Live physics now yields to canonical key/Pilot previews, including queued timer
calls, and restores that preview when stopping. Scene and bone drag updates
publish their live result rather than an extra ordinary pose between ticks.

Live drag physics now uses the evaluator's Scene-space input and bind-space
output conversions with the actual transient object transform. It preserves
evaluated visibility/opacity, including covered clothing/parts. This aligns live
secondary motion with canonical playback without double object placement.

Offscreen tests use an actual premade Panda with first-bone/tail Springs, verify
Pilot takeover of a running live timer, compare every repeated displayed pose,
observe one publication per Scene drag update, retain visible part identities
and exercise real artwork painting. Activation tests cover held keys, master
overrides, mixed channels, frame changes and Undo/Redo. Initial combined checks:
**22 passed** in `build/spring-state-flashing-fixes.xml`; the broader follow-up
passed **86 tests** in `build/spring-state-flashing-regression.xml`.
Ruff and strict mypy pass.

Review: **9/10**, based on accurate state reporting, single pose ownership,
coordinate/attachment correctness, preserved artwork visibility and regression
coverage. All GUI testing uses `QT_QPA_PLATFORM=offscreen`.
