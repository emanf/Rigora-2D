"""Portable, data-only content descriptors independent of installed storage and Qt."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Literal

from rigora.domain.entities import Asset, Entity
from rigora.domain.validation import ProjectError, portable_relative_path, text

CATEGORIES = (
    "Characters",
    "Animals",
    "Home & interiors",
    "Environment",
    "Vehicles",
    "Plants & springs",
    "Props & accessories",
    "Scenes & backgrounds",
    "Human walks",
    "Human runs",
    "Human idle & stand",
    "Jumps & climbing",
    "Animal motions",
    "Animation clips",
    "Skeleton templates",
    "Human rigs",
    "Quadruped rigs",
    "Birds & wings",
    "Flexible spines",
    "Cartoon creatures",
    "Static poses",
    "Facial expressions",
    "Hand poses & gestures",
    "Meshes & deformation",
    "Materials & effects",
    "FFD motions",
    "FFD shapes",
    "Spring dynamics",
    "Gestures & actions",
    "Work & interactions",
    "Combat & reactions",
    "Social gestures",
    "Exercise & poses",
    "Dance & celebrations",
    "Shapes",
    "Adventure props",
    "Food & drink",
    "Fire & smoke",
    "Water & weather",
    "Atmosphere & magic",
    "Moving mechanisms",
)

CHARACTER_VIEWS = (
    ("All views", ""),
    ("Front", "front"),
    ("Front 3/4", "three-quarter"),
    ("Side", "side"),
    ("Back 3/4", "back-three-quarter"),
    ("Back", "back"),
)

PROP_FAMILIES = (
    ("All props", ""),
    ("Balls", "balls"),
    ("Hats", "hats"),
    ("Tools", "tools"),
    ("Bags", "bags"),
    ("Glasses & eyewear", "eyewear"),
    ("Glass & drinkware", "drinkware"),
    ("Trees", "trees"),
    ("Bushes & plants", "bushes"),
    ("Fruits", "fruits"),
    ("Clouds & weather", "weather"),
    ("Basic shapes", "shapes"),
    ("Household", "household"),
    ("Terrain", "terrain"),
)


def content_categories(categories: Iterable[str]) -> tuple[str, ...]:
    """Order populated catalog categories, including dynamically supplied collections."""
    available = set(categories)
    return (*(c for c in CATEGORIES if c in available), *sorted(available - set(CATEGORIES)))


def content_families(category: str) -> tuple[tuple[str, str], ...]:
    """Keep environment filters meaningful after moving nature props out of accessories."""
    environment = {"trees", "bushes", "weather", "terrain"}
    choices = tuple(
        pair
        for pair in PROP_FAMILIES[1:]
        if (pair[1] in environment) == (category == "Environment")
    )
    return (("All assets", ""), *choices)


def asset_format(asset: Asset) -> str:
    """Describe the actual source, independently of its cached raster thumbnail."""
    if asset.kind == "vector":
        return "SVG"
    suffix = PurePosixPath(asset.source).suffix.lstrip(".").upper()
    media = asset.media_type.partition("/")[2].upper().replace("JPEG", "JPG")
    return (
        media
        if media in ("PNG", "JPG", "WEBP", "GIF", "TIFF", "BMP", "WAV", "MP4")
        else suffix or asset.kind.upper()
    )


def content_format(item: "ContentItem") -> str:
    """Infer image format from payload sources, never from a PNG library poster."""
    explicit = item.extra.get("source_format")
    if isinstance(explicit, str) and explicit:
        return explicit
    source_map = item.payload.get("sources", {})
    sources = list(source_map.values()) if isinstance(source_map, Mapping) else []
    if source := item.payload.get("source"):
        sources.append(source)
    formats = {PurePosixPath(str(s)).suffix.lstrip(".").upper() for s in sources}
    formats &= {"SVG", "PNG", "JPG", "JPEG", "WEBP", "GIF", "BMP", "TIFF"}
    if formats:
        return next(iter(formats)) if len(formats) == 1 else "MIXED"
    return {
        "rig": "RIG",
        "pose": "POSE",
        "action": "ANIM",
        "deformation": "MESH",
        "spring": "SPRING",
        "scene": "SCENE",
    }.get(item.kind, "ASSET")


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentItem(Entity):
    """Searchable provenance and a data-only payload with a validated dispatch kind."""

    kind: Literal["rig", "pose", "action", "deformation", "spring", "artwork", "scene"]
    category: str
    description: str = ""
    author: str
    license: str
    version: str = "1.0"
    tags: tuple[str, ...] = ()
    thumbnail: str = ""
    engine_version: int = 1
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate metadata and portable image paths while retaining unknown optional fields."""
        Entity.__post_init__(self)
        text(self.category, "Content category")
        for value in (self.author, self.license, self.version):
            text(value, "Content provenance")
        if len(self.tags) > 64:
            raise ProjectError("Content supports at most 64 tags.")
        if self.thumbnail:
            portable_relative_path(self.thumbnail)


@dataclass(frozen=True, slots=True, kw_only=True)
class ContentPack(Entity):
    """Versioned offline collection of original or explicitly licensed reusable assets."""

    format: Literal["rigora.content-pack"] = "rigora.content-pack"
    version: int = 1
    author: str
    license: str
    items: tuple[ContentItem, ...]

    def __post_init__(self) -> None:
        """Reject duplicate item identities, unsupported formats and unbounded collections."""
        Entity.__post_init__(self)
        if self.version != 1 or not 1 <= len(self.items) <= 128:
            raise ProjectError("Content packs require format 1 and between 1 and 128 items.")
        if len({item.id for item in self.items}) != len(self.items):
            raise ProjectError("Content item IDs must be unique within a pack.")
        text(self.author, "Pack author")
        text(self.license, "Pack license")
