"""Unpublished local speech previews and atomic, editable voice/mouth performance takes."""

import math

from rigora.application_services.asset_pipeline import AssetPipeline
from rigora.application_services.audio import AudioService
from rigora.application_services.documents import DocumentService
from rigora.application_services.facial import FaceService
from rigora.application_services.tracking import Channel, TrackingMapping, publish_frames
from rigora.domain.project import ProjectError
from rigora.engine.state import ScenePose
from rigora.infrastructure.live_speech import SpeechSample


class SpeechTake:
    """Own one target/revision and optional audio-reactive head/brow keys until explicitly kept."""

    def __init__(self, document: DocumentService, target: str, *, gestures: bool = False) -> None:
        """Validate the face before hardware starts and capture the current clip/playhead."""
        self.document, self.target, self.original = document, target, document.project
        self.face = FaceService(document).face(target)
        self.mapping = TrackingMapping(document, target) if gestures else None
        self.start, self.scene_id = document.animation.pose.frame, document.scene.id
        self.context = (
            document.selected_clip_id,
            document.animation_context,
            document.animation_scope,
        )
        self.frames: list[tuple[float, dict[Channel, float]]] = []
        self.last = -1.0

    def check(self) -> None:
        """Reject edits after project, scene, clip or Object Editor scope changes."""
        current = (
            self.document.selected_clip_id,
            self.document.animation_context,
            self.document.animation_scope,
        )
        if (
            self.document.project is not self.original
            or self.document.scene.id != self.scene_id
            or current != self.context
        ):
            raise ProjectError(
                "Project or animation context changed. The speech take was retained."
            )

    def preview(self, sample: SpeechSample) -> ScenePose:
        """Evaluate a scratch mouth/gesture pose; never publish keys into the source document."""
        self.check()
        scratch = self.document.fork()
        FaceService(scratch).lip_sync(self.target, ((0, sample.mouth),), start=self.start)
        if self.mapping:
            frame = self.start + sample.seconds * self.document.scene.settings.fps
            amount = min(1, sample.energy * 8)
            head = self.mapping.bones.get("head")
            owner = head.id if head else self.target
            rest = self.mapping.pose.nodes[owner].local.rotation
            values: dict[Channel, float] = {
                (owner, "transform.rotation"): rest + math.sin(sample.seconds * 5) * amount * 4
            }
            for index, brow in enumerate(self.face.get("brows", ())):
                values[brow, "transform.rotation"] = self.mapping.pose.nodes[
                    brow
                ].local.rotation + amount * (-8 if index else 8)
            if sample.seconds - self.last >= 0.1:
                if len(self.frames) >= 4999:
                    raise ProjectError(
                        "Audio-reactive gestures reached 5000 samples. Stop and keep."
                    )
                self.frames.append((round(frame, 9), values))
                self.last = sample.seconds
            publish_frames(scratch, [(self.start, values)])
        return scratch.animation.evaluate(self.start)

    def keep(self, sample: SpeechSample, voice: bytes) -> str:
        """Publish embedded voice, timed mouths and optional gestures in one undo step."""
        self.check()
        doc = self.document
        with doc.command_group("Record speech performance and voice"):
            asset = str(AssetPipeline(doc).audio_bytes("Speech performance.wav", voice)["asset_id"])
            FaceService(doc).lip_sync(self.target, sample.cues, start=self.start, audio_asset=asset)
            if self.frames:
                end = round(self.start + sample.seconds * doc.scene.settings.fps, 9)
                neutral = (
                    {
                        channel: self.mapping.pose.nodes[channel[0]].local.rotation
                        for channel in self.frames[-1][1]
                    }
                    if self.mapping
                    else {}
                )
                frames = [*self.frames]
                if end > frames[-1][0]:
                    frames.append((end, neutral))
                else:
                    frames[-1] = (end, neutral)
                for index in range(0, len(frames), 600):
                    publish_frames(doc, frames[index : index + 600])
            AudioService(doc).attach(asset, start=self.start)
        return asset
