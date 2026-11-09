"""Qt-free preview framing, vector option posters and inexpensive palette replacement."""

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace

from rigora.application_services.character_creation import CharacterBuild
from rigora.domain.character_recipe import FEELING_PRESETS, MOTION_CHOICES, CharacterRecipe
from rigora.domain.creator_options import COMPONENT_CHOICES, OUTFIT_PRESETS, choose, outfit
from rigora.domain.entities import Transform
from rigora.domain.geometry import affine, inverse, multiply
from rigora.domain.illustration_catalog import customized_design
from rigora.domain.project import Project, SceneSettings
from rigora.infrastructure.illustration import artwork, hand_art, svg
from rigora.infrastructure.illustration_motion import world_joints


def stage_layout(recipe: CharacterRecipe) -> tuple[SceneSettings, Transform]:
    """Center a wardrobe-independent anatomical frame in a dedicated Creator camera."""
    d = customized_design(
        recipe.design_id, recipe.style, dict(recipe.proportions), recipe.body_shape
    )
    joints = world_joints(d, recipe.view, rest=True)
    top = joints["head"].root[1] - d.head * 2.6
    bottom = 12
    height = max(480, round(bottom - top + 130))
    width = max(640, round(height * 4 / 3))
    return SceneSettings(width=width, height=height, fps=30), Transform(
        x=width / 2, y=height / 2 - (top + bottom) / 2
    )


def posed_portrait(recipe: CharacterRecipe, action: str = "Stand", phase: float = 0) -> bytes:
    """Render actual vector parts in a representative pose without building timelines."""
    d, rest, parts = artwork(recipe)
    current = world_joints(d, recipe.view, action, phase, rest=action == "Stand")
    shapes = []
    for part in parts:
        if not part.visible or part.markup == "<g/>":
            continue
        before, after = rest[part.bone], current[part.bone]
        matrix = multiply(
            affine(*after.root, after.angle, 1, 1, 0, 0),
            inverse(affine(*before.root, before.angle, 1, 1, 0, 0)),
        )
        shapes.append(
            '<g transform="matrix(' + " ".join(map(str, matrix)) + ')">' + part.markup + "</g>"
        )
    top = min(j.root[1] for j in current.values()) - d.head * 2.8
    return svg("".join(shapes), (-d.width * 2.3, top, d.width * 4.6, 20 - top))


def option_sources(recipe: CharacterRecipe) -> Iterator[tuple[tuple[str, str], bytes]]:
    """Yield genuine SVG previews for every available option, including unretained choices."""
    base = replace(recipe, alternatives={}, motions=())
    for category, values in COMPONENT_CHOICES.items():
        for value in values:
            choice = choose(base, category, value)
            if category == "Hands":
                d, _, _ = artwork(choice)
                ink = str(choice.colors.get("Ink", d.colors["Ink"]))
                fill = str(choice.garment_colors.get("Hands/" + value, "#ffffff"))
                yield (
                    (category, value),
                    svg(
                        f'<path d="M 0 -10 L 0 0" stroke="{ink}" stroke-width="4"/>'
                        + hand_art(True, value, ink, choice.stroke_width, fill),
                        (-15, -12, 38, 36),
                    ),
                )
                continue
            _, _, parts = artwork(choice)
            family = "Mouth style" if category == "Mouth" else category
            selected = [p for p in parts if p.family == family and p.variant == value]
            if category == "Mouth":
                mouth_parts = [p for p in selected if p.name.endswith((" · Rest", " · AI"))]
                selected = []
                for index, part in enumerate(mouth_parts):
                    x, y, w, h = part.bounds
                    shift = index * (h + 8)
                    selected.append(
                        replace(
                            part,
                            markup=f'<g transform="translate(0 {shift})">' + part.markup + "</g>",
                            bounds=(x, y + shift, w, h),
                        )
                    )
            selected = [p for p in selected if p.markup != "<g/>"]
            if not selected:
                source = svg(
                    '<circle cx="24" cy="24" r="15" fill="none" stroke="#999" '
                    'stroke-width="2"/><path d="M 13 35 L 35 13" stroke="#999" '
                    'stroke-width="2"/>',
                    (0, 0, 48, 48),
                )
            else:
                x, y = min(p.bounds[0] for p in selected), min(p.bounds[1] for p in selected)
                right = max(p.bounds[0] + p.bounds[2] for p in selected)
                bottom = max(p.bounds[1] + p.bounds[3] for p in selected)
                source = svg(
                    "".join(p.markup for p in selected),
                    (x - 3, y - 3, right - x + 6, bottom - y + 6),
                )
            yield (category, value), source
    for name in OUTFIT_PRESETS:
        yield ("Outfit sets", name), posed_portrait(outfit(base, name))
    for name in FEELING_PRESETS:
        face = replace(base, feeling=name)
        d, joints, parts = artwork(face)
        x, y = joints["head"].root
        yield (
            ("Expression", name),
            svg(
                "".join(p.markup for p in parts if p.bone == "head" and p.visible),
                (x - d.head * 1.3, y - d.head * 2.7, d.head * 2.6, d.head * 3),
            ),
        )
    for name in ("Open", "Blink", "Wink"):
        d, joints, parts = artwork(replace(base, poses={**base.poses, "Eyes": name}))
        x, y = joints["head"].root
        yield (
            ("Eye poses", name),
            svg(
                "".join(p.markup for p in parts if p.bone == "head" and p.visible),
                (x - d.head * 1.3, y - d.head * 2.7, d.head * 2.6, d.head * 3),
            ),
        )
    for name in MOTION_CHOICES:
        yield ("Animations", name), posed_portrait(base, name, 0.3 if name == "Jump" else 0.45)
    from rigora.application_services.illustration_cache import recipe_for
    from rigora.domain.illustration_catalog import CREATOR_DESIGNS

    for design in CREATOR_DESIGNS:
        yield ("Presets", design.id), posed_portrait(recipe_for(design))


def repaint_character(built: CharacterBuild, recipe: CharacterRecipe) -> CharacterBuild:
    """Replace only vector paints and recipe metadata; reuse all bones, meshes and action keys."""
    project = Project.from_dict(json.loads(built.files["character.json"]))
    _, _, parts = artwork(recipe)
    sources = {p.name: svg(p.markup, p.bounds) for p in parts}
    files = dict(built.files)
    assets = []
    for asset in project.assets:
        data = sources[asset.name.removesuffix(".svg")]
        files[asset.source] = data
        assets.append(replace(asset, sha256=hashlib.sha256(data).hexdigest()))
    scene = project.scenes[0]
    scene = replace(
        scene,
        groups=tuple(
            replace(g, extra={**g.extra, "character_recipe": recipe.to_dict()})
            if g.id == built.root_id
            else g
            for g in scene.groups
        ),
    )
    project = replace(project, assets=tuple(assets), scenes=(scene,))
    files["character.json"] = json.dumps(project.to_dict(), separators=(",", ":")).encode()
    return replace(built, files=files)
