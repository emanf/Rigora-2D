"""Isolated, debounced Creator preparation with reusable actions and live vector paints."""

import json
import time
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from rigora.application_services.character_creation import (
    CharacterBuild,
    build_character,
    character_portrait,
    raster_source,
)
from rigora.application_services.commands import ProjectPatch
from rigora.application_services.creator_preview import (
    option_sources,
    posed_portrait,
    repaint_character,
    stage_layout,
)
from rigora.application_services.documents import DocumentService
from rigora.application_services.illustration_cache import option_poster
from rigora.application_services.meshes import MeshService
from rigora.domain.character_recipe import MOTION_CHOICES, CharacterRecipe
from rigora.domain.entities import Transform
from rigora.domain.illustration_catalog import customized_design
from rigora.domain.project import Project
from rigora.infrastructure.illustration_motion import duration
from rigora.presentation.artwork import decode_artwork
from rigora.presentation.viewmodels.content_library import LibraryJob


def geometry_key(recipe: CharacterRecipe) -> CharacterRecipe:
    """Palette and exported-action selection do not change topology or choreography."""
    return replace(recipe, colors={}, garment_colors={}, motions=())


class CharacterWizardModel(QObject):
    """Own one worker; discard obsolete results and never mutate the destination project."""

    changed = Signal()
    progress_changed = Signal(int, str)
    preview_ready = Signal(object)

    def __init__(self, parent: QObject, *, cache_root: Path | None = None) -> None:
        """Own the isolated preview controls, option state and cancellable preparation worker."""
        super().__init__(parent)
        self.recipe = CharacterRecipe()
        self.adaptive_cards = False
        self.cache_root = cache_root
        self.ready: CharacterRecipe | None = None
        self.built: CharacterBuild | None = None
        self.full_built: CharacterBuild | None = None
        self.preview: DocumentService | None = None
        self.ready_preview: DocumentService | None = None
        self.images: dict[str, Any] = {}
        self.ready_images: dict[str, Any] = {}
        self.option_images: dict[tuple[str, str], Any] = {}
        self.icons_recipe: CharacterRecipe | None = None
        self.icons_adaptive: bool | None = None
        self.error = ""
        self.busy = False
        self.alive = True
        self.progress = 0
        self.status = ""
        self.job: LibraryJob | None = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.prepare)
        self.progress_changed.connect(self.report_progress)
        self.preview_ready.connect(self.adopt_preview)

    def card_recipe(self) -> CharacterRecipe:
        """Resolve canonical card art or the current character's appearance."""
        return (
            replace(self.recipe, motions=()) if self.adaptive_cards else CharacterRecipe(motions=())
        )

    def set_adaptive_cards(self, enabled: bool) -> None:
        """Refresh thumbnails independently of the authored character and its export choices."""
        self.adaptive_cards = enabled
        self.ensure_prepared(immediate=True)

    def cards_current(self) -> bool:
        """Match both appearance and output mode; identical recipes can use PNG or SVG cards."""
        return (
            self.icons_recipe == self.card_recipe() and self.icons_adaptive == self.adaptive_cards
        )

    def adopt_preview(self, payload: Any) -> None:
        """Start using the ready rig while independent option-card rendering continues."""
        recipe, built, full, doc, images = payload
        if self.alive and recipe == self.recipe:
            self.ready, self.built, self.full_built = recipe, built, full
            self.preview, self.images = doc, images
            self.ready_preview, self.ready_images = doc, images
            self.changed.emit()

    def report_progress(self, value: int, status: str) -> None:
        """Adopt worker progress only on the GUI thread."""
        self.progress, self.status = value, status
        self.changed.emit()

    def request(self, recipe: CharacterRecipe) -> None:
        """Paint an inexpensive composite immediately, then debounce the portable rig build."""
        if recipe == self.recipe and self.preview is not None:
            return
        previous = self.recipe
        self.recipe, self.error = recipe, ""
        if recipe == self.ready and self.ready_preview:
            self.preview, self.images = self.ready_preview, self.ready_images
        elif replace(recipe, motions=previous.motions) != previous or self.preview is None:
            appearance = replace(recipe, motions=(), alternatives={})
            source = None
            if (
                self.ready_preview
                and self.ready
                and geometry_key(recipe) == geometry_key(self.ready)
            ):
                animation = self.ready_preview.animation
                clip = animation.evaluator.clip
                if clip:
                    design = customized_design(
                        recipe.design_id, recipe.style, dict(recipe.proportions), recipe.body_shape
                    )
                    source = posed_portrait(
                        appearance,
                        clip.name,
                        min(1, animation.playback.frame / duration(design, clip.name)),
                    )
            if source is None:
                source = character_portrait(appearance)
            doc = DocumentService()
            doc._link_objects = False
            doc.new("Creator appearance")
            settings, anchor = stage_layout(recipe)
            scene = replace(doc.scene, settings=settings, cameras=())
            assert doc.project is not None
            doc.execute(
                ProjectPatch("Creator stage", {"scenes": doc.project.scenes}, {"scenes": (scene,)})
            )
            service = MeshService(doc)
            mesh = service.mesh(service.import_image_bytes("character.svg", source, 1, 1))
            left, top, _, _ = map(float, ET.fromstring(source).attrib["viewBox"].split())
            service.commit(
                "Center Creator appearance",
                objects=tuple(
                    replace(o, transform=Transform(x=left + anchor.x, y=top + anchor.y))
                    for o in service.scene.objects
                ),
            )
            self.preview = doc
            self.images = {str(mesh.asset_id): (decode_artwork(source, 320), source)}
        self.changed.emit()

    def ensure_prepared(self, *, immediate: bool = False) -> None:
        """Coalesce rapid changes while allowing Create to request immediate preparation."""
        self.timer.start(0 if immediate else 150)

    def prepare(self) -> None:
        """Build all preview actions once; recoloring reuses the completed canonical rig."""
        icons_ready = self.cards_current()
        if not self.alive or self.busy or self.ready == self.recipe and icons_ready:
            return
        requested = self.recipe
        card_recipe = self.card_recipe()
        adaptive = self.adaptive_cards
        previous = self.ready
        cached = (
            self.full_built
            if previous and geometry_key(previous) == geometry_key(requested)
            else None
        )
        shared_preview = (
            self.ready_preview
            if previous and replace(requested, motions=previous.motions) == previous
            else None
        )
        old_images = self.ready_images
        old_icons = self.option_images
        old_icons_recipe = self.icons_recipe
        old_icons_adaptive = self.icons_adaptive
        self.busy = True
        self.progress, self.status = 0, "Preparing SVG parts and animations…"

        def checkpoint() -> bool:
            """Yield between worker steps and cancel superseded recipe requests."""
            time.sleep(0.0002)
            return not self.alive or self.recipe != requested or self.adaptive_cards != adaptive

        def build() -> tuple[
            CharacterBuild,
            CharacterBuild,
            DocumentService,
            dict[str, Any],
            dict[tuple[str, str], Any],
        ]:
            """Prepare portable artwork/actions and render card images off-thread."""
            if cached:
                full = (
                    cached
                    if previous
                    and previous.colors == requested.colors
                    and previous.garment_colors == requested.garment_colors
                    else repaint_character(cached, replace(requested, motions=MOTION_CHOICES))
                )
            else:
                full = build_character(
                    replace(requested, motions=MOTION_CHOICES), cancelled=checkpoint
                )
            if checkpoint():
                raise CancelledError()
            if shared_preview is not None:
                doc, images = shared_preview, old_images
            else:
                project = Project.from_dict(json.loads(full.files["character.json"]))
                settings, anchor = stage_layout(requested)
                scene = project.scenes[0]
                scene = replace(
                    scene,
                    settings=settings,
                    groups=tuple(
                        replace(g, transform=anchor) if g.id == full.root_id else g
                        for g in scene.groups
                    ),
                )
                doc = DocumentService()
                doc.project = replace(project, scenes=(scene,))
                doc._link_objects = False
                doc._asset_data.update(full.files)
                images = {}
                for asset in project.assets:
                    data = full.files[asset.source]
                    prior = old_images.get(asset.id)
                    images[asset.id] = (
                        prior if prior and prior[1] == data else (decode_artwork(data, 256), data)
                    )
            source = json.loads(full.files["character.json"])
            target = source["scenes"][0]
            target["clips"] = [c for c in target["clips"] if c["name"] in requested.motions]
            keep = {c["timeline_id"] for c in target["clips"]}
            target["timelines"] = [t for t in target["timelines"] if t["id"] in keep]
            for group in target["groups"]:
                if group.get("object_container"):
                    group["character_recipe"] = requested.to_dict()
            built = replace(
                full,
                files={**full.files, "character.json": json.dumps(source).encode()},
                item=replace(
                    full.item,
                    payload={
                        **full.item.payload,
                        "performance_clips": [
                            c
                            for c in full.item.payload["performance_clips"]
                            if c["name"] in requested.motions
                        ],
                        "selected_clip": target["clips"][0]["id"] if target["clips"] else None,
                    },
                ),
            )
            self.preview_ready.emit((requested, built, full, doc, images))
            self.progress_changed.emit(45, "Rendering option cards…")
            icons = old_icons
            if old_icons_recipe != card_recipe or old_icons_adaptive != adaptive:
                icons = {}
                for index, (key, data) in enumerate(option_sources(card_recipe)):
                    if checkpoint():
                        raise CancelledError()
                    if not adaptive:
                        path = self.cache_root / option_poster(*key) if self.cache_root else None
                        data = (
                            path.read_bytes()
                            if path and path.is_file()
                            else raster_source(data, height=128)
                        )
                    icons[key] = (decode_artwork(data, 128, upscale_vectors=adaptive), data)
                    if index % 8 == 0:
                        self.progress_changed.emit(
                            min(95, 45 + index // 2), "Rendering " + key[0] + " cards…"
                        )
            return built, full, doc, images, icons

        def complete(result: Any) -> None:
            """Adopt only the current worker result and schedule newer pending choices."""
            self.busy, self.job = False, None
            if not self.alive:
                return
            if requested == self.recipe and adaptive == self.adaptive_cards:
                self.built, self.full_built, self.preview, self.images, self.option_images = result
                self.ready = requested
                self.icons_recipe = card_recipe
                self.icons_adaptive = adaptive
                self.ready_preview, self.ready_images = self.preview, self.images
                self.progress, self.status = 100, ""
            self.changed.emit()
            if self.ready != self.recipe or not self.cards_current():
                self.timer.start(0)

        def failed(message: str) -> None:
            """Expose real errors, discard stale failures and resume any pending recipe."""
            self.busy, self.job = False, None
            if not self.alive:
                return
            if requested == self.recipe:
                self.error = message
            self.changed.emit()
            if requested != self.recipe or not message and not self.cards_current():
                self.timer.start(0)

        self.job = LibraryJob(build)
        self.job.signals.done.connect(complete)
        self.job.signals.failed.connect(failed)
        self.pool.start(self.job)
        self.changed.emit()

    def shutdown(self) -> None:
        """Cancel and drain work before Qt destroys the owning dialog or image caches."""
        self.alive = False
        self.timer.stop()
        self.pool.waitForDone()
        self.ready_preview = None
        self.ready_images = {}
        self.full_built = None
