"""Optional evaluated onion poses, comparison frames and cached world-space motion trails."""

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject

from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class AnimationPreview(QObject):
    """Reuse evaluated visual aids without dirtying projects or moving the playhead."""

    def __init__(self, window: "MainWindow") -> None:
        """Connect optional tools and transport updates with a bounded trail cache."""
        super().__init__(window)
        self.window = window
        self._trail_source: tuple[int, bool] | None = None
        self._trail_data: tuple[tuple[tuple[float, float], ...], ...] = ()
        window.viewmodel.playback.changed.connect(self.refresh)
        window.viewmodel.animation_editor.previews_changed.connect(self.refresh)
        window.viewmodel.rig.changed.connect(self.refresh)
        window.viewmodel.mesh.changed.connect(self.refresh)

    def refresh(self) -> None:
        """Sample neighboring/comparison frames and at most 25 trail poses per source revision."""
        vm, viewport = self.window.viewmodel, self.window.viewport
        session, options = vm.playback.session, vm.animation_editor
        viewport.ghost_poses, viewport.motion_trails = (), ()
        if session is None or (vm.rig.active and not vm.rig.animating) or vm.mesh.active:
            viewport.update()
            return
        try:
            frames = [session.pose.frame - 1, session.pose.frame + 1] if options.onion else []
            if options.compare is not None:
                frames.append(options.compare)
            span = session.playback.range
            viewport.ghost_poses = tuple(
                session.evaluate(frame)
                for frame in dict.fromkeys(frames)
                if span.start <= frame <= span.end and frame != session.pose.frame
            )
            source = id(session.evaluator), options.trails
            if source != self._trail_source:
                self._trail_source = source
                self._trail_data = ()
                if options.trails:
                    poses = [
                        session.evaluate(
                            span.start + (span.end - span.start) * i / 24
                        ).for_display()
                        for i in range(25)
                    ]
                    self._trail_data = tuple(
                        tuple(
                            transform_point(
                                pose.nodes[node.id].world_matrix,
                                node.length if node.kind == "bone" else 0,
                                0,
                            )
                            for pose in poses
                        )
                        for node in session.pose.nodes.values()
                        if node.visible
                    )
            viewport.motion_trails = self._trail_data if options.trails else ()
        except ProjectError as error:
            options.error = str(error)
        viewport.update()
