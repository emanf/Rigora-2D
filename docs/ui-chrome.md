# Window chrome and Welcome workspace

The editor uses one custom caption design for the main window, project/settings
and command dialogs, file selection, messages, help/about, and floating docks.
The main caption contains branding and application menus without a secondary
Welcome/project caption. Menus share the caption surface color and are vertically
centered inside the 40-pixel title bar.

Toolbar icons use rounded state containers, 8-pixel inner padding and 4-pixel
spacing. Momentary commands show hover and pressed states; checkable navigation
and canvas actions retain their selected state. Disabled tools remain visibly
disabled. Spacing and state feedback follow the principles in the
[Material icon-button implementation guide](https://github.com/material-components/material-components-android/blob/master/docs/components/IconButton.md),
adapted for desktop density rather than claiming a full Material UI toolkit.

Native Windows maximize hit testing is retained for Snap support. Nonclient
mouse events feed the same Qt hover/pressed styling as ordinary buttons. The
Close control uses conventional red hover/pressed surfaces, in both themes.
A shared frame controller supplies native resize, state changes and caption
feedback to all application-owned windows. The OS still owns its system menu and
Snap flyout.

Dialogs embed standard Qt file/message content under custom captions. File
selection, standard button roles and cancellation remain real Qt behaviors.
Caption dismissal never grants overwrite/discard approval. Filesystem icons use
the bundled Material font instead of native OS icons. Floating panels retain
normal dragging, a redock button, close/reopen, resize and window controls.
Double-click a docked panel caption to detach it; a floating caption maximizes
and restores like the main window.

Welcome is a closable first tab with New Project, Open Project, Recent Projects
and Learn. It can close independently of project tabs and owns no document
or dirty state. Closing all tabs leaves an empty workspace. Switching to it preserves every project, command history and
canvas view. Ctrl+Tab includes Welcome. Ctrl+W closes the selected tab. View â†’ Welcome reopens the start page. Save All and canceled window closure restore whichever page
was selected. Dock visibility/layout are retained when entering and leaving
Welcome.

Validation: 101 tests passed, one Windows symlink test skipped; Ruff lint/format
and strict mypy passed. Added regressions cover Welcome navigation and pinning,
canvas/history preservation, save/close guards, real file selection/cancellation,
standard message decisions, custom dialog controls, floating panel redocking,
menu centering/background and rendered caption state colors in both themes.
Native Windows checks exercise resize and maximize hit tests, native hover/press/
release/leave, standard window states, red Close state rendering, and shared
frames across settings, file, message and floating windows. Dark/light and Welcome
captures were visually inspected. Physical mouse gestures across multiple
monitors and OS Snap flyouts remain interactive platform acceptance checks.

## About Rigora 2D

Help → About Rigora 2D opens a dedicated branded dialog with the bundled app
icon, application version, current capability summary, creator eManF, and clickable
email, GitHub repository and website contacts. Runtime details report Python,
PySide, Qt, operating system/architecture and project format versions. Icon
attribution is shown separately. Information is local; external destinations
open only when a contact link is activated.

The shared custom title bar provides window controls. Details scroll in smaller
windows while the Close button remains anchored in a separate footer. Enter
activates Close, Escape dismisses the dialog, and links support keyboard focus
and text selection. Both dark and light themes use the application palette.
