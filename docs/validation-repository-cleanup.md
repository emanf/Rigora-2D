# Repository cleanup and GitHub preparation

Reviewed on 2026-10-29. No native app build, Git initialization, commit, push,
release creation, or hosted workflow execution was performed in this task.
All desktop checks used the offscreen Qt platform and temporary preferences.

## Review: 9/10

| Criterion | Score | Evidence |
| --- | --- | --- |
| Repository hygiene | 2/2 | Generated build data, retired build environment and caches removed; source runtime retained; Git ignores expanded; no unused maintained Python imports found |
| Documentation and examples | 3/3 | Feature-focused FrameLine-style README, reviewed original-artwork screenshot, documentation index, contribution guide, complete plugin tutorial and runnable menu/toolbar/dock example |
| Release workflow design | 3/3 | Exact tagged commit, three native jobs, ZIP provenance/hashes, all-target collection, owner checks, restricted write permission, moved-tag/collision/immutable-release guards |
| Validation coverage | 1/2 | Source, archive, UI and mocked API checks pass; first hosted Linux/macOS workflow and actual remote publication remain untested |

## Cleanup

Initial inventory: `build/` held 26,006,349,757 bytes in 270,142 files;
`.venv-build/` held 1,202,486,210 bytes; `.uv-cache/` held 1,423,427,119 bytes.
Additional local npm/type/lint caches and two small distribution records were
also removed. The native filesystem free-space measurement increased by
**28,120,473,600 bytes**, approximately **28.1 GB / 26.2 GiB**.

The installed development `.venv/`, canonical assets, source, tests, plugins and
examples were retained. Private prompts and old task notes remain local and
ignored. The dependency/import audit found every declared runtime integration
still represented in source; no feature dependency was removed to shrink the
checkout. Fresh test diagnostics are small, ignored files in `build/`.

## Changes

- README follows the requested reference's screenshot/title/introduction/setup/
  features/development structure, with no emoji or routine open/save feature list.
- Documentation now has an index, contribution/cleanup guidance and a detailed
  plugin tutorial covering source/native installation, manifests, actions,
  surfaces, panels, state, Undo, reloads, hooks, presets, resources, dependencies,
  ZIP packaging and failure handling.
- The Scene Tools tutorial package is executable source, with real Object edits,
  one-step Undo and a dock that follows the active project. App-local Studio Tools
  and Rig Health Check are included automatically by future native packaging,
  while remaining disabled/untrusted by default.
- A manual GitHub workflow builds the latest stable release's tagged commit for
  Windows x64, Linux x64 and macOS arm64. Native ZIP tools retain Unix modes and
  macOS framework links. Collection requires all three SHA-256-matching packages;
  publication rechecks the frozen tag and preserves unrelated attachments.
- Application tests remain an explicit workflow/build option. Ordinary source
  development and the cleanup did not compile an executable.

## Verification

- **43 focused Python tests passed**, including actual offscreen plugin menus,
  toolbars, panels, project switches, transactional edits, disabled cleanup,
  source/native resource routing, archive provenance and failure cases.
- **Four Node tests passed** against mocked GitHub APIs: owner/rerun guards,
  release selection, immutable/moved tags, collision preflight and unrelated assets.
- Workflow YAML parsed successfully; manual trigger, three-target matrix, default
  compile-only option and publication-only write permission checked.
- Ruff lint and formatting pass; mypy passes for **216 source modules**.
- `uv lock --check --offline` passes. A temporary parser environment used only
  for YAML validation did not modify application dependencies or the lockfile.
- `Run_Rigora.bat --no-pause --headless` succeeds with an isolated profile,
  confirming cleanup preserved the source launcher environment.
- Local Markdown/image targets checked in the new/updated main guides; batch
  files retain CRLF. The README screenshot was captured from source with original
  project vectors and visually inspected.

Current raw results: `build/github-readiness-tests.xml` and
`build/release-helpers-final.xml`. Generated evidence is intentionally not committed.

The existing source-license decision and owner-supplied artwork provenance remain
unchanged. They are documented in `provenance.md`; no redistribution permission
was invented during repository preparation. A live GitHub run is needed before
claiming that all hosted native targets and upload permissions work in the owner's
repository. See `github-releases.md` for that procedure.
