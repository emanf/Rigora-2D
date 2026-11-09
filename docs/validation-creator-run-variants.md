# Creator run variants, sprigs and pants outlines

Validated with the Windows source application and offscreen Qt on 2026-11-04.
No executable bundle was built, and testing did not open a visible window.

## Run choices and reference selection

Character Creation now offers seven independently retainable, repeating runs:

| Choice | Reference / treatment |
| --- | --- |
| Run | Existing KayKit Running_A adaptation, unchanged |
| Jog | Quaternius Jog_Fwd_Loop; relaxed stride and arm swing |
| Sprint | Quaternius Sprint_Loop; faster cadence, stronger stride and knee recovery |
| Run alternate | KayKit Running_B; different foot recovery and elbow motion |
| Anime run | Sprint reference with restrained forward lean and trailing arms |
| Bouncy run | Existing run reference with extra lift, body bounce and arm swing |
| Heavy run | Alternate reference with slower cadence and reduced lift/arm range |

Sources were researched through the authors' official pages:
[KayKit Character Animations](https://kaylousberg.itch.io/kaykit-character-animations)
and [Quaternius Universal Animation Library](https://quaternius.com/packs/universalanimationlibrary.html).
Both publish their applicable assets under CC0. Source-selection scores:
**9/10 for Quaternius Jog/Sprint** and **9/10 for KayKit alternate Run**,
using license clarity, distinct leg motion, retargeting suitability and reproducible
input provenance as the criteria. The Quaternius host timed out; a pinned public
mirror supplied the documented no-root-motion Standard edition and author notice.
Its claim of lossless optimization was not independently checked against the
unavailable original. The input digest and source URL are retained.

`assets/motions/run-variants/` contains 16,784 bytes of numeric JSON plus source
and license notices. No downloaded model, viewer code or third-party executable
is needed by Rigora. The offline converter validates its pinned input digest.

The new styles differ at normalized cycle times, not only through playback speed.
Each keeps editable Bezier keys, fixed limb lengths and periodic loop positions
and velocities. Faster recovery uses half-frame keys. Animal selections use
species-specific gallop/hop treatments; they do not retarget a human motion onto
animal anatomy. Newly authored animal variants also keep a fixed torso length.
The existing animal Run's flexible torso is preserved.

Creator has 19 source actions in total. New characters can retain any subset of
the run choices with the existing animation-card checkboxes. Existing placed
characters keep their saved artwork and source clips.

## Sprigs and outlines

Seven sparse vector hairstyles were added: single sprig, double sprigs, fan,
cowlick, loop, curled and zigzag sprigs. Every style has its own source geometry,
uses the head attachment and supports existing hair colors and retained alternatives.
The existing sprigs remain unchanged.

Pants now use outlined sides and hems consistent with the other garments.
Waist and knee attachments have no separating top border. Rounded knee fills
cover crossing interior strokes while preserving the outer silhouette. No new
bone, mesh or per-frame solver was introduced by the pants change.

## Verification

- Reproduction tests failed for missing Jog and unoutlined trousers before their
  implementations. The first Sprint bake also failed its trajectory tolerance;
  denser keys corrected that loss of fast knee recovery.
- **485 focused tests passed**, covering the new runs, baked trajectories,
  loop velocities, all Creator designs, sprigs, pants outlines, wardrobe
  replacement, prior shoulders/ties/jumps, template roots and the reusable library.
- **340/340 saved pose fingerprints matched** for the existing Run, Walk, Stand
  and Jump across 17 designs, five views and 49 phases.
- Ruff lint/format passed for 506 Python files, including the converter. Mypy
  passed for 272 source files.
- The production Creator window was tested offscreen with all 19 actions and
  card previews. Source contact sheets and GIFs were visually inspected.

One additional offscreen benchmark passed after cache generation finished.
It measured actual playback plus vector repaint, 48 frames per action on the
basic Creator preset:

| Run choice | Median | 95th percentile | Maximum |
| --- | ---: | ---: | ---: |
| Run | 10.61 ms | 11.12 ms | 11.36 ms |
| Jog | 10.66 ms | 11.41 ms | 11.53 ms |
| Sprint | 10.83 ms | 11.29 ms | 11.41 ms |
| Run alternate | 10.65 ms | 11.38 ms | 11.53 ms |
| Anime run | 10.67 ms | 11.19 ms | 11.48 ms |
| Bouncy run | 10.66 ms | 11.21 ms | 11.57 ms |
| Heavy run | 10.65 ms | 11.16 ms | 11.84 ms |

These are host-specific observations, not a speedup claim against earlier runs
or a frame-time guarantee for every character and outfit. Evidence is retained
in `build/run-variants-review/` and
`build/creator-review/run-variant-playback.json`.

Artwork cache revision 26 was generated successfully through 562 preparation
steps. Temporary reference downloads, test data and the superseded cache were
removed after validation; custom content was preserved.

Self-review: **9/10**, using distinct movement, editable loops, limb/part
attachment, visible pants contours, fitted sprig silhouettes, provenance and
measured Creator playback as the criteria. Style labels describe animation
treatments, not motion-capture realism or owner aesthetic approval.
