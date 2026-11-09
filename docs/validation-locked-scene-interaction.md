# Locked scene interaction — 2026-11-02

Viewport hover now uses the same unlocked-object picker as pointer selection.
Locked entries do not produce a forbidden cursor, block editable artwork behind
them, or expose transform handles when selected through the Scene panel. Their
Scene rows remain selectable, and the row's lock control restores ordinary
viewport picking through one undoable change.

New projects and independently added scenes initialize Main Camera as locked.
Additional cameras start unlocked. Loading a saved project retains its authored
lock state; artwork-fragment builders still create no camera.

Camera cuts remain available with a locked Main Camera: activation selects scene
output and must also deactivate locked cameras. The shared animation service
allows actual camera activation channels through the owner lock, while retaining
camera transform protection and explicit timeline track locks.

Offscreen Windows validation:

- The three initial locked-pointer regression cases failed before the hover fix
  and passed afterwards: camera, artwork, and editable artwork behind a locked part.
- Actual Scene-row clicks select locked entries. Viewport drags leave document
  data and history unchanged; actual row-lock clicks restore picking.
- Default locks, additional-camera defaults, new scenes, save/reopen, camera cuts,
  preview, presets, artwork selection and tracking passed in a 71-test regression
  run: `build/locked-camera-recheck-20261102.xml`.
- A subsequent 31-test integration run passed, including Scene-row unlocking,
  explicit cut-track protection, timeline actions, project restoration, motion
  paths and export checks:
  `build/locked-camera-integration-final-20261102.xml`.
- Ruff lint and formatting passed for 506 Python files; mypy passed for 266
  application modules. No executable rebuild was run.

Review: **9/10**, based on consistent hover/selection targeting, Scene-panel
access, transform protection, camera-cut compatibility, persistence and undo.
Native Linux/macOS interaction was not exercised. Two unrelated external-engine
execution tests were deselected from the integration run.
