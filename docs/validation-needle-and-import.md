# Needle bones and image import follow-up

Windows, 2026-10-17. Single-agent implementation and review; no new dependencies.
This is a Prompt 6 usability correction, not the start of Prompt 7.

## Behavior

- Bones render the owner's `assets/shapes/bone.svg`, copied byte-for-byte from
  `gray_rig_bone_reference.svg`. Uniform scaling preserves its circular root and
  tip joints; selection uses red in either theme and stored colors remain intact.
  The live preview uses the same vector asset and resizes as the pointer moves.
  Hit testing follows an SVG silhouette mask. Users may replace the file and
  restart, keeping the documented anchors. Missing/invalid files warn and fall
  back to a basic armature. No Downloads path is retained in runtime code.
- Before drawing, a circular cursor snaps to a visible editable root or tip
  within 14 screen pixels. Drawing there selects that bone as parent and starts
  the child at that exact joint (local zero for a root, local length for a tip).
  Coincident joints prefer tips; hidden/locked bones are excluded. Alt bypasses
  snapping and parenting, including when pressed during an active drag. Releasing
  Alt restores snapping. Released endpoints also snap geometrically to joints
  without altering existing bone parentage. The cursor remains visible in canvas
  margins. Idle feedback hides on leaving the viewport; cancelling or changing
  tools discards the unfinished gesture. The service converts displayed world
  coordinates through the visible parent pose, including active constraints.
  Drawing elsewhere creates a new root. V/selection exits drawing; mesh selection
  remains contextual. Entering draw mode clears the pan tool.
- The toolbar and Asset browser now expose Import artwork directly. Source
  registration remains available in Assets for storage-only workflows. Successful
  import frames the artwork; decoder/authoring failures appear in the status bar.
  Switching from rig mode into mesh import disables rig mode before refreshing
  mesh state, preserving the intended editor transition.
- `examples/image-import-example.rigora` embeds the original torso PNG, a UV mesh,
  two connected bones and a skin binding. `assets/examples/torso.png` is rendered
  from the original CC0 SVG. The example generator uses canonical Qt-free services.

## Verification

`Test_Rigora.bat --no-pause`: **201 passed, 1 existing Windows symlink skip**
in 96.85 s. Ruff lint passed, **129 files** formatted, strict mypy passed across
**69 source files**. Purpose-docstring, exact SVG copy and root batch CRLF audits passed.

New checks cover selected red pixels, live preview changes, automatic attachment
to unselected and constraint-driven parents, selection without accidental bone
creation, and real file-picker/button import of PNG/JPEG/SVG with spaces in paths.
Imports are tested while rig editing is active, with source-byte preservation and
save/reopen. The PNG example additionally verifies connected hierarchy, actual
skin deformation from a bone edit, undo and project round trips. Two additional
checks cover the SVG root silhouette, tinting, replacement and invalid-file fallback.
Joint drawing checks cover hover before a drag, cursor visibility in canvas
margins, zoom, root/tip attachment, hidden/locked joints, Ctrl transitions during
hover and dragging, undo, and released-tip alignment without reparenting targets.

Native Windows rendering/gesture inspection passed the circular idle hover,
root snapping, Ctrl override, live drawing, root attachment and dark/light themes.
Hover was delivered as a widget mouse event because QTest's native pointer move
did not arrive during idle hover on this host. App-owned captures are in ignored
`build/ui-preview/joint-snap-2f47595a96464c28892eabab25551c17/`.
All test windows use isolated preferences.

Offline wheel/sdist builds passed. Archive checks confirm that the wheel carries
the exact bone SVG and renderer, the sdist includes the SVG, and environment,
cache and build artifacts are excluded. The installed wheel passed circular hover,
root snapping, Ctrl override, live drawing and root attachment with its packaged
SVG verified byte-for-byte. Captures are in
`build/ui-preview/joint-snap-63014ae033f84505951a3052ed69e7ca/`.

Ponytail was applied to reuse existing rendering, services and file-picker paths.
Graphify repository/workspace queries returned `no_workspace`; no graph result
was available. Source callers were traced locally and verified through runtime tests.
