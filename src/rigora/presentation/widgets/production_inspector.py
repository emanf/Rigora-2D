"""Low-cadence performance counters and background, navigable project diagnostics."""

from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.diagnostics import Diagnostic, inspect_project
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class ProductionInspector(CustomDialog):
    """Inspect costs without adding per-frame UI rebuilds or modifying authoring records."""

    def __init__(self, window: "MainWindow") -> None:
        """Use existing session/raster metrics and one worker for explicit diagnostic scans."""
        super().__init__(window, "Performance & project diagnostics")
        self.host = window
        self.resize(680, 600)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.job: LibraryJob | None = None
        self.source: object = None
        self.source_document = window.viewmodel.documents
        box = QVBoxLayout(self.content)
        tabs = QTabWidget()
        box.addWidget(tabs, 1)
        performance, diagnostics = QWidget(), QWidget()
        tabs.addTab(performance, "Performance")
        tabs.addTab(diagnostics, "Project diagnostics")
        layout = QVBoxLayout(performance)
        self.metrics = QLabel()
        self.metrics.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.metrics)
        form = QFormLayout()
        layout.addLayout(form)
        self.cache = QCheckBox("Reuse evaluated frames · up to 64 MiB / 128 samples")
        self.cache.setChecked(window.viewmodel.playback.cache_enabled)
        self.cache.toggled.connect(self.set_cache)
        form.addRow("Playback cache", self.cache)
        self.quality = QComboBox()
        for name, value in (
            ("Full", 1.0),
            ("Half · preview only", 0.5),
            ("Quarter · preview only", 0.25),
        ):
            self.quality.addItem(name, value)
        self.quality.setCurrentIndex(max(0, self.quality.findData(window.viewport.preview_quality)))
        self.quality.currentIndexChanged.connect(self.set_quality)
        form.addRow("Artwork preview", self.quality)
        self.undo_limit = QSpinBox()
        self.undo_limit.setRange(1, 10000)
        self.undo_limit.setValue(window.viewmodel.preferences.data["undo_limit"])
        self.undo_limit.setAccessibleName("Undo history retained edits")
        self.undo_limit.setKeyboardTracking(False)
        self.undo_limit.setToolTip(
            "Oldest edits are released beyond this limit; compound edits count once"
        )
        self.undo_limit.valueChanged.connect(window.viewmodel.set_undo_limit)
        form.addRow("Undo history", self.undo_limit)
        clear = QPushButton("Clear playback and retained artwork caches")
        clear.clicked.connect(self.clear_cache)
        layout.addWidget(clear)
        self.prune_button = QPushButton("Remove older generated template caches")
        self.prune_button.setToolTip(
            "Keep current and newest generations; original sources and installed packs stay intact"
        )
        self.prune_button.clicked.connect(self.prune_catalogs)
        layout.addWidget(self.prune_button)
        self.cache_note = QLabel()
        layout.addWidget(self.cache_note)
        self.cache_job: LibraryJob | None = None
        layout.addWidget(QLabel("Most expensive painted parts · double-click to select"))
        self.costs = QListWidget()
        self.costs.itemActivated.connect(self.select_cost)
        layout.addWidget(self.costs, 1)
        checks = QVBoxLayout(diagnostics)
        self.scan_button = QPushButton("Check project")
        self.scan_button.clicked.connect(self.scan)
        checks.addWidget(self.scan_button)
        self.note = QLabel(
            "Checks run in the background and never repair or discard data automatically."
        )
        self.note.setWordWrap(True)
        checks.addWidget(self.note)
        self.issues = QListWidget()
        self.issues.itemActivated.connect(self.select_issue)
        checks.addWidget(self.issues, 1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        box.addWidget(close)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        window.viewport.profile_paint = True
        self.refresh()

    def refresh(self) -> None:
        """Read a small counter snapshot twice a second; no geometry is recomputed here."""
        viewport = self.host.viewport
        session = self.host.viewmodel.playback.session
        if session is None:
            self.metrics.setText("Open a project to inspect evaluation and painting.")
            return
        pose = viewport.pose or session.pose
        cache = session.pose_cache
        pixels = sum(
            layer.tile.width() * layer.tile.height() * 4 for layer in viewport._mesh_layers.values()
        )
        self.metrics.setText(
            f"Evaluation: {session.last_evaluation_ms:.2f} ms    "
            f"Paint: {viewport.last_paint_ms:.2f} ms\n"
            f"Nodes: {len(pose.nodes):,}    Meshes: {len(pose.meshes):,}    "
            f"Triangles: {sum(len(m.triangles) for m in pose.meshes.values()):,}\n"
            f"Frame cache: {len(cache.entries)} samples / {cache.bytes / 1024**2:.1f} MiB · "
            f"{cache.hits} hits / {cache.misses} misses\n"
            f"Retained artwork: {pixels / 1024**2:.1f} MiB · "
            f"last paint reused {viewport.raster_hits}, rebuilt {viewport.raster_misses} parts\n"
            f"Undo: {len(self.host.viewmodel.documents.history.undo_stack)} / "
            f"{self.host.viewmodel.documents.history.limit} edits\n"
            "Preview quality changes never affect exports."
        )
        self.costs.clear()
        for key, milliseconds in sorted(viewport.mesh_paint_ms.items(), key=lambda pair: -pair[1])[
            :12
        ]:
            mesh = pose.meshes.get(key)
            if mesh:
                item = QListWidgetItem(f"{mesh.name} · {milliseconds:.2f} ms")
                item.setData(Qt.ItemDataRole.UserRole, mesh.object_id)
                self.costs.addItem(item)

    def set_cache(self, enabled: bool) -> None:
        """Change preview reuse within the normal document/session scope."""
        model = self.host.viewmodel.playback
        model.cache_enabled = enabled
        if model.session:
            model.session.cache_enabled = enabled
            if not enabled:
                model.session.pose_cache.clear()

    def set_quality(self) -> None:
        """Use lower viewport raster resolution while retaining original artwork."""
        self.host.viewport.preview_quality = float(self.quality.currentData())
        self.clear_cache()

    def clear_cache(self) -> None:
        """Release evaluated frames and retained part pixels, preserving source artwork."""
        session = self.host.viewmodel.playback.session
        if session:
            session.pose_cache.clear()
        viewport = self.host.viewport
        viewport._mesh_layers.clear()
        viewport._artwork_pose, viewport._artwork_layer = None, None
        viewport.update()

    def prune_catalogs(self) -> None:
        """Reclaim completed obsolete cache generations without blocking the editor."""
        from rigora.application_services.cache_retention import prune_catalogs

        model = self.host.viewmodel.content
        if self.cache_job is not None or model.busy:
            self.cache_note.setText("Wait for content preparation to finish, then try again.")
            return
        self.prune_button.setEnabled(False)
        self.cache_note.setText("Checking generated caches…")
        self.cache_job = LibraryJob(
            partial(prune_catalogs, model.library.cache_root, (model.library.bundled.parent,))
        )
        self.cache_job.signals.done.connect(self.cache_pruned)
        self.cache_job.signals.failed.connect(self.cache_prune_failed)
        self.pool.start(self.cache_job)

    def cache_pruned(self, removed: int) -> None:
        """Display maintenance results without changing the current library or document."""
        self.cache_job = None
        self.prune_button.setEnabled(True)
        self.cache_note.setText(f"Removed {removed} older generated cache generations.")

    def cache_prune_failed(self, error: str) -> None:
        """Keep partial cleanup failures visible and allow a later retry."""
        self.cache_job = None
        self.prune_button.setEnabled(True)
        self.cache_note.setText(error)

    def scan(self) -> None:
        """Inspect an isolated snapshot on a worker, retaining its identity for navigation."""
        if self.job is not None or not self.host.viewmodel.documents.project:
            return
        document = self.host.viewmodel.documents
        self.source_document, self.source = document, document.project
        snapshot = document.persistence_copy()
        self.scan_button.setEnabled(False)
        self.note.setText("Checking sources, rigs, evaluation and output budgets…")
        self.job = LibraryJob(partial(inspect_project, snapshot))
        self.job.signals.done.connect(self.scanned)
        self.job.signals.failed.connect(self.scan_failed)
        self.pool.start(self.job)

    def scanned(self, issues: tuple[Diagnostic, ...]) -> None:
        """Display issues whose navigation remains scoped to the inspected revision."""
        self.job = None
        self.scan_button.setEnabled(True)
        self.issues.clear()
        for issue in issues:
            item = QListWidgetItem(f"{issue.severity} · {issue.message}")
            item.setData(Qt.ItemDataRole.UserRole, issue)
            self.issues.addItem(item)
        self.note.setText(
            f"{len(issues)} findings. Double-click to locate an item. "
            "Checks sample one frame per scene."
        )

    def scan_failed(self, error: str) -> None:
        """Keep the project editable when inspection fails."""
        self.job = None
        self.scan_button.setEnabled(True)
        self.note.setText(error)

    def select_issue(self, item: QListWidgetItem) -> None:
        """Navigate only within the project revision actually inspected."""
        if (
            self.host.viewmodel.documents is not self.source_document
            or self.source_document.project is not self.source
        ):
            self.note.setText(
                "The project changed. Run checks again before navigating these findings."
            )
            return
        issue = item.data(Qt.ItemDataRole.UserRole)
        if issue.scene_id:
            self.source_document.select_scene(issue.scene_id)
            self.host.viewmodel.changed.emit()
        if issue.owner_id:
            self.host.scene_workspace.select_entries((issue.owner_id,))

    def select_cost(self, item: QListWidgetItem) -> None:
        """Select a currently evaluated part without relying on obsolete inspector row indices."""
        if key := item.data(Qt.ItemDataRole.UserRole):
            self.host.scene_workspace.select_entries((key,))

    def hideEvent(self, event: QHideEvent) -> None:
        """Stop hidden profiling; an explicit scan may finish in the background."""
        self.timer.stop()
        self.host.viewport.profile_paint = False
        super().hideEvent(event)

    def showEvent(self, event: QShowEvent) -> None:
        """Resume low-cadence metrics when the existing inspector is reopened."""
        super().showEvent(event)
        self.timer.start()
        self.host.viewport.profile_paint = True
        self.refresh()
