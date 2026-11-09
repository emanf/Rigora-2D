# Video to editable rig: open-source selection

Research date: 2 November 2026. These are independent repositories, not model
variants counted as separate projects. Scores are integration-fit judgments,
not reproduced accuracy benchmarks: pose coverage (30%), drawn-character fit
(20%), editable 2D output potential (15%), local desktop deployment (20%), and
license/maintenance fit (15%). Each component is scored out of ten.

| Project / primary source | Coverage | Drawn | Editable | Desktop | License / maintenance | Weighted /10 | Decision |
|---|---:|---:|---:|---:|---:|---:|---|
| [RTMLib](https://github.com/Tau-J/rtmlib) | 9 | 8 | 8 | 9 | 9 | 8.65 | Selected inference integration; Apache-2.0, human and animal ONNX without MMCV/PyTorch |
| [MMPose / RTMPose](https://github.com/open-mmlab/mmpose) | 10 | 9 | 8 | 5 | 9 | 8.35 | Selected model family through RTMLib; full training stack is unnecessary in the editor |
| [ViTPose](https://github.com/ViTAE-Transformer/ViTPose) | 9 | 7 | 8 | 6 | 8 | 7.70 | Selected animal model, converted ONNX via RTMLib |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | 6 | 5 | 8 | 10 | 9 | 7.35 | Keep existing face/live-camera capture; lacks animal body inference |
| [DWPose](https://github.com/IDEA-Research/DWPose) | 7 | 8 | 8 | 8 | 8 | 7.70 | Strong human hands/face option; no general animal topology |
| [DeepLabCut](https://github.com/DeepLabCut/DeepLabCut) | 10 | 5 | 8 | 4 | 4 | 6.60 | Excellent animal research system; pretrained SuperAnimal weights explicitly noncommercial |
| [SLEAP](https://github.com/talmolab/sleap) | 9 | 5 | 8 | 5 | 8 | 7.10 | Strong trained multi-animal tracking; labeling/training workflow, not ready-made cartoon recovery |
| [OpenPose](https://github.com/CMU-Perceptual-Computing-Lab/openpose) | 6 | 6 | 8 | 4 | 2 | 5.30 | Noncommercial research license; native build burden |
| [AlphaPose](https://github.com/MVIG-SJTU/AlphaPose) | 7 | 6 | 8 | 4 | 2 | 5.60 | Human multi-person tracking; noncommercial license |
| [Ultralytics](https://github.com/ultralytics/ultralytics) | 7 | 6 | 8 | 9 | 5 | 7.05 | Good deployment; AGPL/enterprise choice, general animal keypoints require suitable training |
| [Detectron2](https://github.com/facebookresearch/detectron2) | 6 | 6 | 8 | 4 | 8 | 6.20 | Useful segmentation/keypoints; native dependencies and no bundled quadruped rig pipeline |
| [TAPNet / TAPIR / TAPNext](https://github.com/google-deepmind/tapnet) | 6 | 9 | 7 | 5 | 9 | 7.00 | Apache code and released checkpoints; tracks prompted points, does not identify anatomy |
| [CoTracker](https://github.com/facebookresearch/co-tracker) | 6 | 9 | 7 | 5 | 2 | 5.95 | Strong point tracking; majority CC-BY-NC, no automatic anatomical identification |
| [SAM 2](https://github.com/facebookresearch/sam2) | 4 | 9 | 6 | 4 | 9 | 6.10 | Apache checkpoints/code; segmentation helper, not skeletal recovery; large additional GPU stack |
| [VideoPose3D](https://github.com/facebookresearch/VideoPose3D) | 5 | 4 | 6 | 5 | 2 | 4.50 | Human 3D lifting, not artwork recovery; CC-BY-NC |
| [Animated Drawings](https://github.com/facebookresearch/AnimatedDrawings) | 5 | 10 | 9 | 3 | 6 | 6.45 | MIT code; archived, Python 3.8 reference stack, static drawings rather than video motion reconstruction |
| [easy_ViTPose](https://github.com/JunkyByte/easy_ViTPose) | 9 | 7 | 8 | 6 | 7 | 7.55 | Selected ONNX conversion source; prefer RTMLib to avoid its additional detector stack |

## Selection and licensing evidence

Use RTMLib 0.0.16 as the optional inference dependency. The human detector is
YOLOX-s trained on HumanArt+COCO; its upstream documentation specifically
distinguishes drawn/real human detection from COCO-only detection. RTMPose-m
produces human landmarks. YOLOX-s multiclass selects supported mammals and
ViTPose-s APT-36K recovers their landmarks. They are a combined inference
pipeline; none alone reconstructs layered animation artwork.

RTMLib and MMPose code are Apache-2.0. The
[animal ONNX publisher's model card](https://huggingface.co/JunkyByte/easy_ViTPose/blob/main/README.md)
points to the [official ViTPose Apache-2.0 model license](https://github.com/ViTAE-Transformer/ViTPose/blob/main/LICENSE).
[YOLOX](https://github.com/Megvii-BaseDetection/YOLOX) is Apache-2.0.
Code licensing is not a blanket license to training images, video examples,
or user-uploaded footage. Models remain separately downloaded local resources.
No upstream example images or videos are redistributed in the application.

The [DeepLabCut authors explicitly restrict SuperAnimal weights to research/noncommercial use](https://deeplabcut.github.io/DeepLabCut/).
[OpenPose's license](https://github.com/CMU-Perceptual-Computing-Lab/openpose/blob/master/LICENSE)
and [AlphaPose's license section](https://github.com/MVIG-SJTU/AlphaPose#license)
also restrict use. [CoTracker's majority license is CC-BY-NC](https://github.com/facebookresearch/co-tracker#license).
[TAPNet's license section](https://github.com/google-deepmind/tapnet#license-and-disclaimer)
explicitly covers released checkpoints with Apache-2.0. These differences
matter more than repository star counts for a distributable creative application.

## Scope boundaries

Detected landmarks are evidence, not an original production rig. Hidden joints,
cropped limbs, shot cuts, severe perspective, stylized proportions, bird wings,
tails without observed tips, fingers and facial blendshapes require separate
models or author correction. A single RGB clip cannot recover unseen artwork
or original replaceable clothing layers. Reference cutouts and skinned raster
art remain editable, but are not automatically clean vector layers.
