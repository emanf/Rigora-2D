# Rigora 2D project instructions

## Durable collaboration workflow

Performance is the highest product priority. Keep editing, playback, previews,
and asset browsing smooth. Profile interactive hot paths, avoid redundant work
and blocking operations, and verify representative frame times when changing
rendering or interaction code. Preserve correctness and visual quality while
optimizing; do not present unmeasured performance claims as verified results.

When a requested interaction would replace a common application convention,
explain that convention and ask the owner before changing it. An explicit
choice already made by the owner is sufficient authorization.

Use a single agent by default for all project work. The owner changed this
preference to reduce token usage. Do not spawn subagents unless the owner
explicitly requests them again. Implement, review, and test changes in the
current chat, resolving findings before reporting completion.

If the owner requests two agents again, use one implementation owner and an
independent reviewer. They must exchange findings, fixes, and recheck results
directly rather than routing every exchange through a coordinator.

Graphify is disabled by the owner. Use local source navigation and dependency/
impact checks; do not call Graphify unless the owner explicitly re-enables it.

Use the source application through `Run_Rigora.bat` for development. Do not
compile or rebuild executable bundles unless the owner explicitly requests it.
Before every requested rebuild, remove previous generated desktop build environments
and distribution output to reclaim disk space. Use the shared build driver's
bounded cleanup; preserve source, assets, projects, plugins and the development
environment. Do not retain old bundles alongside the new one. Remove disposable
compilation intermediates after a successful build as well.
Run automated GUI tests offscreen so they cannot take focus from other apps.

For optional questions, allow up to five minutes for a reply, then choose the
best reasonable default and continue independent work. Silence is not approval
for actions that require explicit permission.

Every review must include a numeric score and its criteria. If a review or
candidate-selection loop exceeds eight attempts, choose the highest-scoring
working option, report remaining limitations, and continue. Do not represent
broken behavior or failed validation as complete. This applies to multi-agent
work when separately authorized; it does not enable additional agents.

## Visual and asset requirements

- Default to a genuinely dark neutral palette: black, dark gray, light gray,
  and white. Avoid colored surfaces and gradients; use standard red hover/press
  feedback on window close buttons.
- Show transparency across the whole viewport, with the camera indicated only
  by a border. Keep scene geometry visible and editable outside that border;
  grid/checkerboard toggles apply to the whole workspace.
- Use shared custom title bars for the main window, dialogs, and floating panels,
  with normal controls, movement/resizing, and visible hover/press feedback.
- Keep a visible neutral outline around custom windows and dialogs. Numeric
  step arrows stay inside the field border, with no separate idle background
  or overlap with the value or right edge.
- Use native OS file pickers for open, save, and multi-asset selection on all
  platforms. File pickers are the exception to shared custom title bars; thumbnail
  previews belong to the OS, not an eager application directory scan.
- Open Welcome by default; allow closing it and reopening it from View → Welcome.
- Use bundled Material Icons for interface controls. The original Rigora app
  logo is a separate branding asset.
- Character Creation hands use only the owner's paired vectors from Untitled.svg,
  packaged in `assets/characters/hands/cartoon-gloves.svg`. Use each adjacent
  left/right partner, white fills by default and fixed wrist registration.
  Preserve all supplied path geometry and surface details. Apply only palette,
  registration, view and animation transforms. Do not draw substitute hand
  shapes, add wrist patches, remove creases or synthesize back-of-hand fills.
  Front-view Open, Fist, Point and Thumbs out use the viewer-left source for both
  limbs, with the viewer-right hand horizontally reflected about its own wrist.
  Back view reverses the source: use the viewer-right artwork on both limbs,
  with a horizontally reflected copy on the viewer-left wrist.
  Front 3/4 Loose fist and Curled fist reflect the viewer-right supplied hand at
  its own wrist; Fist uses its unreflected right source. Retain the original
  viewer-left partner.
- Use the tapered gray armature with circles at both joints. Selection uses red,
  and drawing previews resize live. The circular drawing cursor snaps to editable
  roots and tips; drawing there attaches a child. Alt bypasses snapping and
  parenting for free placement. Drawing elsewhere starts an independent root.
- Keep canonical images, fonts, and icons in root `assets/`; package them for
  installed use. Never depend on the owner's Downloads folder at runtime.
- Use the owner-supplied `assets/shapes/bone.svg` for bone silhouettes and live
  previews. Keep it replaceable, preserve its round joints and documented endpoint
  anchors, and use its silhouette for selection. See `assets/README.md`.
- Selection uses grouped Bone / Chain (FK) / Rig / IK toggles beside Grid.
  Chain (FK) is the default: selected bones carry their descendants. Bone mode
  preserves unselected world poses; Rig affects the selected connected rigs;
  IK pulls ancestor chains with roots anchored. Ctrl-click toggles selection.
  Chain body drags rotate each selected joint by the same local angle delta;
  unselected descendants inherit motion. Bone body drags translate.
  Joint alignment snaps within 14 screen
  pixels; Alt bypasses alignment without changing parenting.
  Single-bone rotation and scale pivot at its base joint. The selected tip is a
  direct rotation handle, even at an overlapping child joint. Hover and drag
  cursors must match move, rotate, directional resize, marquee and pan actions.
  Show options relevant to the current tool beside Grid.
  Connected joints default to a 30-degree minimum interior angle; allow editing
  selected joints relative to their direct parents, including zero to disable.
  Use one selection tool with move, rotate and scale handles.
  Show evaluated geometry during drags and commit one undo step on
  release. Support marquee selection of bones and custom FFD dots, with group
  movement and resize handles for FFD selections.
- Render SVG deformation from original vectors at the current output resolution,
  preserving sharpness. Raster thumbnails must not become SVG deformation textures.

## Milestone scope and architecture

Document modules, classes, and functions with useful purpose-focused docstrings.
Explain inputs, results, ownership, and side effects where relevant. Inline
comments should clarify non-obvious behavior or design constraints. Never use
code comments to narrate user requests, conversation history, or edits made.

Read `_project_agent_info/RIGORA 2D — MASTER PROJECT BRIEF FOR CODEX.txt` and the
currently requested numbered prompt before implementing a milestone. Treat the
numbered prompts as sequential increments. Preserve working architecture and
previous decisions, test the current increment, and wait for the owner's next
prompt before starting the next milestone. Do not present placeholders as
implemented animation features.

For Prompt 6, FFD (Free Form Deformation) and customized deformation are explicit
owner requirements. Read `docs/deformation-requirements.md` before that milestone;
the referenced product page is workflow inspiration, not code or asset permission.

Use Python and PySide6 with MVVM. Keep domain and engine code Qt-free. GUI, CLI,
Python API, and later MCP integrations must use the same application services.
Keep local operation offline after dependency installation. See `README.md` and
`docs/architecture/0001-foundation.md` for the actual current foundation.

## Current validation commands

After `uv sync --locked --extra gui`, Windows users can double-click
`Run_Rigora.bat` to launch the application or `Test_Rigora.bat` to run pytest,
Ruff lint/format checks, and mypy. Use a first `--no-pause` argument for automated
invocation. The scripts use the existing local environment and never install
dependencies. See the README/development guide for individual commands and
host-specific temporary-directory permissions.
Preserve CRLF line endings in `.bat` files; `.gitattributes` also declares that
checkout rule so Windows CMD can reliably resolve every batch label.
