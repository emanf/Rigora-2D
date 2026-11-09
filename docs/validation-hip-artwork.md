# Fitted character hips — 2026-10-21

The 17 human templates/views use pelvis artwork fitted to their shirt waists and
actual thigh attachment points. The former generic outlined brief shape, sharp
central notch and front-facing fly in profiles made the waist look like a separate
piece of clothing. They are replaced by a smooth waist bridge and round sockets
matching the visible upper-thigh radius, including the additional shorts cloth.
Pelvis shapes have no dark outer seam. Skirts use outfit/view-specific waist,
flare, pleats and hem; Bolt has a separate mechanical center panel.

The shared original SVG generator is `tools/people_art.py`. Starter, Studio people,
juniors and reference-kids packs were rebuilt with their existing template IDs.
Rigs, controls, full-body performances and source-vector rendering are preserved.
Animals continue to use their existing body/chest designs.

Sixteen focused tests passed: circular joint/source bounds and layer order for all
23 characters, fitted pelvis-to-thigh radii, vector/source independence, existing
walking/running/standing loops, planted feet, reference gait contact, Undo and
save/open behavior. Ruff lint/format checks pass for the repository; strict mypy
passes for all 131 source modules. No new dependency or engine path was added.

All 17 revised human templates were rendered with their three actual evaluated
clips. Portraits, motion sheets and animated previews are under
`build/hip-refresh/people/`, `juniors/`, `reference/` and `starter/`.
`build/hip-refresh/waist-and-hips.png` compares standing, walk and run waist crops
for Milo, Theo and Iris from the front and side.

Refresh Templates and place a fresh instance to use the revised SVG parts.
Existing placed characters keep the artwork embedded in their saved project.
