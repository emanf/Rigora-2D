# Asset and dependency provenance

| Material | Local evidence | Distribution status |
| --- | --- | --- |
| Material Icons Outlined font and codepoint map | `assets/fonts/material-icons/LICENSE.txt` | Apache 2.0 notice bundled |
| Rigora application logo | `assets/icons/app/provenance.md` | Original generated branding |
| Arm, torso and prop study artwork | `assets/examples/LICENSE.txt` | Original project CC0 examples |
| Original generated characters and creative presets | `assets/licenses/original-creative-presets.txt`, current infrastructure catalogs | Original CC0 SVG/data; PNG posters are local caches |
| Eight adapted Godot Skeleton2D numeric motions | `assets/motions/godot-skeleton2d/LICENSE.txt`, source URL/hash in `motions.json` | MIT, animation credited to RustyStriker/Godot contributors; no source art |
| Gray bone SVG | `assets/shapes/bone.svg`, endpoint contract in `assets/README.md` | Owner supplied; upstream redistribution permission not independently established |
| Plugin examples and generator output | `examples/plugins/README.md`, generated manifests | Original CC0 examples; third-party plugins retain their own terms |
| Application Python source | Repository metadata | No top-level source license selected |

`pyproject.toml` and `uv.lock` identify exact dependencies. Runtime wheel extras
are optional: PySide6, the official MCP SDK, Pillow/resvg-py and psd-tools. Their
installed distributions carry upstream license/notice files. The release audit
manifest reports installed versions and SPDX expressions when upstream metadata
provides them; a missing expression is not evidence of no license. Preserve and
review the actual license files for any redistributable bundle, particularly when
moving beyond pip-installed wheels to bundling Qt/native binaries.

FFmpeg is host selected, never shipped or downloaded by Rigora. Its build options
and applicable notices belong to the chosen executable. User-imported artwork,
audio, plugins and content packs are not re-licensed by embedding them in a project.
Source bytes and provenance metadata are retained where available.
