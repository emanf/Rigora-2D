# Binding tools and relationship inspection

Date: 2026-10-28.

## Result and review

**Review: 9/10.** Criteria: binding behavior **3/3**, endpoint/ownership/Undo
safety **3/3**, usable shared UI and canonical service integration **2/2**,
native/platform validation **1/2**. Windows source and compiled checks pass;
Linux/macOS native behavior was not exercised on this host. Animation-space
limitations are documented below rather than represented as completed rebaking.

The toolbar's Bind selection opens a modeless **Bindings** window, also reachable
from Object and Rig menus. It displays the entire scene's bone/artwork hierarchy,
skin influences, area pins, constraints and spring anchors. Sources can be a
captured multi-selection or a single explicit choice. Targets can be bones or
artwork/folders. Selected connection rows can be removed independently.

Qt-free `BindingService` composes the existing scene, image-rig and skin services.
The desktop dispatches edits through its SceneViewModel; Python/CLI/MCP expose
`bindings_inspect`, `binding_create`, `binding_remove`. Extensions resolve the
same service through `request.service("bindings")`.

Resolved findings:

- Artwork detach used to remove character membership. The Object Editor then
  lost the relationship needed to display its rig. Unbinding now preserves
  character membership, artwork folders, skeletons and bone IDs.
- Drawing reweighted all actor parts, silently undoing explicit detach choices.
  Whole-part and individual-influence exclusions now persist. Explicit manual
  Bind restores the automatic drawing policy, including the weight panel's Bind.
- Selecting a bone could expand to all of its skinned meshes. Selective unbind
  now removes only that bone's influences, normalizing the surviving weights.
  Its children retain their parent links.
- Skin and rigid attachment paths were separate. A single service now handles
  bone parenting, artwork skinning, and rigid artwork-to-bone/artwork links.
  Rebinding a folder also releases nested obsolete rigid attachments.
- Rigid targets now include other images/shapes/folders. Dependency cycles are
  rejected before publishing, with rollback of any earlier operations.
- Unbinding clears the detached bone's live spring and dependent constraints,
  spring membership and activation channels. Orphan physics is cleaned when
  its last artwork binding disappears. Other bones' bindings and shared spring
  master controls survive while still in use.
- The table captures stable row IDs before command-driven refreshes, preserves
  filtering/scroll/selection, and does not retain invalid Qt item references.
  The drawing status now distinguishes explicitly unbound artwork.

## Validation

- `build/bindings-final.xml`: **85 passed**, including all new binding tests,
  actual offscreen toolbar/dialog workflows, Object Editor isolation, shape and
  image rigging, deformation, spring activation, extension integration and Undo.
- `build/bindings-regression.xml`: **62 passed**, including rig reparenting,
  existing joint drag/drop, automation and MCP adapters.
- `build/bindings-domain.xml`: **28 passed**, covering image/character ownership
  and automatic rigging in addition to binding operations.
- The three reports contain **121 distinct passing test cases**. Repeated cases
  are counted once. The final run followed the last source changes.
- Repository Ruff lint passes; **533 files** pass format checking. Mypy passes
  across **209 source files**.
- `build/bindings-native-ui.json`: **9 passed checks** in the actual compiled
  Windows executable. The harness creates a Panda through the Character Creator's
  service, enters Object Editor, unbinds/rebinds a part through actual UI actions,
  checks bone visibility/isolation, removes a bone's spring, checks single-step
  Undo, and links/moves/unlinks two shapes. Screenshot:
  `build/bindings-native-ui.png`.
- `build/bindings-bundle-check.json`: **12 passed packaged-app checks**, including
  hashes for **2,183 assets**, native imports, SVG/PNG rendering, save/reopen,
  console companion, plugin worker, MCP, icons and offscreen desktop startup.
- Compile-only build succeeded at
  `dist/windows-amd64-20261027-204500-dda49b/Rigora/Rigora.exe`.
  Its build report correctly records that tests were not requested by the build;
  validation was run separately. Both example plugins remain available beside
  the executable and require the normal user trust/enable workflow.

All GUI/native checks used offscreen rendering. The native harness uses a test
profile inside `build/`; it does not change the owner's preferences or activate
test plugins in normal sessions.

## Boundaries

Bone parenting preserves rest geometry. Existing transform animation stays
authored in its original space. Animated artwork hierarchy moves continue to
require rebaking, with an actionable validation message. Rigid attachment removal
preserves the current world transform of unanimated artwork; it does not rebase
all existing animation clips. Authored/baked transform keys and reusable spring
group definitions are retained rather than discarded with live physics.

The inspector covers binding relationships in the current scene; character
membership, source asset ownership and outfit alternatives remain distinct
content relationships. They are deliberately not removed by ordinary Unbind.
