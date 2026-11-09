"""Independent, original SVG stick-character silhouettes and motion identities."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Design:
    """Own a silhouette, seven independent paints and a continuous performance profile."""

    id: str
    name: str
    collection: str
    anatomy: str = "human"
    style: str = "Classic"
    format: str = "SVG"
    palette: tuple[str, ...] = (
        "#ffffff",
        "#191919",
        "#82a49b",
        "#536678",
        "#d4aa65",
        "#4b4b4b",
        "#191919",
    )
    head: float = 29
    body: float = 83
    width: float = 48
    leg: float = 52
    arm: float = 40
    hair: str = "sprigs"
    outfit: str = "none"
    eye: str = "soft"
    body_shape: str = "Rounded rectangle"
    walk_frames: int = 48
    run_frames: int = 28
    stride: float = 45
    lean: float = 20
    energy: float = 1
    phase: float = 0

    @property
    def colors(self) -> dict[str, str]:
        """Return fresh named paints for skin, hair, clothing, accents, shoes and linework."""
        return dict(
            zip(
                ("Skin", "Hair", "Top", "Bottom", "Accent", "Shoes", "Ink"),
                self.palette,
                strict=True,
            )
        )


TEMPLATE_DESIGNS = (
    Design(
        "aiko",
        "Dash · Runner",
        "templates",
        style="Color",
        hair="ponytail",
        outfit="sport",
        walk_frames=44,
        run_frames=24,
        stride=51,
        lean=25,
        energy=1.12,
    ),
    Design(
        "ren",
        "Scout · Explorer",
        "templates",
        style="Color",
        head=27,
        body=91,
        leg=59,
        arm=44,
        hair="sweep",
        outfit="hoodie",
        walk_frames=54,
        run_frames=30,
        stride=49,
        lean=23,
        phase=0.24,
    ),
    Design(
        "iris",
        "Willow · Dancer",
        "templates",
        style="Outline",
        head=30,
        body=78,
        width=43,
        leg=53,
        arm=40,
        hair="waves",
        outfit="dress",
        walk_frames=58,
        run_frames=34,
        stride=36,
        lean=16,
        energy=0.8,
        phase=0.48,
    ),
    Design(
        "otto",
        "Reed · Tall sketch",
        "templates",
        style="Sketch",
        head=26,
        body=98,
        width=40,
        leg=65,
        arm=49,
        hair="tuft",
        walk_frames=62,
        run_frames=32,
        stride=53,
        lean=22,
        energy=0.9,
        phase=0.86,
    ),
    Design(
        "pip",
        "Bolt · Stick robot",
        "templates",
        anatomy="robot",
        style="Color",
        head=29,
        body=70,
        width=53,
        leg=42,
        arm=35,
        hair="antenna",
        outfit="shell",
        walk_frames=42,
        run_frames=26,
        stride=30,
        lean=15,
        energy=0.7,
        phase=0.3,
    ),
    Design(
        "sumi",
        "Whisk · Stick cat",
        "templates",
        anatomy="cat",
        style="Classic",
        head=24,
        body=80,
        width=36,
        leg=32,
        arm=30,
        hair="cat",
        walk_frames=56,
        run_frames=28,
        stride=29,
        energy=0.8,
        phase=0.13,
    ),
    Design(
        "ember",
        "Spark · Stick fox",
        "templates",
        anatomy="fox",
        style="Color",
        head=23,
        body=96,
        width=34,
        leg=39,
        arm=37,
        hair="fox",
        walk_frames=48,
        run_frames=24,
        stride=42,
        energy=1.1,
        phase=0.4,
    ),
    Design(
        "mochi",
        "Hop · Stick rabbit",
        "templates",
        anatomy="rabbit",
        style="Outline",
        head=27,
        body=65,
        width=42,
        leg=27,
        arm=28,
        hair="lop",
        walk_frames=50,
        run_frames=32,
        stride=27,
        energy=1.05,
        phase=0.7,
    ),
)

# Creator identities are deliberately separate from portable Template entries.
CREATOR_DESIGNS = (
    Design("nova", "Classic", "creator"),
    Design(
        "kai",
        "Sport",
        "creator",
        style="Color",
        head=28,
        body=87,
        leg=56,
        arm=43,
        hair="spikes",
        outfit="sport",
        walk_frames=44,
        run_frames=24,
        stride=50,
        lean=27,
        energy=1.15,
        phase=0.55,
    ),
    Design(
        "mabel",
        "Ribbon",
        "creator",
        style="Color",
        head=31,
        body=76,
        width=45,
        leg=49,
        arm=38,
        hair="bob",
        outfit="dress",
        walk_frames=60,
        run_frames=34,
        stride=37,
        lean=17,
        energy=0.8,
        phase=0.8,
    ),
    Design(
        "luca",
        "Tall",
        "creator",
        style="Outline",
        head=26,
        body=99,
        width=44,
        leg=65,
        arm=49,
        hair="quiff",
        outfit="jacket",
        walk_frames=56,
        run_frames=30,
        stride=55,
        lean=24,
        phase=1.1,
    ),
    Design(
        "dot",
        "Little",
        "creator",
        style="Sketch",
        head=32,
        body=60,
        width=42,
        leg=38,
        arm=30,
        hair="braids",
        outfit="dungarees",
        walk_frames=46,
        run_frames=26,
        stride=31,
        lean=18,
        energy=1.05,
        phase=0.33,
    ),
    Design(
        "orbit",
        "Orbit",
        "creator",
        anatomy="robot",
        style="Color",
        head=30,
        body=73,
        width=55,
        leg=43,
        arm=36,
        hair="orbit",
        outfit="shell",
        walk_frames=52,
        run_frames=32,
        stride=29,
        lean=14,
        energy=0.65,
        phase=0.68,
    ),
    Design(
        "tansy",
        "Fox",
        "creator",
        anatomy="fox",
        style="Sketch",
        head=26,
        body=81,
        width=38,
        leg=32,
        arm=31,
        hair="fox",
        walk_frames=56,
        stride=33,
        lean=11,
        energy=0.95,
        phase=0.87,
    ),
    Design(
        "bean",
        "Cat",
        "creator",
        anatomy="cat",
        style="Color",
        head=29,
        body=65,
        width=44,
        leg=25,
        arm=25,
        hair="cat",
        walk_frames=54,
        run_frames=34,
        stride=24,
        lean=7,
        energy=0.85,
        phase=0.24,
    ),
    Design(
        "clover",
        "Rabbit",
        "creator",
        anatomy="rabbit",
        style="Classic",
        head=26,
        body=73,
        width=38,
        leg=31,
        arm=29,
        hair="upright",
        walk_frames=52,
        run_frames=30,
        stride=30,
        lean=13,
        energy=1.1,
        phase=0.62,
    ),
)

DESIGNS = {d.id: d for d in (*TEMPLATE_DESIGNS, *CREATOR_DESIGNS)}


def design_by_id(identity: str) -> Design:
    """Resolve an authored identity without loading retired catalogs or reference images."""
    from rigora.domain.validation import ProjectError

    if identity not in DESIGNS:
        raise ProjectError("This design was retired. Choose a character from the SVG catalog.")
    return DESIGNS[identity]


def customized_design(
    identity: str, style: str, proportions: dict[str, float], body_shape: str = "Rounded rectangle"
) -> Design:
    """Apply bounded recipe proportions before both rest-art and action evaluation."""
    d = design_by_id(identity)
    return replace(
        d,
        style=style,
        body_shape=body_shape,
        **{field: getattr(d, field) * factor for field, factor in proportions.items()},
    )
