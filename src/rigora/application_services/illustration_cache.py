"""Generate offline built-in catalogs and posters in a versioned user cache.

Nothing generated is required in the source tree. A completed generation is
published by atomic directory rename; cancellation never exposes partial packs.
Templates and Creator choices have independent indexes and identities.
"""

import hashlib
import json
import shutil
import threading
from collections.abc import Callable
from concurrent.futures import CancelledError
from dataclasses import asdict, replace
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

from rigora.application_services.character_creation import (
    build_character,
    character_portrait,
    raster_source,
)
from rigora.domain.character_recipe import CharacterRecipe
from rigora.domain.content import ContentPack
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, TEMPLATE_DESIGNS, Design
from rigora.infrastructure.content_packs import write_pack

ART_REVISION = 32
_LOCK = threading.Lock()
type Progress = Callable[[int, int, str], None]


def cache_identity() -> str:
    """Include authoring records and render revision so stale artwork cannot survive redesigns."""
    data = json.dumps(
        {
            "revision": ART_REVISION,
            "designs": [asdict(d) for d in (*TEMPLATE_DESIGNS, *CREATOR_DESIGNS)],
        },
        sort_keys=True,
    )
    return "illustrations-" + hashlib.sha256(data.encode()).hexdigest()[:16]


def cached_catalog(root: Path) -> Path:
    """Return the owned version directory without creating files or touching user packs."""
    return root / cache_identity()


def catalog_ready(root: Path) -> bool:
    """Validate published packs and poster presence without preparing or modifying content."""
    target = cached_catalog(root)
    try:
        record = json.loads((target / "complete.json").read_text(encoding="utf-8"))
        return bool(
            record["identity"] == cache_identity()
            and record["pack_sha256s"]
            and all(
                Path(name).name == name
                and hashlib.sha256((target / name).read_bytes()).hexdigest() == digest
                for name, digest in record["pack_sha256s"].items()
            )
            and all((target / p).is_file() for p in record["posters"])
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def option_poster(category: str, value: str) -> str:
    """Return a stable PNG cache path independent of filesystem-unsafe choice names."""
    key = hashlib.sha256((category + "\0" + value).encode()).hexdigest()[:24]
    return "options/" + key + ".png"


def recipe_for(design: Design) -> CharacterRecipe:
    """Resolve each catalog's own original appearance, format and motion identity."""
    recipe = CharacterRecipe(
        name=design.name,
        design_id=design.id,
        style=design.style,
        source_format=design.format,
        colors=design.colors,
    )
    from rigora.domain.creator_options import CREATOR_LOOKS, outfit

    if design.id in CREATOR_LOOKS:
        name, paints = CREATOR_LOOKS[design.id]
        recipe = replace(outfit(recipe, name), colors={**design.colors, **paints})
    return recipe


def ensure_catalog(
    root: Path, progress: Progress | None = None, cancelled: Callable[[], bool] | None = None
) -> Path:
    """Build once off-thread, with deterministic manifests and bounded authored choices."""
    target = cached_catalog(root)
    with _LOCK:
        if catalog_ready(root):
            return target
        root.mkdir(parents=True, exist_ok=True)
        from rigora.application_services.creator_preview import option_sources

        options = tuple(option_sources(CharacterRecipe(motions=())))
        from rigora.application_services.template_catalog import (
            creative_items,
            write_creative_catalog,
        )

        creative = creative_items()
        from rigora.application_services.object_templates import (
            object_template_count,
            write_object_catalog,
        )

        staging = root / (".preparing-" + uuid4().hex)
        staging.mkdir()
        total = (
            len(TEMPLATE_DESIGNS)
            + len(CREATOR_DESIGNS)
            + len(options)
            + len(creative)
            + object_template_count()
        )
        count = 0

        def update(label: str) -> None:
            if cancelled and cancelled():
                raise CancelledError()
            if progress:
                progress(count, total, label)

        try:
            items, files, posters = [], {}, []
            (staging / "posters").mkdir()
            for design in TEMPLATE_DESIGNS:
                update("Templates · " + design.name)
                recipe = recipe_for(design)
                built = build_character(recipe, cancelled=cancelled)
                poster = "posters/" + design.id + ".png"
                png = raster_source(character_portrait(recipe), height=256)
                (staging / poster).write_bytes(png)
                posters.append(poster)
                prefix = design.id + "/"
                files.update({prefix + k: v for k, v in built.files.items()})
                files[poster] = png
                payload = {
                    **built.item.payload,
                    "project_source": prefix + "character.json",
                    "sources": {k: prefix + v for k, v in built.item.payload["sources"].items()},
                }
                items.append(replace(built.item, thumbnail=poster, payload=payload))
                count += 1
            pack = ContentPack(
                id=str(uuid5(NAMESPACE_URL, "rigora/new-templates/" + cache_identity())),
                name="Rigora original Templates",
                author="Rigora",
                license="Mixed; see each character's GLOVE-NOTICE.md",
                items=tuple(items),
            )
            write_pack(staging / "templates.rigpack", pack, files)

            def advance(label: str) -> None:
                """Report actual preset evaluation before its poster is written."""
                nonlocal count
                update(label)
                count += 1

            posters.extend(write_creative_catalog(staging, creative, advance))
            posters.extend(write_object_catalog(staging, advance))
            creator = []
            for design in CREATOR_DESIGNS:
                update("Character Creation · " + design.name)
                poster = "posters/" + design.id + ".png"
                (staging / poster).write_bytes(
                    raster_source(character_portrait(recipe_for(design)), height=256)
                )
                posters.append(poster)
                creator.append(
                    {
                        "id": design.id,
                        "name": design.name,
                        "anatomy": design.anatomy,
                        "style": design.style,
                        "format": design.format,
                        "poster": poster,
                    }
                )
                count += 1
            (staging / "creator.json").write_text(json.dumps(creator, indent=2), encoding="utf-8")
            (staging / "options").mkdir()
            for (category, value), source in options:
                update(category + " · " + value)
                poster = option_poster(category, value)
                (staging / poster).write_bytes(raster_source(source, height=128))
                posters.append(poster)
                count += 1
            (staging / "complete.json").write_text(
                json.dumps(
                    {
                        "identity": cache_identity(),
                        "pack_sha256": hashlib.sha256(
                            (staging / "templates.rigpack").read_bytes()
                        ).hexdigest(),
                        "pack_sha256s": {
                            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in staging.glob("*.rigpack")
                        },
                        "posters": posters,
                    }
                ),
                encoding="utf-8",
            )
            if target.exists():
                if catalog_ready(root):
                    return target
                # Only this exact generated version is replaceable; never traverse user packs.
                resolved = target.resolve()
                if resolved.parent != root.resolve() or target.is_symlink() or target.is_junction():
                    raise ValueError("Invalid generated catalog replacement path.")
                shutil.rmtree(target)
            staging.rename(target)
            update("Ready")
            return target
        finally:
            if staging.exists():
                shutil.rmtree(staging)
