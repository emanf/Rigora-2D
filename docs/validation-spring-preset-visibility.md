# Visible spring preset feedback

Validated on 2026-10-21 with the local Windows/PySide6 environment.

- Clicking each of the ten presets on a stationary three-bone rig produces more
  than 15 pixels of immediate tip movement in the regression fixture. The root
  world matrix stays unchanged, joints remain attached, and subsequent solver
  steps continue moving the chain. The release adds no animation tracks or extra
  undo entries beyond the preset assignment.
- Presets now have clearer differences in frequency, damping, inertia and gravity.
  Stretchy permits lengthening, Squashy permits compression, and both disable
  angular spring motion. Existing project parameters stay intact until reapplied.
- Preset illustrations use the same coefficients/bounds and now drive their
  attachment vertically as well as horizontally, so axial elasticity is visible.
- Create motion test explicitly adds a separate three-second looping clip with
  editable Bézier root-driver keys. Tests verify more than 20 pixels of root travel,
  actual spring lag above five degrees, preservation of source clips/rest poses,
  one-step Undo, and use of the shared Play/Repeat transport. The live settling
  timer stops during timeline playback.

All 33 focused spring, group, save/Undo and playback checks passed. Ruff lint,
formatting and strict mypy passed. Regression report:
`build/spring-visual-presets-final-tests.xml`.

The native Spring Editor screenshot was visually reviewed and saved to
`build/props-review/spring-editor.png`. This change does not add a second preview
transport, a progress bar, or a separate Preview toggle.
