"""Publish data-only creative presets and real evaluated PNG posters into the generated cache."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from rigora.application_services.content_thumbnails import render_content_thumbnail
from rigora.domain.content import ContentItem, ContentPack
from rigora.infrastructure.action_catalog import human_actions
from rigora.infrastructure.content_packs import write_pack
from rigora.infrastructure.effect_catalog import ffd_presets, spring_presets
from rigora.infrastructure.motion_catalog import identity, item, motions, skeletons
from rigora.resources import asset_path


def creative_items() -> tuple[ContentItem, ...]:
    """Combine original presets with explicitly licensed, attributed open-source motion data."""
    source = json.loads(
        asset_path("motions/godot-skeleton2d/motions.json").read_text(encoding="utf-8")
    )
    external = []
    for motion in source["motions"]:
        label = motion["name"].replace("_", " ").title()
        external.append(
            replace(
                item(
                    "Open demo · " + label,
                    "action",
                    "Human walks"
                    if label == "Walk"
                    else "Human runs"
                    if label == "Run"
                    else "Gestures & actions",
                    motion,
                    tags=("open-source", "godot", "human", "editable"),
                    source_format="ANIM",
                    source_url=source["source"],
                    source_sha256=source["source_sha256"],
                    description=(
                        "MIT-licensed Godot Skeleton2D numeric motion, adapted to Rigora "
                        "rest-relative bones. Original author: RustyStriker / Godot demo "
                        "contributors. No source artwork included."
                    ),
                ),
                author=source["author"],
                license=source["license"],
            )
        )
    return (
        *skeletons(),
        *motions(),
        *human_actions(),
        *external,
        *ffd_presets(),
        *spring_presets(),
    )


def write_creative_catalog(
    target: Path,
    items: tuple[ContentItem, ...],
    advance: Callable[[str], None],
) -> tuple[str, ...]:
    """Generate real specimen posters once and atomically publish two bounded portable packs."""
    output = []
    for pack_name, selected in (
        ("motions", tuple(i for i in items if i.kind == "action")),
        ("rigs-effects", tuple(i for i in items if i.kind != "action")),
    ):
        described = []
        files: dict[str, bytes] = {}
        for entry in selected:
            advance(entry.category + " · " + entry.name)
            poster = "posters/creative-" + entry.id + ".png"
            png = render_content_thumbnail(entry, {}, size=144)
            (target / poster).write_bytes(png)
            files[poster] = png
            described.append(replace(entry, thumbnail=poster))
            output.append(poster)
        pack = ContentPack(
            id=identity("pack/" + pack_name),
            name="Rigora · " + pack_name.replace("-", " & "),
            author="Rigora and credited open-source contributors",
            license="Per-item: CC0-1.0 or MIT",
            items=tuple(described),
        )
        path = pack_name + ".rigpack"
        write_pack(target / path, pack, files)
        output.append(path)
    return tuple(output)
