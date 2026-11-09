"""Render the owner's paired SVG hands with color and wrist registration only."""

from functools import cache
from html import escape
from xml.etree import ElementTree as ET

from rigora.domain.character_recipe import canonical_hand_pose
from rigora.resources import asset_path

SOURCE_HANDS = {
    "Open": ("hand-01", "hand-02"),
    "Loose fist": ("hand-03", "hand-04"),
    "Relaxed": ("hand-05", "hand-06"),
    "Wave": ("hand-07", "hand-08"),
    "Curled fist": ("hand-09", "hand-10"),
    "Palm out": ("hand-11", "hand-12"),
    "Point": ("hand-13", "hand-14"),
    "Fist": ("hand-15", "hand-16"),
    "Thumbs out": ("hand-17", "hand-18"),
}

FORWARD_THUMB_POSES = frozenset(SOURCE_HANDS)

PAIRED_SOURCES = {
    "Front": dict.fromkeys(("Open", "Fist", "Point", "Thumbs out"), "R"),
    "Back": dict.fromkeys(("Open", "Fist", "Point", "Thumbs out"), "L"),
}
REFLECTED_PARTNERS = {"Front 3/4": frozenset((pose, "L") for pose in ("Loose fist", "Curled fist"))}


def hand_placement(view: str, pose: str, side: str, flip: bool = False) -> tuple[str, bool]:
    """Resolve approved source registration plus a per-view mirror at the local wrist."""
    unreflected = (
        pose in FORWARD_THUMB_POSES if view in ("Front 3/4", "Side", "Back 3/4") else side == "R"
    )
    unreflected ^= (pose, side) in REFLECTED_PARTNERS.get(view, ())
    return PAIRED_SOURCES.get(view, {}).get(pose, side), unreflected != flip


@cache
def _source_hands() -> dict[str, tuple[str, str]]:
    """Read packaged vectors once, preserving every supplied layer and path attribute."""
    root = ET.parse(asset_path("characters/hands/cartoon-gloves.svg")).getroot()
    hands = {}
    for group in root.findall("{http://www.w3.org/2000/svg}g"):
        for path in group:
            path.tag = "path"
        markup = "".join(ET.tostring(path, encoding="unicode") for path in group)
        markup = markup.replace("#0D0C0A", "{ink}").replace("#ffffff", "{fill}")
        hands[group.attrib["id"]] = (group.attrib["data-bind-transform"], markup)
    return hands


def glove_art(
    near: bool,
    pose: str,
    ink: str,
    width: float,
    fill: str,
    *,
    palm: bool = True,
    side: str = "R",
) -> str:
    """Place one supplied hand at the wrist without synthesizing or removing details.

    ``side`` chooses the original partner; ``near`` applies view reflection.
    Width and surface hints remain accepted for existing authoring callers, but
    the supplied vectors own their outline weight and visible surface details.
    """
    pair = SOURCE_HANDS[canonical_hand_pose(pose)]
    identity = pair[side == "L"]
    transform, markup = _source_hands()[identity]
    markup = markup.format(ink=escape(ink), fill=escape(fill))
    return (
        f'<g data-source-hand="{identity}" transform="scale({1 if near else -1} 1)">'
        f'<g transform="{transform}">{markup}</g></g>'
    )
