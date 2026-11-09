# SVG spring studies

Six original CC0 examples: Daisy, Sunflower, Berry bush, Willow, Windsock and
Mushroom. Each folder contains independent transparent SVG parts, a stationary
base and an assembled `example.svg` portrait. `studio-springs.rigpack` embeds
all sources, bones, skin bindings, named spring groups and Breeze/Strong gust
driver clips. Runtime physics produces secondary motion; the result is not baked.

In Rigora, open Spring Editor → **Open SVG spring examples…**, or search
`spring-example` in Content → Templates → Props & accessories. Apply a template,
press Play and inspect its groups in Spring Editor. Change presets/properties or
drag the driver with Live physics enabled. Bake through Secondary motion & physics
when ordinary editable keys are needed. Save a project/custom pack for variations.

Build with `python tools/build_spring_examples.py`. Native review projects are
staged under `build/spring-studies/`. Tests cover source independence, fixed bases,
connected spring roots, evaluated motion, save/open parity and preset editing.
See `docs/secondary-motion.md` for solver controls and limits.
