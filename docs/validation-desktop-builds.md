# Native desktop build review

Date: 2026-10-27. The default build is compile-only on every platform.
`--verify` explicitly enables static checks, application tests and an offscreen
bundle test. Default builds do not install development tools or launch Rigora.

The actual Windows launcher completed successfully with no verification flag:

```text
Build_Rigora.bat --no-pause
dist/windows-amd64-20261027-154944-8147c3/Rigora/Rigora.exe
```

Its log contains only locked dependency installation, dependency consistency and
PyInstaller packaging. `build-report.json` records `not requested (compile-only)`
for tests. The complete output folder includes the GUI executable, console peer,
native libraries, dependency metadata and 2,183 canonical assets. Generated Python
bytecode caches are excluded from the asset collection.

An earlier prototype passed offscreen runtime checks for codec imports, SVG
rasterization, asset hashes, character animation, save/reopen, PNG export, icons,
desktop startup/shutdown and console-worker routing. The official MCP client also
connected to that frozen prototype. These earlier checks do not mean the final
compile-only invocation ran application tests.

Findings resolved during implementation:

- Native dependency discovery picked up an incompatible ICU DLL from an unrelated
  application on PATH. Restricting the freezing PATH corrected Qt loading.
- Reinstalling into a previously tested environment hit Windows' locked font file
  and left an incomplete installation. Each build now owns a fresh environment;
  no active development environment or previous build needs to be replaced.
- The runtime smoke compared different selected clips before/after reopening.
  It now compares the same clip and also checks exact authored project data.
- The initial full test run exposed stale part counts, first-bone assumptions and
  a missing Motion Pilot toolbar expectation. Those checks were updated to the
  intended behavior. The installed-asset test now uses the shared asset resolver.

The broader application validation and focused rechecks produced 1,059 unique
passing cases and one skipped Windows symlink-permission case, recorded in
`build/desktop-validation.json`. That historical source snapshot precedes the
final compile-only builder adjustment. The final builder was exercised by the
successful native compile above. Build-tool Ruff lint/format checks pass.

Both Unix entry points passed Bash syntax checking and a local harness covering
paths containing spaces, forwarded options and failing exit-status propagation.
Linux and macOS native builds were not run on this Windows host. The current full
Mac dependency set requires Apple Silicon/macOS 14+; see [build requirements](desktop-builds.md).

Review: **8/10**. Criteria: successful Windows compilation and resource packaging,
isolated dependencies, correct compile-only defaults, error propagation, and native
platform coverage. The remaining deduction reflects unexecuted Linux/macOS builds
and the current dependency architecture limits.

## Public application folders and distribution cleanup

The subsequent Windows build is
`dist/windows-amd64-20261027-163601-db6c22/Rigora/Rigora.exe`.
Its root contains the two executables, `assets/`, `plugins/` and `_internal/`.
All 2,183 assets are present once, outside the runtime folder. The plugin folder
is discovered alongside the existing per-user folder, with unchanged explicit
trust and duplicate-ID protection. Preferences and other writable user data stay
in the user profile.

Installer/cache records and Matplotlib sample/documentation data were removed;
dependency licenses, runtime metadata, entry points and feature libraries remain.
The bundle has 3,582 files and occupies 577.65 MiB, compared with 3,774 files and
579.28 MiB before cleanup. Previous output folders were retained.

Validation:

- 14 focused build/resource/plugin tests passed (`build/public-bundle-folders.xml`).
- Ruff lint/format checks passed; the spec check allows PyInstaller's injected
  build globals. Strict mypy passed for all 202 application source files.
- The standard compile-only launcher passed without starting the application.
- A separate, explicit offscreen check passed (`build/public-bundle-check.json`):
  native imports, SVG rendering, all asset hashes, public data folders, console
  companion, plugin worker, MCP round trip, animated character, save/reopen, PNG
  export, Material Icons and desktop startup/shutdown. It ran from a different
  working directory with temporary preferences and no foreground windows.

Review: **9/10** for this change. Criteria: folder layout 2/2, resource integrity
2/2, plugin trust/discovery 2/2, packaged Windows behavior 2/2, native platform
coverage 1/2. Windows is validated natively; Linux/macOS path behavior is covered
by focused tests, but their native bundles still require matching hosts.
