# Spring Editor design

The editor operates on canonical dynamics groups rather than a separate preview
simulation. Named groups own member bones, an activation state and a saved spring
profile. Preset illustrations are generated from Rigora's solver.

The group tree preserves selection and expansion while values change. Physical
properties are edited through the application service and form one undoable edit.
The editor transport runs an isolated release test. Timeline activation and baking
use normal animation channels; live preview creates no authored keyframes.

See [Spring and Motion Pilot](spring-and-motion-pilot.md) for usage and
[mesh and spring design](mesh-and-spring-design.md) for physical mappings and limits.
