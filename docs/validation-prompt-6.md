# Prompt 6 validation — artwork, mesh editing and deformation

Windows, 2026-10-17. CPython 3.12.14, PySide6/Qt 6.12.0, pytest 9.1.1,
Ruff 0.17.1 and mypy 1.20.2. Implementation, review and testing used one agent.
No dependency or project format-version change was introduced.

## Final automated gate

`Test_Rigora.bat --no-pause` passed: **189 passed, 1 skipped** in 92.52 s.
The existing symlink test requires Windows Developer Mode or a Unix host.
Ruff lint passed, all **125 files** were formatted, and strict mypy passed
across **68 source files**. This restricted host ran pytest with normal-user
temporary-file permissions. Both root batch files retain CRLF line endings.
An AST audit found no undocumented source classes or functions.

Coverage includes:

- Source-byte preservation, PNG/JPEG decoding and bounded static SVG validation;
  worker completion ownership rejects stale imports.
- Grid generation, face/shared-edge insertion, UV interpolation, manual faces,
  duplicate/nonmanifold/collapsed/inverted/overlapping topology rejection,
  density replacement, protected regions and source-preserving undo.
- Distinct Bernstein FFD and bilinear lattice bases, neutral identities,
  intensity/masks, stage composition/order, pinned sampled positions, animated
  pins, exact overlapping pin anchors and atomic invalid-stage rollback.
- Explicit skin bind transforms including current object inverse, normalized
  bounded weights, add/subtract/smooth/normalize brushes, protected weights and
  constraints before skinning.
- Stateless vertex/control/pin/parameter sampling, key insertion/update/deletion,
  multi-control auto-key gestures, reusable clip remapping/topology checks,
  duplicate JSON rejection and nested service-command rollback.
- Five original editable studies with real animated geometry, save/reopen
  equivalence, source bytes and one-step example undo/redo.
- Actual Qt control dragging, edge/face/vertex selection, flags, weight strokes,
  key editor/transport fields, tab isolation and existing shell/rig/chrome behavior.
- Pixel-level consistency across opaque and translucent texture-triangle edges.
  CLI subprocesses reject Qt imports while evaluating torso FFD and skinned arm
  projects through the same services.

Review resolved triangle clip seams, redundant per-vertex preview evaluation,
transaction composition, unsupported-clip recovery, property/key-time retention,
stale worker results, immutable solver parameters, protected edits and safe
disabling of unknown deformers. Future animation data remains preserved.

## Native Windows and measured limits

Inspected dark/light native captures of textured torso FFD, deformation stack,
Motion inspector, control cage and a skinned waving arm. Final captures are under
ignored `build/ui-preview/0e268444-b638-4d8d-8585-21c3c3287a03/`.
All previews use isolated preferences and app-owned Qt captures.

`python tools/benchmark_deformation.py`: 1,089 vertices, 2,048 triangles,
64 FFD controls, 100 frames; compile **1.243 ms**, median evaluation
**14.365 ms**, maximum **18.816 ms** on this machine. The native waving-arm
study measured **0.473 ms** median evaluation and **4.147 ms** median viewport
painting over 100 samples. These are local CPU measurements, not general frame
rate guarantees. See [deformation limits](deformation.md).

## Distribution

`uv lock --check --offline` passed with the existing 20-package lock.
`uv build --offline` produced wheel/source archives. Archive audit confirmed
new engine/UI modules, original SVG studies and packaged Material font; the
source archive includes example projects/docs and excludes `.venv`, `.uv-cache`,
`build` and private `_project_agent_info`.

Reinstalled the wheel into isolated `build/qa-core` and `build/qa-gui` environments.
Both asserted Rigora imports/resources resolve inside the installed environment,
created all five studies, checked changed geometry, saved/reopened, exchanged
motion clips and matched shared CLI JSON. Core explicitly blocked Qt imports.
GUI borrowed only the pinned Qt runtime and verified native artwork, inspector,
frame synchronization, control edits/undo and both themes. All passed.

## Scope

Main additions are Qt-free mesh/deformation/skinning/motion services, geometry
helpers and immutable mesh poses, plus the MeshViewModel/workspace/interaction
and inspector/artwork adapters. Schemas, README, format/engine guides, original
assets, examples and benchmark tools are updated. Root launch/test scripts remain
the supported entry points. Prompt 7 has not started.
