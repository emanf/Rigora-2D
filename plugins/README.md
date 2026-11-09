# Rigora plugins

Use **Plugins → Manage plugins → Install ZIP…** to install a packaged extension
into the writable user plugin folder. Installation does not grant trust or enable
code. The source project includes API 2 Studio Tools and Rig Health Check examples
showing native menus, toolbars, editor controls, widgets and dynamic content.

Place each plugin in its own folder here, with its `rigora-plugin.json` manifest
directly inside that folder. Generated plugins place this manifest in their
inner Python package: copy that inner package, not the outer project directory.

Open **Plugins → Manage plugins** and press **Refresh**. New plugins remain
disabled until you review their code and explicitly trust and enable them.
Duplicate plugin IDs from different folders are disabled rather than silently
overriding one another. Plugins must supply their own compatible dependencies.

Rigora also discovers plugins in the user preferences directory. Use that
location when the application folder is read-only. Trust, enabled state and
diagnostic logs stay in the user profile and are not stored beside the executable.
