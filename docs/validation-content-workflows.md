# Workspace and reusable animation validation

Date: 2026-10-18. This increment follows Prompt 9 and addresses the owner's UI,
timeline, template, custom FFD, motion-card and spring requests. Prompt 10 was not
started. Implementation, review and verification used one agent.

- Full `Test_Rigora.bat --no-pause`: **253 passed, 1 skipped**, Ruff lint/format
  clean and mypy clean across 99 source modules. The skip is the existing Windows
  symlink permission case; the existing Qt drag-event constructor emits a
  deprecation warning.
- After the SVG placement-transform correction: **14 passed** across workspace,
  image/mesh and content GUI tests, including an assertion that actual translucent
  artwork pixels appear at the pointer.
- After adding the accessible timeline height grip: **19 passed** across workspace
  GUI and custom-window chrome checks. Mouse gestures grow the dock; normal
  floating caption controls remain functional. Ruff and mypy remained clean.
- Native Windows source and installed-package checks rendered **all 116** original
  template previews, including standalone FFD and anatomy-specific motion specimens.
  Native timeline dragging grew its height from **340 to 460 pixels**. Expanded
  timeline, custom FFD numeric controls, translucent SVG placement, content preview,
  Puppet Stage and light/dark views were captured under ignored `build/ui-preview/`.
- Installed Qt-free checks previewed every original template, evaluated spring and
  FFD motion, recorded a Puppet performance, read forked embedded sources and
  asserted that no PySide6 module was present or imported.
- Offline wheel/source builds succeeded. Archive auditing checks purpose-focused
  module/class/function documentation, exact bundled bone SVG, excluded build/cache
  directories and CRLF batch scripts.

Regression coverage includes library-only image registration, repeated placement,
scene/viewport selection, visibility/locks, live object gestures and undo,
selected-dot scaling of animated FFD channels, normalized FFD sharing/adaptation,
bone/FFD animation coexistence, fixed-root spring evaluation and deterministic
seeks, isolated card preview, one-command recording, profile sharing and stale
recording rejection.
