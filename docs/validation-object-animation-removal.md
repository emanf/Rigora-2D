# Object animation removal

Validated on 2026-11-03 against the source application.

Object Editor's Motions page offers a compact Remove animation button beside New
and Duplicate. It is disabled without a selected action. The shared confirmation
dialog names the action, reports the number of linked Scene placements, and
defaults to Cancel. Cancellation leaves project data and Undo history unchanged.

`CharacterService.remove_motion` validates ownership and Object locking, removes
the source clip and its linked placement tracks atomically, and retains any
timeline referenced by another clip. It preserves artwork, bones and deformation
stages. A state-machine reference blocks removal with an actionable message.
Undo restores the entire source and its placements as one edit.

**34 focused tests passed**, including the real offscreen confirmation dialog,
Cancel, removal of the final action, disabled-button state, in-editor Undo, linked
placements, independent/shared timelines, ownership validation, state-machine
protection and save/reopen. Ruff lint/format and mypy passed. No bundle was built.

Review: **9/10** for confirmation behavior, reference integrity, atomic Undo,
ownership and preservation of the edited Object. No blocking finding remains.
