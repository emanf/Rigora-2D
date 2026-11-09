# Deformation requirements retained for Prompt 6

Owner request, 2026-10-17: support FFD (Free Form Deformation) and customized
deformation when implementing the mesh/deformation milestone. This supplements
Prompt 6; it does not start deformation work during Prompt 5.

Acceptance must include real geometry deformation from customizable lattice
controls, rather than a grid overlay alone. Preserve source artwork, serialize
settings, support undo/redo, preview results and test project round trips.

Implemented in Prompt 6: displacement-form Bernstein FFD, editable bilinear
lattices, multiple control selection, stage intensity/masks, common timeline keys,
transition interpolation and reusable geometric clips. See [the deformation
guide](deformation.md) for original algorithms, usage and tested limits.

The custom FFD follow-up adds marquee selection, group translation and eight-handle
selection resizing. SVGs render directly from their original vectors through the
deformed mesh instead of using a raster deformation texture.
