# Build a character (Prompt 16)

Open **Rig → Build a character**. The modeless guide edits the real project;
each automated step is undoable. Earlier steps stay accessible and the normal
stage/inspectors remain available.

1. **Artwork & parts:** import separate original PNG/SVG parts (or select existing
   artwork), rename them and choose roles. Imports are independent instances.
   Arrange parts with the normal scene transforms before fitting the rig.
2. **Skeleton:** choose Biped, Quadruped, Winged, Flexible spine or Chain. Generate
   and fit a rig to checked artwork bounds. Adjust each bone's local X/Y,
   rotation and length, or use Edit bones on stage. Parent/branch commands remain
   in the normal Rig inspector.
3. **Meshes:** generate the initial grid at the chosen resolution. Pristine guide
   geometry can be regenerated. Edited geometry, weights and deformation keys
   require the explicit replacement checkbox. All mesh vertices remain editable.
4. **Weights:** bind each part to the complete rig for automatic nearest-segment
   weights, or assign one rigid bone. Paint weights on stage opens the existing
   brush, heatmap, normalization and smoothing controls. Reopen the guide from
   Rig to resume; it retains the working project/step.
5. **Test deformation:** select a bone and scrub its angle. This evaluates actual
   skinning on a scratch document and creates no real keys. Reset preview, then
   correct placement or weights as needed.
6. **Save template:** export the current assembled scene as a `.rigpack`, with
   name, author and license. It includes the complete current scene and original
   embedded assets. Existing files require the explicit overwrite option. Install
   the pack through Content and drag its scene template into another project.

The guide does not infer semantic parts from a flattened image or generate
segmented artwork. Every automatic fit and weight is an editable starting point.
For new production work, fit rest bones before binding; subsequent animation
should use keyed poses rather than changing rest data.

Bone overlays use dark edges and a light halo so they remain visible over the
checkerboard and artwork in both themes. The borders retain a visible thickness
when zooming out; selected bones remain red. Template rig/motion cards use the
same contrast treatment. Display styling does not change bone positions, lengths,
parenting, bindings or the replaceable `assets/shapes/bone.svg` source.

Qt-free `RiggingGuideService` composes the same import, rig, mesh, skin and content
services as the rest of the editor. Tests run all five templates through import,
fit, grid generation, binding, real deformation, pack reuse, save/reopen and undo.
Desktop tests exercise the six steps and handoff/resume of weight painting.

## Binding and unbinding

Use **Object → Bindings…** or **Rig → Bindings…**, or the toolbar's **Bind
selection…** button. This modeless window shows connections across the whole scene:
bone/artwork parenting, skin influences, area pins, constraints and spring groups.
Filter by name or connection type, select several rows, and use **Unbind selected
connections** to remove just those relationships.

Choose a source and target, then **Bind**. **Use scene selection** captures multiple
selected sources. With both artwork and bones selected, the first selected bone
becomes the target and the artwork becomes the source. Bone-to-bone binding parents
within a skeleton. Artwork-to-bone binding skins the artwork to the rig; **Rigid
follow** links solid artwork to one bone instead. Artwork-to-artwork links are rigid
and preserve the source's current world transform. Targets can be images, shapes or
folders. Cycles, locked sources and invalid targets fail without partial edits.

**Unbind selection** releases artwork skinning, area pins and rigid links without
deleting bones or removing parts from their character/layer folder. On a bone,
Unbind also releases its parent relationship and removes its spring physics,
pin/IK constraints and spring activation keys. Children stay parented to the bone.
Other bones' skin influences remain, with surviving vertex weights normalized.
Releasing the last artwork link removes that bone's unused live physics; shared
physics survives while other artwork uses it. Authored/baked transform animation
and reusable spring group definitions remain. Each operation is one Undo step.

The window exposes **Auto bind artwork while drawing bones**. Parts and individual
skin influences that you explicitly unbind stay unbound during further drawing.
Use Bind to reconnect them. These choices survive saving and reopening.

Bone parenting preserves rest geometry. Moving animated artwork between layer
parents still requires rebaking its transform animation first; a validation message
explains this rather than silently changing its motion. Rigid attachment removal
preserves the current transform of unanimated artwork; existing transform keys
remain authored in their original space. Fit and parent rigs before production
animation, or rework those transform keys after changing their relationship.

Run `python -m examples.extended_character_workflow --root build/my-character-study`
from the checkout with a fresh destination to create editable `.rigora` examples,
a reusable `.rigpack` and SVG previews through the public API. The extended study
contains retargeted and baked clips plus facial keys; the guided study contains a
fitted, weighted original SVG character.
