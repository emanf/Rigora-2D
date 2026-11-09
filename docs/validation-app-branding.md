# Single-color application branding — 2026-11-06

The posed armature uses one shared vector geometry. Dark UI surfaces display a
white transparent mark; light surfaces display a black transparent mark. Boxed
variants add an opposite-color rounded tile for application/window icons.

## Integration

- `IconProvider.branding()` retains four theme/style icon entries separately
  from Material interface glyphs. Transparent marks use SVG; boxed window icons
  use multi-size ICO files.
- Title bars, Welcome and About use transparent branding. Existing windows react
  to application palette changes, including direct `apply_theme()` calls.
- The application and shared window frames use matching boxed icons. The
  packaging-compatible `rigora.png` contains the new dark boxed icon. All assets
  remain in the root asset tree and are included by the existing package rules.
- See `assets/icons/app/PROVENANCE.md` for source geometry, variant names and the
  reproducible export command. No executable bundle was rebuilt.

## Verification

- Focused offscreen suite: **62 passed** across window chrome, workspace, release
  GUI, field selection, workspace layout menus and toolbox edges.
- Real source launcher: `Run_Rigora.bat --no-pause --safe-mode` with an isolated
  offscreen capture hook and separate preferences. Welcome and About were captured
  in both themes. PNG foregrounds were verified as exactly one ink, with alpha-zero
  margins and pelvis holes. Each ICO contains all eight documented sizes.
- Source launcher headless diagnostic passed.
- Repository Ruff lint passed; all nine changed Python files passed formatting.
- Strict mypy passed for all 284 source files.
- The repository-wide format check reports a pre-existing Python code-block
  formatting issue in `docs/scene-attachments.md`. That unrelated file was not edited.

## Review

**9/10:** correctness 3/3, visual consistency/transparency 3/3, integration and
simplicity 2/2, validation 1/2. Native OS shell appearance was not visually checked;
the source GUI and icon data were checked offscreen. No unresolved branding
findings remain in the reviewed integration.
