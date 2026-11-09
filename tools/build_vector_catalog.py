"""Bake original animal/household cards and portable rigged, animated catalog packs."""

import argparse
import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import resvg_py
from build_content_thumbnails import bake_thumbnails
from PIL import Image

from rigora.application_services.vector_creation import (
    action_name,
    build_vector,
    vector_actions,
    vector_colors,
    vector_portrait,
)
from rigora.domain.content import ContentPack
from rigora.domain.vector_catalog import CATALOGS, VectorRecipe, vector_poster, vector_views
from rigora.infrastructure.content_packs import write_pack


def build(kinds: tuple[str, ...] = tuple(CATALOGS)) -> None:
    """Save cards once and deduplicate repeated SVG bytes to retain bounded pack sizes."""
    for kind in kinds:
        names = CATALOGS[kind]
        files = {}
        items = []
        for name in names:
            colors = vector_colors(kind, name)
            recipe = VectorRecipe(
                kind=kind,
                design_id=name,
                name=name,
                primary=colors[0],
                accent=colors[1],
                view="Front 3/4" if kind in ("Animals", "Household") else vector_views(kind)[0],
            )
            if kind == "Environment" and len(vector_actions(recipe)) > 1:
                recipe = replace(recipe, name=f"{name} · {action_name(recipe)}")
            poster = Path("assets") / vector_poster(kind, name)
            poster.parent.mkdir(parents=True, exist_ok=True)
            raw = resvg_py.svg_to_bytes(
                svg_string=vector_portrait(recipe).decode(),
                width=512,
                height=512,
                skip_system_fonts=True,
            )
            image = Image.open(BytesIO(raw)).convert("RGBA")
            if bounds := image.getbbox():
                image = image.crop(bounds)
            factor = min(112 / image.width, 112 / image.height)
            image = image.resize(
                (max(1, round(image.width * factor)), max(1, round(image.height * factor))),
                Image.Resampling.LANCZOS,
            )
            card = Image.new("RGBA", (128, 128))
            card.paste(image, ((128 - image.width) // 2, (128 - image.height) // 2), image)
            card.save(poster)
            built = build_vector(recipe)
            prefix = name.lower().replace(" ", "-") + "/"
            files[prefix + "character.json"] = built.files["character.json"]
            files[prefix + "portrait.svg"] = built.files["portrait.svg"]
            sources = {}
            for key, path in built.item.payload["sources"].items():
                data = built.files[path]
                target = f"vectors/{hashlib.sha256(data).hexdigest()}.svg"
                files[target] = data
                sources[key] = target
            item = replace(
                built.item,
                id=str(uuid5(NAMESPACE_URL, f"rigora:vector-catalog:{kind}:{name}")),
                thumbnail=prefix + "portrait.svg",
                payload={
                    **built.item.payload,
                    "project_source": prefix + "character.json",
                    "sources": sources,
                },
            )
            member = f"thumbnails/{name.lower().replace(' ', '-')}-{item.id[:8]}.png"
            files[member] = poster.read_bytes()
            item = replace(item, thumbnail=member)
            items.append(item)
            print("Built", kind, name, flush=True)
        pack = ContentPack(
            id=str(uuid5(NAMESPACE_URL, f"rigora:vector-catalog:{kind}")),
            name=f"Rigora Vector Creator · {kind}",
            author="Rigora contributors",
            license="CC0-1.0",
            items=tuple(items),
        )
        pack = bake_thumbnails(pack, files)
        used = (
            {i.thumbnail for i in pack.items}
            | {i.payload["project_source"] for i in pack.items}
            | {s for i in pack.items for s in i.payload["sources"].values()}
        )
        write_pack(
            Path(f"assets/library/creator-{kind.lower()}.rigpack"),
            pack,
            {k: v for k, v in files.items() if k in used},
            overwrite=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", action="append", choices=tuple(CATALOGS))
    arguments = parser.parse_args()
    build(tuple(arguments.kind) if arguments.kind else tuple(CATALOGS))
