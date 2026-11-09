# Studio Tools · API 2 example

Enable this package in **Plugins → Manage plugins** after reviewing the code.
It integrates directly into the normal editor:

- **Rig → Studio tools → Add three-bone chain** creates actual editable bones.
- The **Studio tools** toolbar contains **Draw bone chain**. Click the stage to
  create a connected chain there. A complete chain is one undo step.
- The Object Editor's layer action strip gains the same chain command.
- The stage context menu gains the command and receives the clicked-item context.
- The Object Editor header has a live selection count.
- Character Creator gains **Studio explorer** in its preset choices and cards.
- The normal Content Library gains a **Studio templates** category with an original rig.
- A project-open hook displays a nonmodal status hint.

Disabling removes all these contributions and stops event delivery, while keeping
previously created canonical bones and characters editable. Refreshing an unchanged
package retains its running instance. This example is disabled by default and has
no external dependencies or network behavior. Original code/content: CC0-1.0.
