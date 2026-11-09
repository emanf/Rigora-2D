# Rig Health Check plugin review

Date: 2026-10-27. The plugin lives in `plugins/rig_health` and uses only the
existing SDK, standard library and desktop Qt runtime. The application source and
compiled executable do not need changes to load it.

The example provides a dockable background scanner, a static health score,
prioritized findings with scene/item identifiers, repair guidance and a JSON
clipboard report. The same analysis is a Qt-free validator for isolated jobs.
It checks collapsed authored transforms, duplicate bone names, independent roots,
unweighted unpinned vertices in enabled skins, missing/incomplete bind references
and key coverage across the union of a timeline's clips. It never repairs or
mutates project data. Notes do not lower the static score; an empty project has
no grade. Results explicitly describe their scope and become stale after edits.

Validation completed:

- Four plugin-specific tests passed, including canonical clean/risky projects,
  shared clip coverage, disabled skin stages, pinned vertices, empty projects,
  report bounds, late-error prioritization and unchanged project/undo history.
- The real source SDK subprocess returned the same report as in-process analysis.
- The actual host dock scanned in the background, copied its report, rejected
  stale results across project changes and unloaded during a pending scan.
- Seven existing plugin tests and three host GUI tests passed. These cover trust,
  dependencies, generated tools/content/deformers, isolated work and removable UI.
  The source-test helper now restricts discovery to its own explicit fixture roots,
  keeping newly shipped examples out of unrelated test expectations.
- The final external plugin returned the identical six-finding report through
  the existing frozen `RigoraCLI.exe` worker, with temporary test-only trust.
  Report: `build/rig-health-compiled-plugin.json`.
- Ruff lint and formatting passed. Visual inspection used the shared dark theme
  and custom dock chrome offscreen. No foreground application was launched.

Reports: `build/rig-health-plugin.xml`, `build/rig-health-host-gui.xml` and the
final plugin recheck `build/rig-health-plugin-final.xml`.

Distribution: `dist/rig-health-plugin-1.0.0.zip` contains exactly the manifest,
two Python files and README under one `rig_health/` directory, without caches.
A disabled copy is also in the current compiled app's `plugins/rig_health/`.
The owner's saved trust/enabled preferences were not changed. Future builds still
require copying this plugin into their new output folders; the build script does
not automatically install executable custom plugins.

Review: **9/10**. Criteria: useful diagnostics and honest scope 2/2; immutable
data and trust handling 2/2; responsive dock and lifecycle 2/2; source/frozen-worker
compatibility 2/2; platform and visual coverage 1/2. Native Windows worker and
source desktop behavior were tested. Native macOS/Linux and the dock inside the
frozen executable were not exercised. Static checks do not judge rendered poses,
artistic quality or engine export readiness.
