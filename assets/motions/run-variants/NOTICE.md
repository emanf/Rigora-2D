# Additional run references

These are numeric motion adaptations, without source meshes, textures or code.
`variants.json` retains 32 samples per cycle and records each author's name,
CC0 license, source URL and SHA-256. Rigora supplies proportion-aware leg IK,
softened motion, independent arm choreography and selected style treatments.
The authored Anime/Bouncy/Heavy treatments are not claimed as original source
animation clips. All sampling and playback work offline.

## Sources

- Kay Lousberg: `Running_B` from the pinned KayKit Adventurers `Knight.glb`.
  See the neighboring `kaykit-run/NOTICE.md` for the exact source revision.
- Quaternius: `Jog_Fwd_Loop` and `Sprint_Loop` from the free Standard edition of
  [Universal Animation Library](https://quaternius.com/packs/universalanimationlibrary.html).
  The author's download host was unavailable during retrieval. The public mirror
  URL is pinned in each record. Its publisher describes this no-root-motion
  edition as losslessly resampled; it was not compared against the unavailable
  original download. The complete author notice is preserved as
  `LICENSE-QUATERNIUS.txt`.

Pinned mirror input SHA-256:
`4c748767741a3e495d89667b9a218b690ba9810b9517a12e960780e3ca72c4e9`

## Reproduction

Download only the pinned input named in the JSON. Run:

```text
python tools/extract_run_reference.py Knight.glb kaykit-cycles.json
python tools/extract_run_reference.py UAL.glb ual-cycles.json --quaternius
```

Retain `Running_B`, `Jog_Fwd_Loop` and `Sprint_Loop`. Copy their height and
foot channels into `variants.json`, together with source and license metadata.
The converter checks the input digest. No input models are bundled with Rigora.
