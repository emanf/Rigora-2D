# Tween spans and contextual graphs

Date: 2026-10-18. This is an owner-requested timeline increment following the
timeline redesign; it does not start another numbered milestone.

## Implemented behavior

- The Dope sheet displays circular endpoints and connected, selectable tween
  bodies. Bodies move endpoint groups; dragging an endpoint changes duration.
  Keys stay in their lanes, cannot cross tween endpoints, and commit once on
  release. Canonical scratch evaluation previews movement without changing data.
- The separate Graph editor page and its unused widget implementation were
  removed. Double-click or Edit tween graph opens shared custom window chrome,
  24 original easing presets, editable progress dots, smooth/snap/repeat tools,
  local graph undo/redo and looping stage preview. Cancel restores the source;
  Apply commits once. A document revision, session or clip switch invalidates an
  open scratch edit.
- Presets support copy-only drag/drop onto the popup or timeline span. Their
  strokes redraw after palette changes. Final curves appear inside the span.
- Convert to tween, discrete holds, cut/copy/paste/duplicate/delete and reverse
  operate on real canonical keys. Duplicate starts after the selected channels'
  last key. Clipboard and project storage retain graph metadata.
- Auto key records scene transforms and mesh/FFD scalar changes, seeds an
  initial pose, and keeps the scene/mesh recording switches synchronized. It
  uses existing command groups for nested mesh gestures, preserving atomic undo.
  Weighted channels invert their scalar blend influence before writing keys.

The Qt-free `TransitionCurve` uses bounded normalized progress dots stored in
outgoing key metadata. The existing `CompiledTrack` applies that progress before
the same scene/mesh evaluation pipeline. Existing Bézier keys remain supported;
retiming scales their time handles, and reversing clips reverses graph metadata.
No proprietary assets or additional dependencies were added. Full control/data
limits are in [timeline.md](timeline.md).

## Verification

- `Test_Rigora.bat --no-pause`: **321 passed, 1 skipped, 6 warnings**, 285.21 s.
  Ruff lint/format and strict mypy passed (117 source modules). The skip requires
  Windows Developer Mode for symlinks. Warnings come from Qt drag test constructors.
- The previously failing grouped FFD cases were rechecked after switching the
  recorder to the existing nested `command_group` API; 40 affected service/UI
  tests passed. Final focused checks cover the last numeric/thumbnail changes
  and full-clip graph reversal.
- Five complete span/popup/recording regressions also passed with native Windows
  Qt. Captured owned windows at 1600×1000 and 1280×800, dark/light popup palettes,
  clean two-key spans and a live graph preview. No existing user window or user
  preferences were used. Final captures are under
  `build/ui-preview/tween-popup-052b1e25dbed4151a08fe01d464381bf/`.
- Logs are under `build/maintenance/tween-full-final.log`, `tween-final-focus.log`,
  `tween-last-review.log`, `tween-native-gestures.log` and `tween-native-clean.log`.
