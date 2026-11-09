# Rigora app branding

The current mark is a posed animation armature with tapered bones, circular
joints and a pelvis controller. `rigora-mark.svg` is its canonical vector source.
It reproduces the approved generated concept in
`../../branding/concepts/rigora-2d-icon-armature-2026-11-06.png` as clean,
single-color geometry. That concept was created with the built-in image generator;
its exact prompt is stored beside it. The production SVG was authored locally on
2026-11-06; it is not an automatically traced or generated transparent raster.

Run `.venv\Scripts\python.exe tools\export_app_icons.py` from the project root
to export all variants from the one master. This needs the existing GUI and
render extras; it does not build an executable.

| Surface/theme | Transparent mark | Boxed application icon |
| --- | --- | --- |
| Dark | `rigora-dark-mark.svg` / `.png` (white) | `rigora-dark.svg` / `.png` / `.ico` |
| Light | `rigora-light-mark.svg` / `.png` (black) | `rigora-light.svg` / `.png` / `.ico` |

Marks use exactly one ink; joint holes and all negative space are transparent.
Boxed variants add the opposite neutral tile. PNGs are 1024 × 1024 with genuine
alpha; ICO files contain 16, 20, 24, 32, 48, 64, 128 and 256 pixel sizes.
`rigora.png` is the dark boxed compatibility export consumed by desktop packaging.
The runtime theme selects boxed icons for windows and transparent SVGs for title
bars, Welcome and About, including already-open windows after a palette change.
All variants are bundled under the root `assets/` tree for offline installed use.

`generation-prompt.txt` records the previous articulated-R branding generated on
2026-10-17. Interface-control icons still use the separate Material Icons font.
