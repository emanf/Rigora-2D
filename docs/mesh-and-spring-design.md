# Mesh generation, image pins and spring design

## Implemented Rigora behavior

- Bone Editor exposes Full, Mask, Grid, Density, Alignment, Expand and Affect all
  artwork layers. Grid keeps its old rectangular layout. Full uses irregular
  interior samples and a single Delaunay pass over one boundary sample set;
  combining two boundary sample patterns previously created thin corner fans.
  Twenty aspect/density combinations were checked: corners had at most two
  boundary edges and one inward edge. Mask intersects coarse triangles with
  the original alpha region and triangulates the resulting polygons with GEOS
  constrained Delaunay, retaining holes and disconnected pieces. Mask partitioning preserves source-alpha boundaries and holes.
- Alpha extraction retains every nonzero-alpha pixel, including single-pixel
  parts. Alignment adds contour samples; Expand dilates the mask in source pixels,
  clipped to the source image. No centroid-only triangle removal is used.
- Shapely 2.1.2 is pinned in the base dependencies/lockfile. Its geometry engine
  is Qt-free and supports desktop/headless use. Mask decoding uses the existing
  render extra. SVG mask rasterization never replaces original vector rendering.
- Meshing runs on an isolated scratch document in the background. A changed tab,
  changed document revision, closed editor or failed preparation prevents adoption.
  Successful adoption is one undo step. Skin stages survive and weights interpolate
  old triangles (nearest-vertex fallback outside old faces). Topology-dependent
  vertex keys/deformers require explicit replacement confirmation.
- Live subdivision preview is enabled by default and shows property changes in
  the stage without changing
  project/history. Density, Alignment and Expand have slider-and-number controls.
  Changes are coalesced at 160 ms; an older worker result cannot replace newer
  settings. Apply reuses a matching prepared result. Escape, unchecking Preview,
  hiding the editor or changing the source restores the authored view. Navigation
  remains available; authoring clicks are blocked while preview is displayed.
- Generation reports percentage progress. Alpha contours cache the two most
  recent immutable sources; skin-weight transfer queries a spatial triangle
  index instead of scanning every old triangle for every new vertex. No eager
  directory scan or source-art replacement is involved.
- Add pin enters a repeatable artwork-click tool. Object root is the default
  target, holding regions independently of skeletal posing while following whole
  Object transforms. An explicit bone target follows that bone. Clicks inverse-map
  evaluated triangles so placement and retargeting capture the displayed pose.
  Influence is `strength * max(0, 1 - distance/radius)^2`. Attachment matrices are
  prepared once per pin per evaluation, outside the vertex loop. Existing saved
  bone targets retain their behavior. Pins remain visible in Bone Editor, support
  Ctrl-selection, setup dragging, Delete and edits to target/radius/strength.
  Setup drags draw transient handles and publish once on release. Pose mode keeps
  setup read-only. Ordinary skin weights and existing vertex keys are retained;
  subdivision preserves anchors. Release pin removes selected anchors, or all
  active-artwork anchors when none are selected. These are image anchors, separate
  from bone IK constraints and animated FFD controls.
- Spring Translate uses bounded axial strain of the owned bone, preserving its
  base joint and carrying connected children and skinned artwork through evaluated
  X scale. Authored transforms stay unchanged. Rotate can be disabled independently.
  Existing Translate rules use this attachment-preserving behavior on load.
- Spring Editor provides groups, presets, Bounciness/Speed sliders, gravity,
  independent rotation/translation and asymmetric angular/distance limits.
  Physical coefficients remain accessible in a collapsible section. Apply and
  Live physics stay reachable outside the scroller. Presets immediately configure
  members or eligible selected bones; properties update assigned groups live.
  Presets are Rigora's original values.
- The composer toolbar includes reversible view-only Isolate Selection alongside
  transform targets, Attach and authored Show/Hide.

Rigora's original damped oscillator is
`q'' = omega²(target-q) - 2*zeta*omega*q' + forcing`, with `omega=2*pi*frequency`,
inertial forcing from kinematic joint acceleration and bounded 240 Hz substeps.
Speed 0–100 maps linearly to 0.5–12 Hz; Bounciness 0–100 maps inversely to damping
ratio 1.2–0.05. Advanced damping values above 1.2 remain supported, although the
simple Bounciness display saturates at zero. Rigora's screen-space gravity is
positive downwards. These mappings use Rigora's documented physical units.

