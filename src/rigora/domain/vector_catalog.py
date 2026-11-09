"""Animal authoring choices from the independent Creator catalog."""

from dataclasses import dataclass

from rigora.domain.character_recipe import VIEWS, canonical_view
from rigora.domain.illustration_catalog import CREATOR_DESIGNS, design_by_id

ANIMALS = tuple(d.id for d in CREATOR_DESIGNS if d.anatomy not in ("human", "robot"))
CATALOGS = {"Animals": ANIMALS}


@dataclass(frozen=True)
class VectorRecipe:
    """Persist an independently authored animal identity and a source format."""

    kind: str = "Animals"
    design_id: str = "tansy"
    name: str = "Tansy"
    view: str = "Front 3/4"
    primary: str = "#b88a64"
    accent: str = "#ead6b7"
    source_format: str = "SVG"
    artwork_collection: str = "original"

    def __post_init__(self) -> None:
        """Validate identity and turnaround slots without loading retired catalogs."""
        design_by_id(self.design_id)
        canonical_view(self.view)


def vector_views(kind: str) -> tuple[str, ...]:
    """Keep all editable turnaround slots available."""
    return VIEWS


def vector_poster(kind: str, name: str) -> str:
    """Return a cache identity, not a bundled PNG path."""
    return "animal/" + name
