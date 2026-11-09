# Mesh animation and live Skin preview validation

The combined regression report `build/mesh-skin-final.xml` records **142 passing
tests** across mesh authoring, deformation, subdivision, animation editing,
timeline interaction, character ownership and object workspaces. The focused
follow-up report `build/mesh-skin-tool-state.xml` records **37 passing checks**
after the final tool-state refinements.

New checks cover:

- Dense poses beyond 512 scalar channels, initial-pose seeding, interpolation,
  later edits to previously unkeyed dots, and one-command gesture Undo.
- Folded surface previews matching committed geometry while rest triangles and
  UVs remain valid; repeated sculpting, reordered stages, project save/load and
  portable motion UUID remapping.
- Default area dragging between dots, radius/falloff controls, mesh timeline
  grouping, tool toggles, and controls in a 1200-pixel-wide window.
- Pointer-aligned point and soft drags through rotated skinning, including when
  a neutral FFD stage remains selected.
- Full/Mask/Grid subdivision in Edit Mesh, background progress, stale-result
  rejection, Undo and preservation of animated appearance.
- Live color-picker poses without document/history mutations, one-step Apply,
  and Cancel restoring the original viewport appearance.

All GUI checks use `QT_QPA_PLATFORM=offscreen`; they do not show desktop windows
or take focus. The gesture validation plugin isolates only the unrelated content
poster decoder. Original scene artwork, SVG decoding, widgets and actual pointer
events remain enabled. Native desktop font rendering is outside this offscreen
validation.

Ruff lint/format checks cover 231 Python files; mypy covers 144 source modules.
No dependency or project schema-version change was required. Surface sculpting
uses a built-in displacement stage in the existing deformation stack, and keys
use the common scalar-channel timeline and evaluator.

## Mask outline and density follow-up — 2026-10-23

Bone Editor and Edit Mesh limit Density to 10 without rewriting existing mesh
geometry. Mask extraction still uses original artwork alpha. Triangulation removes
pixel stair steps within 0.7 source pixels with topology preservation, and rounded
expansion joins avoid long mitre spikes. Coverage checks include one-pixel parts,
holes, disconnected islands, subpixel outline error, overlap and valid embedding.

At Density 4, Alignment 1 and Expand 0, the bundled Willow tree changes from 807
to 542 vertices; Cumulus cloud changes from 335 to 203. These are geometry-count
comparisons, not timing measurements. Full and Grid topology are unchanged.

The combined final regression run passed 108 tests across subdivision, object
editing, bone gestures, selection/timeline, mesh/skin and Spring Editor workflows.
Report: `build/bone-mask-and-timeline-regression.xml`. Ruff lint/format checks pass
over 233 Python files; mypy passes over 145 source modules. All GUI checks ran
offscreen with isolated preferences and retained original scene rendering.
