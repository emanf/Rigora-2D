# Prompt 9 validation

The public Plugin SDK milestone is complete. Prompt 10 has not been started.
Work used one agent for implementation, review and verification.

`Test_Rigora.bat --no-pause` passed on Windows with Python 3.12.14 and PySide6
6.12.0: **241 passed, 1 skipped, 1 warning** in 135.25 seconds. Ruff lint and
formatting passed across 169 files; strict mypy passed across 89 source files.
The skip is the existing Windows symlink permission case. The warning is the
existing synthetic Qt drag-enter test's deprecated event constructor.
Log: `build/maintenance/prompt9-final.log`.

SDK acceptance checks cover:

- Metadata-only discovery, exact-source trust, changed-source trust revocation,
  safe mode, dependency preflight/cycles/versions, duplicate identities and API
  mismatch before import.
- Registration rollback, reverse cleanup, bounded diagnostics and failing
  callback quarantine; failed grouped project commands restore the baseline.
- Generated viewport-tool, mesh-deformer and original content-pack examples,
  real canonical records/evaluation, undo and preserved records after disable.
- A custom numeric track sampler driving actual playback, and explicit missing
  sampler errors without discarding keys.
- Separate-process jobs, copied-project mutation isolation, hard child exit and
  timeout handling. GUI timers remain responsive while a job runs.
- Desktop explicit trust/enable/disable, pointer stamping, selected-mesh
  deformation, additional content discovery/removal, owned custom docks,
  inspectors, panel-command refresh and renderer failure containment.

The application wheel/sdist and all three independently packaged example plugins
built **offline** with the pinned backend. Installed all four wheels into
separate `build/qa-core` and `build/qa-gui` environments. The core environment
contains no PySide6: installed entry-point discovery, trust/activation, actual
bone creation and content-resource loading passed without importing Qt.

The installed GUI wheel passed a native Windows run using installed entry points
and bundled assets. Verified new plugins stay disabled until trusted, toolbar
stamping and undo history, actual deformed geometry, extended-project save/open,
offline content discovery/preview, disabled-tool removal and custom manager
controls. Dark/light screenshots were inspected in
`build/ui-preview/prompt9-0d089f43d5304a96b3b7ebdf91037ace/`.
Native log: `build/maintenance/prompt9-installed.log`.

Source purpose-docstring, original bone SVG, batch CRLF, SDK module inclusion,
starter assets, source example/documentation inclusion and wheel/sdist exclusion
audits passed. Build/cache/environment folders are excluded from archives.

API 1 supports existing numeric track value types and viewport render overlays.
It does not add video export or arbitrary serialized track-value types. Python
plugins execute trusted code in-process during registration. Optional data-job
subprocess execution separates job failure; neither manifests nor subprocesses
are an OS security sandbox. Installed package upgrades require restarting Rigora.
See [the SDK guide](plugin-sdk.md) for contracts, bounds and lifecycle guarantees.
