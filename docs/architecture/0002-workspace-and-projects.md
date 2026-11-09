# ADR 0002: Workspace, canonical authoring model and project packages

Accepted: 2026-10-17.

Prompt 2 supplies a professional neutral desktop shell. Prompt 3 supplies the
canonical data and mutation contracts for subsequent animation/editor milestones.
Typed frozen standard-library dataclasses keep this layer Qt-free and avoid
introducing another runtime dependency. Unknown compatible JSON is preserved
and frozen, and UUIDs identify every persistent entity.

- `domain/entities.py`, `project.py`, `validation.py`: canonical records, finite
  values, coordinate conventions, typed graph validation and JSON codecs.
- `application_services/commands.py`: immutable reversible field deltas and
  compound history entries, sharing unaffected records rather than snapshots.
- `application_services/documents.py`: independent session lifecycle, asset
  resolution/registration, transactions, dirty baseline, migration diagnostics.
- `application_services/workspace.py`: multiple document ownership, selection,
  duplicate-path reuse, reorder and guarded closure without Qt dependencies.
- `infrastructure/project_storage.py`, `migrations.py`: bounded no-extraction ZIP
  packages, explicit additive migrations, digest checks, backups and atomic saves.
- `infrastructure/preferences.py`: fault-tolerant UI preferences separate from
  project data; `RIGORA_PREFERENCES_PATH` supports explicit host/test isolation.
- `presentation/viewmodels`: Qt signals and presentation commands over services.
- `presentation/views` and `widgets`: tabbed dock workspace, canvas navigation,
  custom frame, validated dialogs and searchable actions. No animation evaluator
  or alternate model is embedded in widgets.
- `presentation/icons.py`, `themes.py`: bundled Material glyphs and complete
  neutral dark/light palettes, including Qt-generated controls and dialogs.

The hybrid source policy defaults to embedded assets for portability. Relative
external links support shared local sources but cannot escape the project root.
Moving a package to a different directory requires embedding linked sources
first. Source bytes are distinct from derived caches. Opaque plugin payloads do
not cause plugin imports or code execution.

All canonical media live in root `assets/`, force-included as `rigora/assets` in
wheels. Font conversion is a preparation step; fontTools and network access are
not runtime requirements. App branding uses an original transparent PNG.

The frameless window uses custom caption buttons and integrated application
menus. Qt system move/resize APIs delegate movement to the platform. Windows
receives native resize/maximize hit tests, the native system menu and thick-frame
style for resizing. Physical client coordinates are converted to Qt logical
units. Native checks cover styles, hit tests and standard window states;
interactive Snap and multiple-monitor behavior remain platform acceptance work.

Reference contracts: [Qt system movement](https://doc.qt.io/qt-6/qwindow.html#startSystemMove)
and [Windows snap requirements](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-snap-layout-menu).

A model can describe bones, tracks and deformation before an evaluator exists.
The shell shows stored records and counts honestly. Playback, rigging, rendering,
mesh editing, plugin execution and export remain disabled until implemented.
