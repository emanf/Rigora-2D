"""Revisioned artwork replacement preserving asset identities, UVs and authored rig geometry."""

import hashlib
from dataclasses import replace
from pathlib import Path

from rigora.application_services.commands import ProjectPatch
from rigora.application_services.documents import DocumentService
from rigora.domain.project import ProjectError
from rigora.engine.artwork_source import inspect_artwork
from rigora.infrastructure.media_import import pillow_image
from rigora.infrastructure.project_storage import MAX_ASSET_SIZE


class ArtworkEditingService:
    """Replace source pixels/vectors while keeping every mesh, binding and timeline reference."""

    def __init__(self, document: DocumentService) -> None:
        """Borrow one document; source revisions remain retained for Undo/Redo."""
        self.document = document

    def replace_bytes(self, asset_id: str, data: bytes) -> dict[str, object]:
        """Embed a validated content-addressed revision fitted to existing UV geometry."""
        project = self.document.project
        asset = next((a for a in project.assets if a.id == asset_id), None) if project else None
        if project is None or asset is None or asset.kind not in ("raster", "vector"):
            raise ProjectError("Choose a registered image or vector source.")
        if type(data) is not bytes or len(data) > MAX_ASSET_SIZE:
            raise ProjectError("Replacement artwork must fit the 32 MiB source budget.")
        info = inspect_artwork(data)
        if info.kind == "raster":
            pillow_image(data)
        used = sum(
            len(self.document.read_asset(a.id))
            for a in project.assets
            if a.id != asset_id and a.storage == "embedded"
        )
        if used + len(data) > 96 * 1024 * 1024:
            raise ProjectError("Replacement exceeds the 96 MiB embedded source budget.")
        digest = hashlib.sha256(data).hexdigest()
        source = f"assets/{asset.id}/{digest}.{'svg' if info.kind == 'vector' else 'image'}"
        changed = replace(
            asset,
            source=source,
            storage="embedded",
            sha256=digest,
            media_type=info.media_type,
            kind=info.kind,
            extra={**asset.extra, "image_width": info.width, "image_height": info.height},
        )
        before_data = self.document._asset_data.get(source)
        self.document._asset_data[source] = data
        try:
            self.document.execute(
                ProjectPatch(
                    "Replace artwork",
                    {"assets": project.assets},
                    {"assets": tuple(changed if a.id == asset_id else a for a in project.assets)},
                )
            )
        except BaseException:
            if before_data is None:
                self.document._asset_data.pop(source, None)
            raise
        old_width, old_height = asset.extra.get("image_width"), asset.extra.get("image_height")
        resized = (old_width, old_height) != (info.width, info.height)
        return {
            "asset_id": asset.id,
            "size_changed": resized,
            "message": "Artwork replaced. Existing geometry and UVs retained."
            + (" New proportions are fitted to the existing mesh." if resized else ""),
        }

    def replace_file(self, asset_id: str, path: Path) -> dict[str, object]:
        """Read a host-authorized local file with the ordinary bounded source loader."""
        return self.replace_bytes(asset_id, self.document._read_asset_file(path))
