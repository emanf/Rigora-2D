# Canonical assets

- `fonts/material-icons/`: bundled Material Icons Outlined font, map and Apache 2.0 notice.
- `icons/app/`: single-color Rigora armature branding, light/dark transparent SVG
  marks and boxed PNG/ICO variants. See `PROVENANCE.md` there for the canonical
  source and export command; branding is separate from interface glyphs.
- `icons/controls/`: theme-aware spin arrows and menu checkmarks from Material Icons.
- `shapes/bone.svg`: owner-supplied armature silhouette and documented joint anchors.
- `characters/hands/`: owner-supplied editable white glove pairs, wrist registration
  metadata and source provenance. Their licensing is separate from generated CC0 presets.
- `examples/`: original CC0 SVG/image deformation studies and spring examples.
- `audio/`, `scripts/`, `exporters/`: local audio examples and installed integration resources.
- `images/`: application illustrations.
- `licenses/`: notices for separately licensed resources and original generated preset data.
- `motions/godot-skeleton2d/`: eight adapted numeric motion clips, their source
  URL/SHA-256 and the complete MIT animation credit/license. No character art.
- `motions/kaykit-run/`: compact CC0 run trajectories, pinned source digest and
  author notice. See its `NOTICE.md` for reproduction and retargeting details.
- `motions/kaykit-jump/`: CC0 short/long jump trajectories with source provenance
  and reproduction instructions; no source models or artwork.
- `motions/run-variants/`: CC0 KayKit alternate run and Quaternius Jog/Sprint
  trajectories with pinned provenance and author notices, used by CC run choices.

Apart from the supplied glove contours, current original SVG character, part,
prop and effect sources are generated
from authoring records in `src/rigora/infrastructure/` and the domain catalogs.
Template/Creator PNG posters and generated `.rigpack` files are disposable,
versioned user caches. First-use generation runs in a worker with progress and
cancellation. Those caches are not source artwork, deformation textures or data
that must be committed to GitHub.

The library includes 11 skeletons, 85 skeletal motions, 26 FFD motions/shapes,
20 spring profiles, 112 static SVG props/shapes and 25 layered animated Objects,
beside eight independent character templates. See
[Creative Templates](../docs/creative-templates.md) for usage and limitations.
Original generated data/art is CC0; the eight Godot-adapted motions remain MIT.
The application source has its own separate licensing status.

## Replacing the bone shape

Edit or replace `shapes/bone.svg`, then restart Rigora. Keep the template's
`viewBox="0 0 1024 1536"`, root center `(512, 1402)` and tip `(512, 170)`. Rigora maps
those anchors onto each bone's endpoints and uniformly scales/rotates the shape
while drawing or zooming, preserving both round joints. The default unselected bone
retains the SVG's original colors. Selected and custom-colored bones tint explicit `fill`, `stroke`,
`stop-color` and `color` attributes while retaining their light/dark detail; use
inline paint attributes rather than CSS styles for these paints. Invalid/missing
files log a warning and use a basic armature fallback. Shape changes affect the
editor globally and do not alter project coordinates or embedded artwork.

Viewport bones and generated rig/motion posters add display-only dark outlines
and a light outer halo traced from this SVG. Their thickness stays legible in
screen pixels while zooming. The original fill, circular joints, source file and
selection mask remain intact. Outline variants use bounded vector caches.
Editor overlays also retain source-derived tiles at twice the current display
pixel density, sharing fixed-length bones across placement and rotation. Each
viewport retains at most 128 tiles / 8 MiB; tint, length, width and DPI changes
invalidate the relevant tile. Large or externally scaled overlays draw vectors
directly. These display tiles never supply character artwork or SVG deformation.

The wheel includes this file under `rigora/assets/shapes/`; installed users edit
that packaged copy. Source users edit this canonical root folder. No runtime
access to the original Downloads file is needed. The owner supplied this SVG;
it is separate from the Material Icons and original CC0 example artwork.
