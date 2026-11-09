"""Small cached demonstrations of actual spring presets, independent of project playback."""

from functools import lru_cache

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from rigora.application_services.dynamics import SPRING_PRESETS
from rigora.domain.entities import (
    AnimationClip,
    Bone,
    Constraint,
    Keyframe,
    Skeleton,
    Timeline,
    Track,
    Transform,
)
from rigora.domain.geometry import transform_point
from rigora.domain.project import Scene
from rigora.engine.evaluation import SceneEvaluator
from rigora.engine.springs import SpringSimulation

PRESET_HELP = {
    "Default": "Balanced follow-through; useful for general accessories and foliage.",
    "Rubbery": "Loose spring with visible overshoot; useful for antennae and floppy parts.",
    "Smooth": "Damped response that settles without much overshoot.",
    "Fast": "Quick response and short settling time for small details.",
    "Slow": "Delayed, broad follow-through for long hanging parts.",
    "Stiff": "Firm response that stays close to the driven pose.",
    "Weighted": "Gravity pulls the tip down; inertia gives it a heavier swing.",
    "Light": "Small, lively reactions with little inertia.",
    "Stretchy": "The segment can lengthen as its attachment moves.",
    "Squashy": "The segment can compress as its attachment moves.",
}


@lru_cache(maxsize=10)
def preset_frames(name: str) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Simulate the same driver twice; cache the settled second cycle at 30 FPS.

    Every example uses the production solver and the preset's real physical
    coefficients. The first cycle warms gravity/settling before the visible loop.
    """
    frequency, damping, inertia, gravity, translate = SPRING_PRESETS[name]
    root = Bone(name="Driver", length=24, transform=Transform(x=80, y=103, rotation=-90))
    tip = Bone(name="Spring tip", parent_id=root.id, length=45, transform=Transform(x=24))
    keys = ((0, 80), (5, 99), (12, 58), (20, 94), (28, 80), (72, 80))
    timeline = Timeline(
        tracks=(
            Track(
                owner_id=root.id,
                property_path="transform.x",
                keyframes=tuple(Keyframe(frame=t, value=x) for t, x in keys),
            ),
            Track(
                owner_id=root.id,
                property_path="transform.y",
                keyframes=tuple(
                    Keyframe(frame=t, value=y)
                    for t, y in ((0, 103), (5, 87), (12, 106), (20, 91), (28, 103), (72, 103))
                ),
            ),
        )
    )
    evaluator = SceneEvaluator(
        Scene(
            skeletons=(Skeleton(bones=(root, tip)),),
            timelines=(timeline,),
            clips=(AnimationClip(timeline_id=timeline.id, out_frame=72),),
        )
    )
    rule = Constraint(
        kind="spring",
        owner_id=tip.id,
        parameters={
            "frequency": frequency,
            "damping": damping,
            "inertia": inertia,
            "gravity": gravity,
            "translate": translate,
            "rotate": not translate,
            "stretch": 75 if name == "Stretchy" else 0,
            "squash": 50 if name == "Squashy" else 0,
            "clockwise": 65,
            "counterclockwise": 65,
        },
    )
    simulation = SpringSimulation()
    frames = []
    for tick in range(360):
        phase = (tick % 180) / 60 * 24
        pose = evaluator.evaluate(phase)
        nodes = simulation.advance(tuple(pose.nodes.values()), (rule,), 1 / 60)
        if tick >= 180 and tick % 2 == 0:
            a, b = nodes
            frames.append(
                (
                    a.world_matrix[4:],
                    b.world_matrix[4:],
                    transform_point(b.world_matrix, b.length, 0),
                )
            )
    return tuple(frames)


class SpringPresetPreview(QWidget):
    """Draw a neutral driver, connected segment and tip from precomputed real solver output."""

    def __init__(self, name: str) -> None:
        """Own only a frame index; the editor supplies one shared visible-only animation clock."""
        super().__init__()
        self.frames = preset_frames(name)
        self.frame = 0
        self.setFixedSize(70, 54)
        self.setAccessibleName(f"{name} spring example")
        self.setToolTip(
            PRESET_HELP[name] + " Same moving base in every example; not project animation."
        )

    def advance(self, frame: int) -> None:
        """Display the shared demonstration phase without touching a document or solver."""
        self.frame = frame % len(self.frames)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        """Keep all drawing neutral and use real connected joint positions for comparison."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 160, self.height() / 120)
        color = self.palette().color(self.foregroundRole())
        muted = self.palette().color(self.foregroundRole())
        muted.setAlpha(100)
        painter.setPen(QPen(muted, 3))
        painter.drawLine(18, 109, 142, 109)
        a, b, tip = (QPointF(*p) for p in self.frames[self.frame])
        painter.drawLine(a, b)
        path = QPainterPath(b)
        path.lineTo(tip)
        painter.setPen(QPen(color, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawPath(path)
        painter.setBrush(color)
        painter.drawEllipse(tip, 7, 7)
        painter.setBrush(self.palette().window())
        painter.drawEllipse(a, 4, 4)
        painter.end()
