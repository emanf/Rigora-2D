# Project-local linked Objects

## Use saved Objects

**Assets → Objects** contains project-local reusable definitions. Double-click a
card, or choose **Edit** from its right-click menu, to open its contents in Object
Editor. This works even after its last scene placement has been deleted. Editing
does not add a new placement. The temporary Object tab publishes completed edits
to the owning project and its linked copies; **Scene** returns to that project.
Save from the Object tab saves its owning project.

To place a copy, drag the card onto the viewport or choose **Add to Scene**. Each
placement keeps its own transform, visibility, opacity, lock and Depth (Z), while
artwork, parts, rig, clothing, skins and source actions remain shared. Object cards
render the complete saved composition, including its current default colors and
visible parts. Source edits refresh the poster in the background; stale worker
results cannot replace a newer revision. Rig-only Objects show their bones.

The first four right-click commands are **Edit**, **Add to Scene**, **Remove…** and
**Remove All Related Objects in Scene…**. Both removal commands ask for
confirmation. Remove deletes the saved definition while leaving placed copies
detached. Remove All Related Objects deletes its placements in the current scene,
keeping the definition and other scenes. Both operations support Undo.

## Exchange Objects and save Custom Templates

1. Select one or more cards in **Assets → Objects**.
2. Choose **Export Object Package…** to write a portable `.rigpack`, or
   **Save to Custom Templates…** to keep it in the shared local content library.
3. Enter its name, author and license. Choose a category or type a new category.
   Custom Templates appear under **Assets → Content → Custom** across projects.
4. In another project, choose **Import Object Package…** from the Objects menu.
   The definitions and referenced source files are imported into Objects without
   placing anything in the scene. Drag a card or choose Add to Scene when ready.

Packages include referenced original artwork, rigs, bindings, appearance choices,
clothing and source animations. Unrelated project scenes and assets are excluded.
Reuse allocates new entity identities and creates project-local links; installed
Custom Templates are saved snapshots, so editing one project does not overwrite
another project's contents or the installed template. To share a package through
Content, use the existing **Install pack** command.

In **Content → Templates** and **Content → Custom**, right-click a standalone
character, artwork or rig for **Add to Objects** or **Add to Scene**. Double-click
adds it directly to the main Scene and keeps Scene editing active. Poses, motions
and deformation presets require an existing compatible target; their preview/apply
workflow remains available in the content browser.

## Storage and services

`ObjectLibraryService` is the Qt-free application service used by the desktop,
Python API and CLI. `Project.extra.object_library` stores each definition's name,
canonical root identity and serialized scene ownership fragment. Source bytes stay
in the ordinary project assets. A placement's `extra.linked_object` maps canonical
entity identities to its unique scene identities. Preset IDs in opaque metadata
remain shared; references to actual parts, tracks, vertices and bones are remapped.
This is additive optional project data and survives the standard package codec.

`DocumentService` publishes new definitions and synchronizes edited contents at the
outermost command/transaction boundary. The original command and synchronization
patch form one Undo entry. Failed synchronization rolls back the transaction.
Definitions survive placement deletion. Explicit removal detaches placements and
marks them as excluded from automatic publication until Save as Object is used.
Source removal checks saved definition references as well as live scene references.
Content-pack imports start new project-local definitions rather than inheriting
links into their origin project.

Only changed scene revisions are inspected. Immutable content comparisons exclude
placement transform, visibility, opacity, lock and root Depth (Z) fields. Scratch preview documents
skip publication. Inactive scenes are updated as immutable data; the synchronizer
does not compile, advance or retain an animation runtime for them. Internally
validated immutable metadata can be reused across revisions, while external JSON
and mapping inputs are still copied, validated and deeply frozen.

The root's `pivot_edited` marker is also placement-specific. Moving a Scene pivot
does not publish that marker into the definition or change the pivot fallback used
by linked copies. Pivot edits preserve the evaluated matrix and use only the active
workspace's action timelines when checking whether key compensation is needed.

Rig-only Objects record a stable `Skeleton.extra.library_bind` matrix, allowing the
same authored bone coordinates and action keys to follow different root placements.
Evaluation applies this placement once, after constraints/dynamics. Object Editor
uses the corresponding bind space; whole-object transforms do not additionally
rewrite these bones. Existing skinned Object deformation keeps its existing mapping
and takes precedence if artwork is later bound. Shared action synchronization reuses
the same motion-window update function as ordinary timeline edits.

Clipboard payloads use `application/x-rigora-authoring-clipboard`, bounded to 32 MiB
in the desktop. All record IDs are regenerated for paste, including nested records,
weight-map keys and reference-bearing metadata. Definition mapping keys retain
their canonical identities while mapping values receive the new placement IDs.
Paste validates the resulting project graph before publication. Saved definitions
also validate their root and references before being added. Clipboard payloads
reference the original project; cross-project sources are exchanged with packs.

The additive API operations are `object_library_list`, `object_library_save`,
`object_library_place`, `authoring_copy`, `authoring_paste`, `scene_create`,
`scene_select` and `scene_delete`. They are available through `RigoraAPI.execute`
and the ordinary operation discovery/CLI routes. Clipboard operations here return
or accept JSON data and do not depend on a desktop clipboard.

```python
saved = api.execute("object_library_save", {"object_ids": [object_id]}).data
definition = saved["definition_ids"][0]
scene = api.execute("scene_create", {"name": "Next scene"}).data["scene_id"]
api.execute("scene_select", {"scene_id": scene})
api.execute("object_library_place", {"definition_id": definition, "x": 300, "y": 200})
payload = api.execute("authoring_copy", {"scene_id": scene}).data
api.execute("authoring_paste", {"payload": payload})
```
