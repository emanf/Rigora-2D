# Template bone visibility in the main scene

Date: 2026-10-28.

After importing a skeleton template and leaving Object Editor, bones disappeared
despite Show Bones remaining checked. The scene's artwork-only rendering flag
overrode the bone display toggle outside rig mode. Evaluated bones remained
visible in the document, so changing template data would not solve the problem.

The shared renderer now follows Show Bones independently of the artwork-only
helper setting. This also makes the toggle consistent on appearance pages.
Character and asset previews that explicitly disable Show Bones remain clean.
Bone drawing continues to expose joints temporarily while the overlay is off.
Authored visibility, opacity, rendering geometry and selection stay unchanged.

The regression imports Generic biped from the docked Templates shelf, leaves
Object Editor, and compares rendered images with the overlay on and off in both
dark and light themes. It refreshes the scene in each state and verifies that
project data and undo history do not change. It failed before the renderer fix
(`build/template-bones-before.xml`) and passes afterward.

All eight related tests pass (`build/template-bones-regressions.xml`), covering
main-scene controls, character appearance actions and drawing bones over artwork
on Parts and Skin pages with the overlay enabled and disabled. Ruff lint and
formatting and mypy pass for the modified source and test as applicable.

The compiled Windows app passes seven native checks with a real bundled template
(`build/template-bones-compiled-windows/run-1.json`), including rendered on/off
comparisons and refresh persistence in both themes. The visible armature capture
was visually reviewed. Validation uses an isolated preferences copy on a separate
Windows desktop that is never activated, without moving the user's pointer.

Compile-only output:
`dist/windows-amd64-20261028-010540-f02704/Rigora/Rigora.exe`.
Keep the entire bundle folder together. Normal example plugins are included;
the temporary validation plugin is not shipped.

Review: **9/10**. Criteria: overlay behavior and preserved authored visibility
**4/4**, scene refresh and editor interaction **3/3**, regression/platform coverage
**2/3**. Native Linux/macOS and manual foreground interaction are not tested.
