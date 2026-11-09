# Example projects

`asset_pipeline_workflow.py` is the Prompt 11 headless study. With `render`
installed, run it with `--output build/my-output-study` in a fresh directory to
create transparent PNGs, a sprite atlas, runtime JSON, scene pack and editable
project while verifying original-source and geometry round trips.

`agent-workflow.json` and `automation_workflow.py` demonstrate Prompt 10's offline
Python/CLI/MCP operations: import an original SVG character, apply a rig template,
create animation and keys, render four SVG frames, validate and save a portable
project. Run `python examples/automation_workflow.py --root . --dry-run` first.
See the [automation guide](../docs/automation.md) for execution and file permissions.

`image-import-example.rigora` is a ready-to-open PNG image study with an embedded
torso image and two connected, skinned needle bones. Press **V** to select a bone
in red, **B** to draw a child from its tip, or rotate a bone in the Rig inspector
to deform the image. Its source PNG is `assets/examples/torso.png`, rendered from
the original CC0 torso SVG. Use the Asset browser's **Import artwork…** button or
Ctrl+I to add your own PNG/JPEG/static SVG; sources are preserved and framed on load.
Assets → Register project asset stores source bytes without placing geometry.

`workspace-example.rigora` is the original format 1 empty 1920 × 1080 project at
24 fps. Open it to exercise migration: Rigora keeps the original bytes untouched,
shows an upgrade message, and marks the tab dirty. Saving writes format 2 and
retains format 1 in the `.rigora.bak` predecessor.

`authoring-model.rigora` is the format 2 data-contract example. It includes an
original embedded SVG, a layer/group/object, character, two bones, triangle mesh
with weights, slot/attachment, clip, timeline/track/keys, deformer, constraint,
asset reference and inert plugin metadata. All entity IDs are repeatable UUIDs.
The hierarchy and source browser display these records. Its object translation
can now play in the transform preview. Its aim constraint evaluates; its lattice
deformer remains deferred with an explicit warning. Its SVG
artwork, mesh and attachment are stored but not rendered.

Open these files to try independent tabs, save/undo, tab reordering, Ctrl+Tab,
Ctrl+W and Save All (Ctrl+Alt+S). Save a copy when experimenting with the examples.

Prompt 6 adds five self-contained, editable artwork studies:

- `deformation-bending.rigora`: animated bend over original arm artwork.
- `deformation-waving-arm.rigora`: two-bone skinning, normalized segment weights,
  forearm wave keys and a soft sleeve bulge.
- `deformation-character-torso.rigora`: animated customizable FFD controls.
- `deformation-squash-and-stretch.rigora`: area-preserving deformation keys.
- `deformation-deforming-prop.rigora`: animated twist composed with bulge.

Choose Deform → New deformation example or Motion's example selector for unsaved
copies. Sources are original CC0 geometric illustrations in `assets/examples/`.
Project/asset IDs are created by normal services; the numerical inputs and motion
are fixed. Open, scrub, edit keys and save a copy to test the complete workflow.

The generator uses the same validated domain model and storage adapter:

```powershell
.\.venv\Scripts\python.exe examples/create_authoring_example.py
.\.venv\Scripts\python.exe examples/create_deformation_examples.py
.\.venv\Scripts\python.exe examples/create_image_import_example.py
.\.venv\Scripts\python.exe -m rigora --evaluate my-project.rigora --frame 23.5
```

The generators default to matching files under `build/examples/`. Supply a different
output path to create another copy. An existing destination requires an explicit
`--overwrite` argument; a predecessor is backed up. Source SVG bytes are original
project example artwork and are stored directly in the generator for portability.
# Release acceptance

From the source release, run `python -m tools.release_smoke --root build/smoke-new
--mcp --raster` with all intended extras installed. Use a fresh destination. This
checks the generated original character/FFD project, source preservation,
undo/redo, trusted generated plugin, actual CLI and official MCP stdio. See the
[release guide](../docs/release.md). Existing examples below remain available.

