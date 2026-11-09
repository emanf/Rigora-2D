# Bundled asset compatibility review

Reviewed on 29 October 2026 against the source application. All checks ran
offscreen or through Qt-free services. No executable bundle was compiled.

The review covered all 487 entries in the 18 bundled packs: 231 ready-made
Objects and 1,085 animation clips, plus the rig, motion, pose, deformation and
standalone artwork entries. Every entry was imported and rendered through the
current application services into a contact sheet, rather than displaying its
saved thumbnail. Every clip was evaluated at its start, end and three interior
positions without evaluation warnings or nonfinite geometry.

## Corrections

- Bone edits now carry generated standing contacts through edited ancestors.
  Moving a Root or an inherited chain therefore carries the feet. Compensated
  Bone-mode edits still preserve the unselected children's world poses. Direct
  foot editing, keyed posing, standing locks and walk/run releases remain covered.
- All 42 legacy standing targets in the Bolt and studio animal templates now
  identify their owning Object. The original vectors, asset IDs, animation keys
  and content item IDs were retained. The generator writes the same ownership.
- Reusable Object extraction also follows generated contact constraints in older
  projects that lack ownership metadata, retaining their targets and rules during
  save, copy, duplication and linked-object synchronization.
- Add Track groups a character's rig roots and standing controls under its Object.
  Foot controls have an explanatory tooltip. Left and right foot bones remain
  separate channels because they must be animated independently; they are not
  separate stage Objects.
- Imported scene cameras no longer determine the artwork's drop anchor. Existing
  destination cameras are unchanged, and scene fragments retain atomic placement
  and Undo behavior.

## Coverage

| Check | Result |
| --- | --- |
| Shipped pack import and visible evaluated rendering | 487 of 487 entries |
| Complete reusable Object graph | All 231 templates retain their objects, meshes, rigs, deformers, constraints, clips and timelines |
| Original artwork decoding | 649 canonical SVG files and 1,351 canonical PNG files; all pack artwork, including 1,981 distinct packed SVG sources |
| Hidden replacement artwork | Packed clothing, hands, eyes, mouths and other variants decode without external image dependencies |
| Feet and paws | All sampled ankle connections remain within one source pixel; the largest observed gap was approximately 0.702 pixels in a reduced standing pose |
| Current creator turnarounds | 25 views across Ren, Rin, Mina, Milo and Mallow |
| Creator catalog views | 210 animal, 300 household, 32 environment and 18 vehicle views |
| Creator game loops | 15 standing/walk/run performances, 16 rendered samples each, with matching loop endpoints |
| Real desktop flow | Async template drag/drop, valid SVG renderers, Object Editor and Add Track for both Milo catalogs, Bolt and a studio animal |
| Regression checks | 131 distinct focused tests pass, including Undo, flipping, scene transforms, contact editing, linked Objects and timeline behavior |
| Static checks | Ruff lint and format checks pass; mypy passes for 216 source modules |

The timeline and placement regression tests were updated to account for the
existing Main Camera default and the deliberate hiding of camera outlines in
Object Editor. Camera transforms and authored poses remain explicitly checked.

## Repeat the review

From the repository root, with the development, GUI and render dependencies installed:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/test_bundled_asset_compatibility.py tests/test_template_tracks_gui.py tests/test_content_placement.py
.venv/Scripts/python.exe tools/review_character_creator.py --bundled
.venv/Scripts/python.exe tools/review_character_creator.py --motion
```

The bundled render report and 18 contact sheets are written to
`build/bundled-asset-review/`. Creator sheets and sampled action GIFs are written
to `build/creator-cast-review/`. These generated review files are ignored by Git.
The commands do not rewrite library packs or original artwork.

## Score and limits

**9/10**: Object ownership and replacement completeness **2.5/2.5**, source
integrity and rendering **2/2**, animation connectivity **2/2.5**, editor workflow
regressions **2/2**, and platform coverage **0.5/1**.

The remaining point reflects sampled animation coverage and Windows-only desktop
validation. This is not an exhaustive check of every interpolated frame, every
possible wardrobe combination, arbitrary user-imported content, or native macOS
and Linux window behavior. No failing checks remain in the reviewed scope.
