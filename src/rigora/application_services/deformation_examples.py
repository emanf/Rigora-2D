"""Original editable artwork studies demonstrating the same deformation services as the editor."""

from dataclasses import replace

from rigora.application_services.deformation import DeformationPreset
from rigora.application_services.deformation_motion import DeformationMotionService
from rigora.application_services.documents import DocumentService
from rigora.application_services.skinning import SkinService
from rigora.domain.entities import Bone, Keyframe, Skeleton, Track, Transform
from rigora.domain.project import ProjectError, SceneSettings
from rigora.resources import asset_path

EXAMPLE_STYLES = (
    "Bending",
    "Waving arm",
    "Character torso",
    "Squash and stretch",
    "Deforming prop",
)


def populate_deformation_example(document: DocumentService, style: str = "Bending") -> str:
    """Populate an empty document with embedded original art, editable geometry and real motion
    keys.
    """
    if style not in EXAMPLE_STYLES:
        raise ProjectError("Unknown deformation example style.")
    service = DeformationMotionService(document)
    if service.scene.objects or service.scene.meshes or service.scene.skeletons:
        raise ProjectError("Create an empty example document before populating artwork.")
    art = (
        "arm"
        if style in ("Bending", "Waving arm")
        else "torso"
        if style == "Character torso"
        else "prop"
    )
    with document.transaction("Create deformation study"):
        service.commit(
            "Set study canvas", settings=SceneSettings(width=800, height=600, fps=24, end_frame=72)
        )
        key = service.import_image(asset_path(f"examples/{art}.svg"), 6, 10)
        mesh = service.mesh(key)
        if style == "Waving arm":
            obj = next(o for o in service.scene.objects if o.id == mesh.object_id)
            upper = Bone(
                name="Upper arm",
                length=125,
                transform=Transform(x=obj.transform.x + 90, y=obj.transform.y + 35, rotation=90),
            )
            lower = Bone(name="Forearm", parent_id=upper.id, length=120, transform=Transform(x=125))
            service.commit(
                "Create arm bones", skeletons=(Skeleton(name="Arm study", bones=(upper, lower)),)
            )
            SkinService(document).bind(key, (upper.id, lower.id))
            stage = service.add(
                key, DeformationPreset("Soft sleeve bulge", "bulge", {"amount": 0.08})
            )
            service.key(stage, "parameters.amount", 0, 0.08)
            timeline = service.scene.timelines[0]
            wave = Track(
                name="Forearm wave",
                owner_id=lower.id,
                property_path="transform.rotation",
                keyframes=tuple(
                    Keyframe(frame=f, value=v, interpolation="bezier")
                    for f, v in ((0, 0), (18, -65), (36, -25), (54, -65), (72, 0))
                ),
            )
            service.commit(
                "Animate arm wave", timelines=(replace(timeline, tracks=(*timeline.tracks, wave)),)
            )
        else:
            kind = {
                "Bending": "bend",
                "Character torso": "ffd",
                "Squash and stretch": "squash_stretch",
                "Deforming prop": "twist",
            }[style]
            stage = service.add(key, DeformationPreset(style, kind, {}))
            path = "parameters.controls.4.0" if kind == "ffd" else "parameters.amount"
            values = (
                (0, 60, -45, 0)
                if kind in ("bend", "twist")
                else (1, 0.65, 1.3, 1)
                if kind == "squash_stretch"
                else (0, 85, -55, 0)
            )
            for frame, value in zip((0, 24, 48, 72), values, strict=True):
                service.key(stage, path, frame, value, interpolation="bezier")
            if style == "Deforming prop":
                service.add(key, DeformationPreset("Prop bulge", "bulge", {"amount": 0.2}))
        clip = service.scene.clips[0]
        service.commit("Loop study", clips=(replace(clip, name=style, loop=True, out_frame=72),))
    document.select_animation_clip(service.scene.clips[0].id)
    return key
