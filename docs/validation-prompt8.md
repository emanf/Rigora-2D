# Prompt 8 validation

`Test_Rigora.bat --no-pause` passed: **232 tests passed**, one existing Windows
symlink skip, and one deprecation warning from the synthetic Qt drag-enter event
constructor used by a test. Ruff lint/format passed across 149 files; strict mypy
passed across 80 source files. The log is `build/maintenance/prompt8-full.log`.

Core checks cover all 17 original starter items, compatible semantic poses and
real numeric playback, incompatible anatomy, independent previews, pack sharing,
installation without replacement, favorites/recent persistence, new entity IDs,
skin weights and original image preservation, project round trips and atomic undo.
Malformed paths, duplicate JSON fields and duplicate item identities are rejected.
The rigging regression also covers pulling a last bone from an interior or offset
parent attachment, preserving offsets, lengths and the fixed root.

Native Windows checks passed search, worker-driven preview, rig/pose/action
application, independent motion playback, compatibility feedback, user-pack
sharing/install and internal drag/drop with undo. Preview commands run on the GUI
thread after worker-owned storage reads; the acceptance tests verify that ownership.
Dark/light captures are in ignored
`build/ui-preview/prompt8-e39939b35d7c464996e3c6ab7b342e2b/`.

Offline wheel/sdist builds passed. The installed wheel passed the same native
acceptance checks with its bundled starter collection. Installed captures are in
`build/ui-preview/prompt8-78be409b1f524741a2b49225bbd9f8ba/`.
Source purpose-docstring, batch CRLF, original SVG, wheel and source-archive
exclusion audits passed. The source project schema was regenerated for the
animation record additions. See `content-library.md` for current bounds and
explicit anatomy/retargeting behavior.
