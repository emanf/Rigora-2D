# Run trajectory reference

`run.json` contains 32 samples of lower-body motion derived from Kay Lousberg's
CC0 **KayKit Adventurers** `Running_A` clip. The exact source URL and SHA-256 are
included in the JSON. The author's license notice is retained in `LICENSE.txt`.

Official source: https://github.com/KayKit-Game-Assets/KayKit-Character-Pack-Adventures-1.0

Rigora projects the source ankle trajectories into a side plane, normalizes them
by leg length, and retargets them with fixed-length two-link legs. Body bounce
and foot pitch are softened for small 2D characters. Arms are authored separately
in opposition to the legs; the source's weapon-carrying arm poses are not used.
Torso lean remains restrained. This is an adaptation, not a full-body retarget.
No source meshes, textures, models, executables, or network access are needed at runtime.

To reproduce the reference, download the pinned `Knight.glb` identified in
`run.json`, then run:

```text
python tools/extract_run_reference.py path/to/Knight.glb cycles.json
```

Use `cycles.Running_A` and retain height and foot channels; omit upper-arm and
forearm channels. The converter verifies the source digest before reading it.
