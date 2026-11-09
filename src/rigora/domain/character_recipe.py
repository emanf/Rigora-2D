"""Portable choices for the independent original Character Creation collection."""

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from rigora.domain.illustration_catalog import CREATOR_DESIGNS, design_by_id
from rigora.domain.validation import ProjectError

VIEWS = ("Front", "Front 3/4", "Side", "Back 3/4", "Back")
RUN_ACTIONS = ("Run", "Jog", "Sprint", "Run alternate", "Anime run", "Bouncy run", "Heavy run")
MOTION_CHOICES = (
    "Stand",
    "Idle",
    "Walk",
    *RUN_ACTIONS,
    "Jump",
    "Hop",
    "High jump",
    "Crouch",
    "Stretch",
    "Wave",
    "Bow",
    "Cheer",
    "Point",
)
MOUTH_POSES = ("Rest", "AI", "E", "O", "U", "FV", "MBP", "L", "WQ", "TH")
MOUTH_STYLES = ("Soft", "Graphic", "Ink", "Small", "Wide", "Round", "Toon", "Teeth", "Fangs")
STYLE_CHOICES = ("Classic", "Color", "Outline", "Sketch")
GENDERS = ("Girl", "Boy", "Woman", "Man", "Robot")
CHARACTER_PRESETS = tuple(d.name for d in CREATOR_DESIGNS if d.anatomy in ("human", "robot"))
PALETTE = design_by_id("nova").colors
FEELING_PRESETS = ("Neutral", "Happy", "Sad", "Angry", "Surprised", "Sleepy")
DRESS_CHOICES = {
    "Tops": ("none", "tee", "jacket", "hoodie", "sport", "overshirt", "dungarees"),
    "Dresses": ("dress",),
    "Bottoms": ("trousers", "shorts"),
    "Shoes": ("sneakers", "boots"),
}
OUTFIT_SETS = {
    "Everyday": ("tee", "trousers", "sneakers"),
    "Runner": ("sport", "shorts", "sneakers"),
    "Garden": ("dress", "boots"),
}
LONG_DRESSES = ("dress",)
PART_CHOICES = {
    "Hair": (
        "sprigs",
        "single sprig",
        "double sprigs",
        "fan sprigs",
        "cowlick sprigs",
        "loop sprig",
        "curled sprigs",
        "zigzag sprigs",
        "bob",
        "ponytail",
        "sweep",
        "waves",
        "curls",
        "tuft",
        "spikes",
        "quiff",
        "braids",
        "antenna",
        "orbit",
        "pixie",
        "side part",
        "center part",
        "bowl",
        "buzz",
        "afro",
        "bun",
        "twin buns",
        "pigtails",
        "mohawk",
        "locs",
        "layered bob",
        "spring curl",
        "double curl",
        "coiled fringe",
        "curly ponytail",
        "high ponytail",
        "side curl",
        "none",
    ),
    "Eyes": (
        "soft",
        "dot",
        "anime",
        "round",
        "lashes",
        "narrow",
        "sleepy",
        "happy",
        "robot",
        "almond",
        "wide",
        "half lidded",
        "sparkle",
        "cross",
        "heart",
    ),
    "Mouth": MOUTH_STYLES,
    "Mustache": (
        "None",
        "Pencil",
        "Chevron",
        "Handlebar",
        "Walrus",
        "Horseshoe",
        "English",
        "Dali",
        "Imperial",
        "Toothbrush",
    ),
    "Beard": (
        "None",
        "Goatee",
        "Short",
        "Full",
        "Stubble",
        "Chinstrap",
        "Long",
        "Long full",
        "Pointed",
        "Forked",
        "Braided",
    ),
    "Nose": ("None", "Simple", "Button", "Round", "Pointed", "Long", "Hooked", "Wide"),
}
POSE_CHOICES = {
    "Eyes": ("Open", "Blink", "Wink"),
    "Hands": (
        "Relaxed",
        "Open",
        "Palm out",
        "Fist",
        "Loose fist",
        "Point",
        "Thumbs out",
        "Wave",
        "Curled fist",
    ),
}
REPLACEABLE_PARTS = tuple(PART_CHOICES)


def canonical_hand_pose(value: str) -> str:
    """Resolve retired recipe choices to available art without altering saved project parts."""
    if value in ("Simple fist", "Small fist", "Round hand", "Mitten"):
        return "Loose fist"
    if value in ("Stop", "Flat hand"):
        return "Palm out"
    return value if value in POSE_CHOICES["Hands"] else "Relaxed"


def canonical_view(view: str) -> str:
    """Normalize persisted turnaround aliases while retaining the empty Default slot."""
    value = str(view).strip().casefold().replace("_", " ").replace("-", " ")
    aliases = {
        "front": "Front",
        "front 3/4": "Front 3/4",
        "three quarter": "Front 3/4",
        "side": "Side",
        "profile": "Side",
        "back 3/4": "Back 3/4",
        "rear 3/4": "Back 3/4",
        "back": "Back",
        "behind": "Back",
        "rear": "Back",
        "default": "Default",
        "": "Default",
    }
    if value not in aliases:
        raise ProjectError("Choose Front, Front 3/4, Side, Back 3/4 or Back.")
    return aliases[value]


@dataclass(frozen=True)
class CharacterRecipe:
    """Persist authoring choices; generated media and cache paths are excluded."""

    name: str = "Nova"
    design_id: str = "nova"
    gender: str = "Girl"
    view: str = "Front 3/4"
    style: str = "Classic"
    source_format: str = "SVG"
    artwork_collection: str = "original"
    mouth_pose: str = "Rest"
    parts: Mapping[str, str] = field(default_factory=dict)
    colors: Mapping[str, str] = field(default_factory=dict)
    garment_colors: Mapping[str, Any] = field(default_factory=dict)
    dress: tuple[str, ...] = ()
    worn: Mapping[str, Any] = field(default_factory=dict)
    poses: Mapping[str, Any] = field(default_factory=dict)
    motions: tuple[str, ...] = MOTION_CHOICES
    alternatives: Mapping[str, Any] = field(default_factory=dict)
    feeling: str = "Neutral"
    mouth_style: str = "Soft"
    head_shape: str = "Round"
    body_shape: str = "Rounded rectangle"
    stroke_width: float = 4
    proportions: Mapping[str, float] = field(default_factory=dict)
    layer_modes: Mapping[str, str] = field(default_factory=dict)
    outfit_sets: tuple[str, ...] = ()
    outline_width: float = 1.6
    hand_flips: Mapping[str, Mapping[str, bool]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate source choices before writing cache or project files."""
        for name in ("dress", "motions", "outfit_sets"):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)) or not all(isinstance(v, str) for v in values):
                raise ProjectError("Character selections must be arrays of choice names.")
            object.__setattr__(self, name, tuple(values))
        design_by_id(self.design_id)
        if not isinstance(self.hand_flips, Mapping) or any(
            view not in VIEWS
            or not isinstance(hands, Mapping)
            or any(
                side not in ("left", "right") or type(flip) is not bool
                for side, flip in hands.items()
            )
            for view, hands in self.hand_flips.items()
        ):
            raise ProjectError("Hand mirrors need a supported view and left/right boolean values.")
        from rigora.domain.creator_options import OUTFIT_PRESETS, PLACEMENTS

        if any(name not in OUTFIT_PRESETS for name in self.outfit_sets):
            raise ProjectError("Choose an available coordinated outfit set.")
        if any(
            category not in PLACEMENTS or value not in PLACEMENTS[category]
            for category, value in self.layer_modes.items()
        ):
            raise ProjectError("Choose a supported clothing or accessory placement.")
        canonical_view(self.view)
        if self.source_format != "SVG":
            raise ProjectError("Character Creation uses editable SVG artwork.")
        if self.head_shape not in ("Round", "Oval", "Soft square"):
            raise ProjectError("Choose Round, Oval or Soft square for the head.")
        if self.body_shape not in ("Simple", "Rounded rectangle"):
            raise ProjectError("Choose Simple or Rounded rectangle for the body.")
        if not 3 <= self.stroke_width <= 16:
            raise ProjectError("Stroke width must be between 3 and 16 pixels.")
        if not 0 <= self.outline_width <= 5:
            raise ProjectError("Outline weight must be between zero and five.")
        if any(
            k not in ("head", "body", "width", "arm", "leg") or not 0.65 <= v <= 1.6
            for k, v in self.proportions.items()
        ):
            raise ProjectError("Body proportions must be between 65 and 160 percent.")
        if self.mouth_pose not in MOUTH_POSES or self.mouth_style not in MOUTH_STYLES:
            raise ProjectError("Choose a supported speech shape and mouth set.")
        if self.feeling not in FEELING_PRESETS or any(
            m not in MOTION_CHOICES for m in self.motions
        ):
            raise ProjectError("Choose a supported expression and source action.")
        for color in self.colors.values():
            if (
                len(color) != 7
                or color[0] != "#"
                or any(c not in "0123456789abcdefABCDEF" for c in color[1:])
            ):
                raise ProjectError("Use RGB hexadecimal paint colors.")

    def to_dict(self) -> dict[str, Any]:
        """Serialize reusable choices into project metadata or presets."""
        return asdict(self)

    def wearing(self, family: str) -> str | None:
        """Resolve the visible garment separately from retained alternatives."""
        explicit = self.worn.get(family)
        return (
            explicit
            if isinstance(explicit, str)
            else next((n for n in self.dress if n in DRESS_CHOICES.get(family, ())), None)
        )


def character_preset(name: str) -> CharacterRecipe:
    """Create choices from a Creator design; Template identities remain separate."""
    d = next((d for d in CREATOR_DESIGNS if name in (d.name, d.id)), None)
    if d is None:
        raise ProjectError("Choose a preset from the new Character Creation catalog.")
    return CharacterRecipe(
        name=d.name,
        design_id=d.id,
        style=d.style,
        gender="Robot" if d.anatomy == "robot" else "Girl",
        source_format=d.format,
        colors=d.colors,
    )


def default_character(gender: str) -> CharacterRecipe:
    """Choose an authored silhouette rather than recoloring a single base body."""
    return replace(
        character_preset(
            {"Boy": "kai", "Man": "luca", "Woman": "mabel", "Robot": "orbit"}.get(gender, "nova")
        ),
        gender=gender,
    )


def styled_character(recipe: CharacterRecipe, name: str) -> CharacterRecipe:
    """Change rendering treatment while retaining the independent silhouette."""
    if name not in STYLE_CHOICES:
        raise ProjectError("Choose a supported illustration style.")
    return replace(recipe, style=name)


def with_feeling(recipe: CharacterRecipe, name: str) -> CharacterRecipe:
    """Coordinate brows, eyes and mouth through one editable expression choice."""
    return replace(recipe, feeling=name)


def feeling_for(recipe: CharacterRecipe) -> str:
    """Return the coordinated expression selected by this recipe."""
    return recipe.feeling


def garment_role(family: str) -> str:
    """Resolve an independent wardrobe paint slot."""
    return {"Tops": "Top", "Dresses": "Top", "Bottoms": "Bottom", "Shoes": "Shoes"}.get(
        family, "Accent"
    )


def component_poster(category: str, choice: str) -> str:
    """Return a cache identity instead of a source-tree PNG path."""
    return f"component/{category}/{choice}"
