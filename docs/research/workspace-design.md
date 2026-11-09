# Workspace interaction design

The workspace separates authoring tools, stage, scene hierarchy, reusable content
and the full-width timeline. Stable object identities synchronize scene rows,
viewport selection, timeline discovery and editor context.

| Workflow | Implementation |
| --- | --- |
| Mesh editing | Multiple-point Move, Scale and Rotate; numeric values and resets |
| Lattice Average | Bilinear interpolation of interior points from the four corners |
| Reusable deformation | Original normalized lattice recipes with timing and intensity |
| Secondary motion | Bounded angular and axial springs, live preview and sampled keys |
| Performance cards | Data-only cards, hotkeys, scratch playback and atomic recording |
| Object state | Flip, visibility and opacity channels evaluated by the shared engine |

Native content dragging uses Qt's documented QListWidget MIME types, QDrag copy
actions and QListView movement. Tests exercise pointer initiation and delivery.
See [workspace usage and limits](../workspace-and-performance.md).
