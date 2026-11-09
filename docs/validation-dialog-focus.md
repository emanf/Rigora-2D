# Dialog keyboard focus validation

Shared dialogs give their Cancel action initial focus and default status; Close
is the fallback when available. Buttons no longer acquire competing automatic
defaults when the window opens. The theme highlights actual keyboard focus, so
a separate default border does not make a second button appear selected.
Confirmation dialogs without Cancel retain their existing explicit default.
Native OS file dialogs are unaffected.

Enter initially cancels a Save/Discard/Cancel confirmation. Explicitly focusing
Save still makes Enter save; Escape rejects the dialog. Tests cover this real
keyboard path, the Project Settings Cancel action, click-to-save and closing by
the custom caption. The first combined run exposed Qt restoring two defaults;
disabling automatic defaults fixed it. The three focused window-chrome tests
pass in `build/dialog-focus-final.xml`; the additional explicit-focus Enter path
passes in `build/dialog-focus-keyboard.xml`. Ruff and strict mypy pass.

Review: **9/10**, based on one clear initial action, safe cancellation, preserved
keyboard activation and coverage of the shared dialog implementation. Tests use
Qt's offscreen platform and do not activate a foreground window.
