# Multiple scenes, Object ownership and connected bindings

Date: 2026-10-28.

DocumentService now exposes the active Scene to the shared authoring, rendering,
import, performance and export services. Add/delete use project commands; rename
uses a scene command and does not activate an inactive scene. Selection is
transient and does not dirty a project. All scenes persist in the existing
project format, without a schema migration. Switching releases the previous
animation runtime and keeps lightweight cursor state. Selection, tools, tree
state and canvas navigation are keyed by document plus scene. Only active scene
contents are built into the hierarchy; inactive scenes have headers only.

Scene-specific live editors and previews stop before a UI scene switch. Motion
Pilot, Puppet and tracking recordings also validate scene identity independently
of project revision. Queued scene-row edits and pending template drops reject
stale scene contexts. Undo of a newly added active scene releases stale runtime
state and falls back to a surviving scene. Shared source assets remain available.

Whole-Object deletion follows metadata ownership as well as transform parenting.
It removes armatures, characters, physics, helper controls, meshes, deformers,
private clips and their exclusive timelines as one Undo step. Bare and empty
Objects remain selectable and removable. Reusable imported assets are retained.

Object containment no longer appears as a removable binding. Explicit hierarchy
release inside an Object reparents artwork to its Object root with the evaluated
world pose preserved. The binding inspector partitions connected endpoints into
expandable folders; selecting a folder releases its connections atomically.
Unrelated folder disclosure and selection survive refresh. Object Editor limits
available binding sources/targets and inspected connections to its own scope.
Rigid artwork translation redirects to its enabled driver, so dragging either
endpoint moves connected artwork once. Outside drivers cannot be authored from
an isolated Object Editor. Ordinary bone/FK and skin editing remain separate.

Show scene context is an optional preview-toolbar command in Object Editor.
The paused full-scene sample is cached independently of the edited object's
scoped runtime and transformed into the editor's coordinate space. Reference
nodes draw at reduced opacity; they never enter editable poses or picking.
Disabling the command or leaving Object Editor releases its cache. The default
is off. Scene visibility/lock icons have distinct state colors, with contrasting
visible icons in the light theme.

## Validation

- `build/scenes-bindings-regressions.xml`: 67 passing regressions covering shared
  ownership, bindings, scene state, template drops, main-scene character movement
  and multiple document performance/state retention.
- `build/scenes-bindings-tools.xml`: 47 passing headless regressions covering
  bindings, scenes, deletion, springs, Puppet and camera tracking.
- `build/scenes-bindings-final.xml`: 68 passing tests covering final services,
  dialogs, project save/reopen, history and Motion Pilot scene ownership.
- `build/scenes-bindings-gui-final.xml`: 11 passing offscreen checks of actual
  scene-header clicks, grouped unbinding, body dragging, reference rendering,
  binding dialogs and all four skeleton-template drop destinations.
- Ruff lint and format pass; mypy checks all 210 source modules successfully.
- `build/scenes-bindings-compiled-headless/run-1.json`: the compiled executable
  passes six end-to-end checks using offscreen Qt and a copied profile. These
  cover template Object and empty-armature deletion, scene activation/state,
  actual bound-artwork dragging, reference rendering with rejected picks/drags,
  folder unbinding/Undo, and visibility/lock icon colors. Captured dialogs and
  reference rendering were inspected visually. The validation plugin is not
  included in the application bundle.

All pytest checks use isolated preferences and offscreen Qt. After the owner's
headless-only request, no further native Windows UI tests were launched.
The build script runs in compile-only mode; tests are separate commands.

Compile-only output:
`dist/windows-amd64-20261028-133327-3b5741/Rigora/Rigora.exe`.
The bundle includes sibling assets and the normal example plugin folders. Keep
the complete Rigora folder together. The owner profile and its plugin trust
settings were not modified by validation.

## Review

**9/10.** Criteria: ownership/binding/scene correctness **4/4**; inactive-scene
runtime and reference isolation **2/2**; Qt interaction and visual state **2/2**;
platform coverage **1/2**. Windows offscreen interactions are covered. Native
foreground mouse interaction and Linux/macOS execution remain untested.
Inactive scenes retain authored records in memory and share ordinary asset
caches; they do not run animation or physics in the background.
