# First animated character

Install the desktop using [installation.md](installation.md). Launch
`Run_Rigora.bat`; Welcome opens by default. Create a project with Ctrl+N.

1. In the right Content shelf, choose **Characters**. Drag **Bolt · Stick robot**
   into the stage. The translucent preview shows its position before release.
   The character includes original vector body parts, semantic bones and skinning.
2. Choose **Human walks** and drag **Natural · Walk** onto that character. The
   animation attaches to its compatible skeleton. Use Ctrl+Space to play/pause,
   or use the Timeline transport. The clip picker, frame
   scrubber and loop button are at the bottom. Drag the timeline's top grip to
   enlarge the editor; its focused Up/Down keys also resize it.
3. Select artwork in Scene or on stage. Open **Mesh / Deform** (M), add **Custom
   FFD**, and select multiple control dots with Ctrl-click or a marquee. Use the
   Scale mode and selection handles, or numeric Scale X/Y. Turn on Auto key when
   creating animated controls. Undo reverses each finished gesture. Exit mesh
   editing and Rig rest mode to preview ordinary animation.
4. Use the Timeline Dope sheet or Graph editor to edit keys. To add an original
   FFD motion, drag **Soft breathing** from the content library onto a
   compatible artwork mesh. Bone animation remains in the same clip.
5. Save with Ctrl+S to a new `.rigora` path. Close and reopen it with Ctrl+O.
   Embedded original SVGs, skin weights, FFD and animation keys remain editable.
6. Use **File → Render & export…** (Ctrl+Shift+E). Select PNG, a new destination,
   frame range and resolution, then add the job to the queue. Transparent output
   is the default. The editor remains usable while rendering. Install `render`
   first, or use SVG output without it.

To use your own art, Ctrl+I imports into Project assets. Double-click a source
to place an independent instance; repeated placement is supported. Importing a
file does not place it automatically. Select a Scene row to select its stage
element; the eye and lock columns control visibility and editing. V activates
Select. Bone posing anchors roots; Move bones explicitly translates a root or
branch. [Workspace guide](workspace-and-performance.md) explains the controls.

The camera is a border on the transparent workspace; editing outside it is
allowed. Export uses the camera dimensions. The default theme is dark; Ctrl+Shift+L
toggles light. View → Welcome reopens the closable Welcome tab. View → Restore
workspace layout restores the dock arrangement. Ctrl+Shift+P opens command search.

Next: [rigging](rigging.md), [deformation](deformation.md),
[animation editing](animation-editing.md), [content sharing](content-library.md),
[plugins](plugin-sdk.md), [Python/CLI/MCP](automation.md).

For an exact repeatable headless tutorial, run
`python examples/asset_pipeline_workflow.py --output build/my-first-output`
with render dependencies installed and a fresh destination. It produces an
editable original scene, transparent PNGs, atlas/runtime JSON and a reusable pack.
