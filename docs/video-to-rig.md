# Media to Rig

Use **Animation → Media to Rig** in the main Scene for local videos, single images
and image sequences. A still creates a reusable Object with an editable posed rig.
Videos and sequences also create a reusable action on the scene Animation row.
Human and quadruped body layouts are supported; original source layers are not recovered.

## Workflow

1. Choose a local MP4, MOV, MKV, AVI, WebM or M4V, or click **Choose images** for
   PNG, JPEG, WebP, BMP or TIFF. The native picker accepts one image or multiple
   explicitly selected frames. Numbered filenames sort naturally: frame1, frame2,
   frame10. No folder is scanned. Video codecs depend on the local OpenCV decoder.
2. Set start and length in seconds. The default is ten seconds at fifteen samples
   per second. Each operation accepts up to 120 seconds within the first hour of
   a source file. Process additional ranges as separate takes. For images, trim
   controls disappear and **Frames / second** controls sequence timing. Sequence
   frames must have a common working canvas; animated image files must first be
   expanded into individual images. A single image has no inferred motion.
3. Leave subject type on **Auto** to classify detected people or supported mammals.
   Subject 1 selects the largest initial detection; higher numbers select smaller
   detections. Convert multiple characters in separate passes.
4. If a drawing is missed, click **Choose subject area**, drag around it, and choose
   **Human** or **Quadruped** explicitly. The pose tracker follows an adaptive region
   without requiring the detector to recognize the drawing.
5. Click **Analyze movement**. Loading, decoding and inference run off-thread.
   The thin progress strip stays attached to the preview's lower edge. Cancel
   leaves the project unchanged. Settings cards expand independently, with one
   shared sidebar scroll surface.
6. Scrub or play the result. Pale joints meet the confidence threshold; muted red
   joints are weaker observations. Drag a joint to correct the displayed sample,
   or select its name and enter X/Y to restore a missing joint. Wheel or +/− zooms;
   middle drag pans; Fit restores the complete image. The percentage shows pixel
   magnification. Playback controls include **Show joint names** and **Previous
   frame rig**. The previous sampled pose is translucent red, never selectable
   or editable. The first frame has no previous-pose overlay.
7. Choose a useful reference pose for rest geometry and reference artwork. The
   automatic reference favors a complete connected skeleton. Lower confidence
   accepts more uncertain predictions. Smoothing reduces jitter in inferred
   points; manually corrected points remain exact anchors at every smoothing value.
   Use the single **Freeze all bone lengths** toggle beside Play in the
   preview to protect every bone together. Its pressed state and lock icon show
   when protection is active. Connected joints may move to satisfy
   the locks. These edit guards preserve each frame's existing proportions;
   they do not remove projected-length changes already tracked in other frames.
8. Choose **Rig + reference artwork** or **Rig only · No artwork** explicitly.
   Rig only creates no image, mesh or skin. For artwork, preview the cutout against
   the checkerboard before creating. Existing image transparency is preserved.
   Opaque sources use the built-in keyer with the same settings
   for preview and final art; an unchanged preview PNG is reused exactly.
9. Click **Create character** or **Create rig only**. The selected Object is ready
   to edit. Videos/sequences have editable animation; a still has rest bones and
   no invented animation clip. The entire import is one Undo step. Return to
   the main Scene before creation.

Corrections affect one sample and remain temporary until creation. Changing the
project during conversion rejects the stale result instead of overwriting edits.
Closing the window cancels its operation and rejects late publication.

## Built-in background keying

Keying runs inside Rigora with the existing image-processing dependencies.
No Blender installation, executable, setup step or external process is needed.
Rig-only and transparent-image workflows preserve their existing behavior.

**Auto** samples a common border color and selects Chroma for colored screens or
Difference for neutral backgrounds. Use the color picker or eyedropper to choose
the screen explicitly. Tolerance and Soft edge adjust the matte; Despill applies
to Chroma screens. Expand **Matte cleanup** for independent key/despill balances,
chroma blur, matte blur, grow/shrink and feather. These controls affect both the
preview and final art through one cached result.

The [source study](keying-source-review.md) records the Blender keying code read,
the independently implemented processing stages, and differences from Blender.
Keying is intended for solid screens. White-on-white and other matching foreground
colors cannot be separated by a color key. Complex backgrounds need a prepared
transparent image or author cleanup. The cutout is one raster mesh, not recovered
clothing, hidden artwork or vector layers.

## Installation and models

The selected runtime is **RTMLib 0.0.16**, CPU ONNX Runtime and OpenCV. For source
development, install the optional extra before launching:

```powershell
uv sync --locked --extra gui --extra render --extra tracking --extra speech --extra video-rig
.\Run_Rigora.bat
```

Retain any other extras your checkout uses. Run scripts do not install packages.
Installed applications obtain dependencies at build time; the model button does
not run pip or downloaded Python code.

**Install / repair models** downloads four known models on explicit request:
HumanArt+COCO YOLOX human detection, RTMPose-m human pose, YOLOX-s mammal detection
and ViTPose-s APT-36K animal pose. Each has a pinned SHA-256 checked before use.
Temporary downloads replace model files atomically; archive paths are never
extracted. Licenses ship under `assets/licenses/video-rig/` and beside the cache.

Windows cache: `%LOCALAPPDATA%\Rigora\models\video-rig-v1`. Other platforms:
`~/.cache/Rigora/models/video-rig-v1`. Analysis works offline after installation.
There are no implicit downloads during import, cloud uploads, or camera/microphone
access. The [17-project comparison](video-rig-research.md) records selection scores,
primary sources, licensing evidence and rejected alternatives.

## Editable output

Human rigs supply hips, spine, head, upper arms, forearms, thighs and shins.
Quadruped rigs supply body, head and upper/lower front/rear legs. Unreliable
reference branches are omitted, reported in the window, and retained as an
omission list in action metadata. The current models do not provide articulated
fingers, independently rotating feet/paws, bird wings or observed tail tips.

Animation uses ordinary local X/Y, rotation, projected length and visibility
keys. Length keys preserve foreshortening so child joints stay connected. Angles
are unwrapped across ±180 degrees. Decoder timestamps preserve timing at the
destination scene FPS, including fractional frames; sampling does not accumulate
rounding delay when source and sample rates differ.

Scene placement stays independent of internal motion. Moving, rotating or scaling
the Object carries artwork and displayed bones together. Its initial pivot is the
fitted video frame center and remains editable. Existing save, Undo, arrangement,
speed/repeat and export routes apply to the resulting normal animation data.

For an existing layered character, create a motion-only skeleton and use
**Animation → Retarget motion** with the Human or Quadruped profile. Review the
mapping and rest-angle offsets; unmatched controls retain their rest pose.

## Quality limits

Model confidence is not anatomical accuracy. Stylization, unusual proportions,
overlap, cropped limbs and rapid cuts need review. Auto animal classification is
validated on a natural-image reference; Rigora's cartoon dog needs a subject
region. Spatial overlap rejects distant replacement detections, but does not
recognize identity through crossing crowds or a different shot.

Gaps up to 0.25 seconds are interpolated. Longer gaps hide unreliable bone-preview
branches and retain their last usable transforms; skinned artwork can hold that
pose until tracking recovers. The budget is 3,600 poses per conversion. Decoded
frames are streamed, not retained as an atlas.

Source alpha or built-in keying produces **one raster cutout with an editable
deformation mesh**. Existing layered artwork is preferable for replaceable parts
and clean large movements. Eye/ear detection points help review, but are not
separate facial bones in the current body layouts.

Video audio, facial expressions, lip-sync and camera motion are not captured by
this body importer. Existing face/audio workflows remain separate. Arbitrary
animal topology is not presented as automatic support. Native bundle configuration
includes the optional inference libraries; no executable was rebuilt for this work.

## Shared Python, CLI and MCP operation

`media_rig_import` shares the desktop's application services. Model paths receive
the same read-root authorization as source media. API calls are synchronous;
the desktop owns the background worker. Downloads never run implicitly.

```python
from pathlib import Path
from rigora.api import RigoraAPI
from rigora.infrastructure.video_models import model_directory

workspace = Path("video-workspace").resolve()
workspace.mkdir(exist_ok=True)
models = model_directory()
api = RigoraAPI(workspace, asset_roots=(models,))
api.execute("project_create", {"name": "Recovered motion"})
result = api.execute(
    "media_rig_import",
    {
        "paths": ["walk.mp4"],
        "models": str(models),
        "profile": "Human",
        "duration": 5,
        "sample_fps": 15,
        "cutout": False,
    },
)
print(result.data["object_id"], result.data["clip_id"])
```

Guided tracking accepts `region=[left, top, right, bottom]` in normalized fractions
and requires an explicit profile. Dry runs may perform inference and validate a
scratch project but never publish. CLI/MCP expose the same typed operation through
their existing interfaces.

For stills/sequences, pass image paths in the desired order. Unlike the picker's
natural filename sort, API ordering is explicit. `sample_fps` controls sequence
timing. A single image returns empty `clip_id` and `scene_clip_id` values.
`video_rig_import(path=...)` remains a compatible single-source alias.
Artwork accepts `key_method`, `key_color=[r,g,b]` in 0–1, `key_tolerance`,
`key_softness`, `key_despill`, `key_balance`, `key_despill_balance`, `key_pre_blur`,
`key_matte_blur`, `key_grow` and `key_feather`. All keying runs in-process.

## Validation and review

The 63-test integration run covered video/still/sequence conversion, native decode,
nonmatching sample rates, subject continuity, model checksums/caching, both
topologies, displayed artwork/bone movement, archives, Undo, exact manual edits,
connected length guards, zoom/pan picking, unpickable previous-pose overlays,
shared cutout pixels, in-process color/alpha/filter/cancellation checks,
UI responsiveness, stale results, API permissions/dry runs and existing
tracking/retargeting/automation regressions. Report:
`build/media-rig-builtin-final.xml`. A final 18-test pixel/UI recheck also covers
indexed-PNG transparency: `build/media-rig-builtin-alpha-final.xml`.

Real CPU inference on original Rigora footage recovered 12 poses and 11 human
bones automatically, and 12 poses and 10 cartoon-dog bones with a selected region.
Mean joint confidence was approximately 0.868 and 0.830; these are **confidence
values, not accuracy measurements**. A separate Auto-mode video test using the
upstream YOLOX dog image created seven reliable bones and explicitly omitted
three uncertain branches. Validation media/projects remain ignored build artifacts;
upstream sample media is not distributed as application content.

Real image inference recovered 11 human bones from a transparent still, 10
quadruped bones from a guided cartoon-dog still, and three connected human poses
at 6 FPS from a selected image sequence. The still projects contain no invented
animation. The built-in keyer processes chromatic and neutral-background fixtures
with transparent backgrounds and preserved foreground colors without Blender.
Original fixtures, keyed PNGs and editable projects are recorded in
`build/video-rig-review/media-native-review.json`. These checks validate the local
pipeline, not a general anatomical-accuracy benchmark.

To reproduce native evidence, generate fixtures with `tools/review_video_rig.py`,
then run `tools/review_media_rig.py`. The real window can be rendered offscreen
with `tools/review_video_rig_window.py`; none of these tools opens a desktop window.

Review: **8.5/10** for the full reconstruction workflow. Criteria: geometry/timing
9.8 (25%), workflow/UI 9.2 (20%), background/cancellation/Undo 9.5 (20%), inference
coverage 6.5 (20%), artwork reconstruction 6.8 (15%). The separate keying/deployment
review and its criteria are in the source study. This is a working editable
body-motion importer, not universal production rig recovery. Windows is validated;
Linux/macOS dependency
resolution and packaging configuration still need native runtime validation.
