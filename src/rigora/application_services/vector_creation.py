"""Animal authoring through the same portable illustration and animation services."""

from rigora.application_services.character_creation import (
    CharacterBuild,
    build_character,
    character_portrait,
)
from rigora.domain.character_recipe import MOTION_CHOICES, CharacterRecipe
from rigora.domain.illustration_catalog import design_by_id
from rigora.domain.vector_catalog import VectorRecipe


def character_recipe(recipe: VectorRecipe) -> CharacterRecipe:
    """Keep animal silhouette, style and natural paints specific to the selected design."""
    design = design_by_id(recipe.design_id)
    return CharacterRecipe(
        name=recipe.name,
        design_id=design.id,
        style=design.style,
        view=recipe.view,
        source_format=recipe.source_format,
        colors={**design.colors, "Skin": recipe.primary, "Accent": recipe.accent},
    )


def build_vector(recipe: VectorRecipe) -> CharacterBuild:
    """Assemble the animal using canonical bones, source meshes and named source actions."""
    return build_character(character_recipe(recipe))


def vector_portrait(recipe: VectorRecipe) -> bytes:
    """Render the same original sources used by the portable animal specimen."""
    return character_portrait(character_recipe(recipe))


def vector_actions(recipe: VectorRecipe) -> tuple[str, ...]:
    """Expose the four independently authored full-body cycles."""
    return MOTION_CHOICES


def vector_colors(kind: str, name: str) -> tuple[str, str]:
    """Resolve this identity's natural starting fur and accent colors."""
    colors = design_by_id(name).colors
    return colors["Skin"], colors["Accent"]
