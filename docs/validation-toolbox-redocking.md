# Toolbox grip redocking

Date: 2026-10-28.

The dots handle previously accepted docking only inside a 24-pixel band next to
the canvas. That excluded the former wider tool column and much of its header.
Welcome also hid the canvas, making its coordinates unsuitable for a visible
drop target. Both Welcome and project-header regressions failed before the fix
(`build/toolbox-redock-before.xml`).

Drop targets now use the visible center workspace, with wider edge bands, the
Scene/Assets captions and the main window's outer side edges. A neutral,
input-transparent preview indicates the destination during dragging, and the
same target calculation commits the drop. The marker hides on release or when
the grip leaves a valid target. Other areas retain free floating movement.

Returning to the original side reuses Qt's saved independent dock slot. Side
changes use Qt's horizontal dock insertion rather than manually rebuilding other
panels' native layout items. Drops commit after the captured mouse event has
finished dispatching. Scene and Tools stay separate. The default left return
restores Scene → Tools → Preview; right docking occupies an independent outer
column beside Assets. This placement keeps Assets itself in its existing slot.

## Validation

- `build/toolbox-redock-final-verified.xml`: 17 passing tests for grip drops on
  Welcome and Preview headers, both adjacent captions, visible feedback, free
  movement, floating/docked persistence, independent tabs, legacy recovery,
  View controls and startup visibility.
- Ruff lint and formatting pass for the modified files; mypy passes for the
  modified Toolbox module.
- Compile-only output:
  `dist/windows-amd64-20261028-002247-f458cf/Rigora/Rigora.exe`.
- `build/toolbox-redocking-windows/run-1.json` through `run-3.json`: three
  successful compiled launches, each passing 21 native Windows checks. The first
  starts from a copy of the actual saved floating toolbox; later runs reuse the
  saved profile. Checks include both captions and headers, docking feedback,
  full-height panels, free movement, forbidden merges, legacy tab repair,
  unchanged project data and saved placement.
- All native runs use a separate Windows desktop that is never activated. The
  test plugin and preference copies stay under `build/`; real preferences are
  not modified. Example plugins remain available with normal trust requirements.

## Review and limits

**Selected working implementation: 8/10.** Criteria: grip targeting and feedback
**3/3**, independent docking **2/2**, retained placement/data **2/2**, native
validation coverage **1/3**. Several restored-layout mutation approaches failed
native checks; the selected implementation uses the working public dock insertion
path and preserves the original slot for normal return.

The native harness waits for window exposure and initial Windows placement to
settle before simulating user gestures. An additional stress run sending repeated
scripted docking operations during that initial placement still triggers a Qt
native abort; that startup timing edge case remains unresolved. No runtime delay
was added to conceal it. Normal post-startup dragging passes the native checks.
Native Linux/macOS and manual foreground interaction were not tested.

Follow-up: the Preview toolbar's excessive minimum width was subsequently fixed
with a contained scrolling row. The source Windows harness now passes its early
run without the placement-settling wait. See
[dock resizing and toolbox polish](validation-dock-resize-toolbox-polish.md)
for the reproduction, current validation and remaining platform limits.
