"""Original flat SVG props and geometric silhouettes, generated without stored raster artwork."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectArt:
    """Own one original vector composition and its browser category and semantic family."""

    name: str
    category: str
    body: str
    family: str = ""


def svg(body: str) -> bytes:
    """Wrap authored geometry in a transparent, fixed-coordinate, self-contained SVG."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" '
        'viewBox="0 0 256 256">' + body + "</svg>"
    ).encode()


def rect(x: float, y: float, w: float, h: float, fill: str, radius: float = 5) -> str:
    """Create a flat rounded rectangle with no decorative shading."""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}"/>'


def ellipse(x: float, y: float, rx: float, ry: float, fill: str) -> str:
    """Create a solid ellipse, including circles when the radii match."""
    return f'<ellipse cx="{x}" cy="{y}" rx="{rx}" ry="{ry}" fill="{fill}"/>'


def path(data: str, fill: str, stroke: str = "", width: float = 4) -> str:
    """Create an original filled silhouette or rounded outline."""
    return (
        f'''<path d="{data}" fill="{fill}" stroke="{stroke or "none"}" '''
        f'stroke-width="{width}" stroke-linecap="round" '
        f'stroke-linejoin="round"/>'
    )


def polygon(points: list[tuple[float, float]], fill: str) -> str:
    """Serialize a closed polygon with concise coordinates for readable exported SVG."""
    return (
        '<polygon points="' + " ".join(f"{x:.3f},{y:.3f}" for x, y in points) + f'" fill="{fill}"/>'
    )


def radial(count: int, inner: float = 0) -> str:
    """Generate a regular polygon or alternating-radius star centered on the artboard."""
    total = count * 2 if inner else count
    return polygon(
        [
            (
                128
                + math.cos(math.tau * i / total - math.pi / 2) * (inner if inner and i % 2 else 92),
                128
                + math.sin(math.tau * i / total - math.pi / 2) * (inner if inner and i % 2 else 92),
            )
            for i in range(total)
        ],
        "#acb7c0",
    )


def shapes() -> tuple[ObjectArt, ...]:
    """Provide different silhouettes rather than inflating counts with palette duplicates."""
    fill = "#acb7c0"
    values = {
        "Circle": ellipse(128, 128, 90, 90, fill),
        "Ellipse": ellipse(128, 128, 108, 65, fill),
        "Square": rect(38, 38, 180, 180, fill, 0),
        "Rounded square": rect(38, 38, 180, 180, fill, 35),
        "Rectangle": rect(22, 65, 212, 126, fill, 0),
        "Rounded rectangle": rect(22, 65, 212, 126, fill, 27),
        "Capsule": rect(22, 80, 212, 96, fill, 48),
        "Right triangle": path("M38 38 L218 218 H38Z", fill),
        "Diamond": path("M128 20 L224 128 128 236 32 128Z", fill),
        "Parallelogram": path("M75 45 H230 L181 211 H26Z", fill),
        "Trapezoid": path("M77 50 H179 L230 206 H26Z", fill),
        "Semicircle": path("M28 160 A100 100 0 0 1 228 160Z", fill),
        "Crescent": path("M172 30 A100 100 0 1 0 205 195 A93 93 0 0 1 172 30Z", fill),
        "Heart": path(
            (
                "M128 218 C100 192 27 144 27 92 C27 27 103 23 128 77 C153 23 229 27 229"
                " 92 C229 144 156 192 128 218Z"
            ),
            fill,
        ),
        "Teardrop": path(
            "M128 24 C111 75 49 119 49 167 A79 66 0 0 0 207 167 C207 119 145 75 128 24Z", fill
        ),
        "Shield": path("M128 22 L218 58 V126 Q218 198 128 234 Q38 198 38 126 V58Z", fill),
        "Cloud": path(
            (
                "M63 195 C8 195 14 119 64 124 C55 60 139 39 162 94 C209 66 250 112 222 "
                "145 C260 184 203 202 181 195Z"
            ),
            fill,
        ),
        "Speech bubble": path(
            (
                "M48 40 H208 Q230 40 230 62 V164 Q230 186 208 186 H112 L63 222 74 186 "
                "H48 Q26 186 26 164 V62 Q26 40 48 40Z"
            ),
            fill,
        ),
        "Thought bubble": ellipse(128, 104, 101, 71, fill)
        + ellipse(67, 196, 19, 19, fill)
        + ellipse(39, 227, 10, 10, fill),
        "Ring": (
            '<path fill-rule="evenodd" d="M128 28 A100 100 0 1 0 128 228 A100 100 0'
            ' 1 0 128 28 M128 67 A61 61 0 1 1 128 189 A61 61 0 1 1 128 67" fill="'
        )
        + fill
        + '"/>',
        "Plus": path("M98 28 H158 V98 H228 V158 H158 V228 H98 V158 H28 V98 H98Z", fill),
        "Lightning": path("M143 18 L43 147 H112 L95 238 215 100 H144Z", fill),
        "Chevron": path("M60 28 H117 L206 128 117 228 H60 L149 128Z", fill),
        "Location pin": path(
            "M128 232 C94 182 52 139 52 94 A76 76 0 0 1 204 94 C204 139 162 182 128 232Z", fill
        )
        + ellipse(128, 96, 28, 28, "#3e4b58"),
    }
    for count, label in (
        (3, "Triangle"),
        (5, "Pentagon"),
        (6, "Hexagon"),
        (7, "Heptagon"),
        (8, "Octagon"),
        (10, "Decagon"),
    ):
        values[label] = radial(count)
    for points in (4, 5, 6, 8, 12):
        values[f"Star · {points} points"] = radial(points, 43)
    arrow = path("M25 99 H135 V47 L235 128 135 209 V157 H25Z", fill)
    for angle, name in ((0, "Right"), (90, "Down"), (180, "Left"), (270, "Up")):
        values[name + " arrow"] = f'<g transform="rotate({angle} 128 128)">{arrow}</g>'
    return tuple(ObjectArt(name, "Shapes", body, "shapes") for name, body in values.items())


def props() -> tuple[ObjectArt, ...]:
    """Author furniture, tools, outdoor, food, vehicle and adventure Object sources."""
    brown, wood, ink, metal, green, blue = (
        "#806044",
        "#b88b60",
        "#303741",
        "#a2adb8",
        "#6d9b68",
        "#6d9eaf",
    )
    values: list[ObjectArt] = []

    def add(category: str, name: str, body: str, family: str = "household") -> None:
        """Retain each composition's category and optional existing family filter."""
        values.append(ObjectArt(name, category, body, family))

    home = "Home & interiors"
    add(
        home,
        "Chair",
        rect(65, 34, 126, 112, wood)
        + rect(54, 143, 148, 24, brown)
        + rect(66, 166, 17, 66, brown)
        + rect(173, 166, 17, 66, brown),
    )
    add(
        home,
        "Dining table",
        rect(25, 86, 206, 27, wood)
        + rect(43, 112, 18, 112, brown)
        + rect(195, 112, 18, 112, brown),
    )
    add(
        home,
        "Round table",
        ellipse(128, 84, 104, 38, wood)
        + rect(116, 100, 24, 112, brown)
        + rect(65, 211, 126, 15, brown),
    )
    add(
        home,
        "Sofa",
        rect(30, 76, 196, 100, blue, 24)
        + rect(20, 126, 38, 78, blue, 16)
        + rect(198, 126, 38, 78, blue, 16)
        + rect(59, 140, 138, 52, "#87acba", 12)
        + rect(39, 202, 18, 27, brown)
        + rect(199, 202, 18, 27, brown),
    )
    add(
        home,
        "Bed",
        rect(29, 61, 198, 153, wood)
        + rect(38, 80, 180, 115, "#e5e0d5", 12)
        + rect(45, 87, 67, 34, "#faf8ef", 10)
        + rect(120, 87, 86, 34, "#faf8ef", 10)
        + rect(38, 129, 180, 66, blue)
        + rect(30, 213, 17, 20, brown)
        + rect(209, 213, 17, 20, brown),
    )
    add(
        home,
        "Wardrobe",
        rect(49, 28, 158, 203, wood)
        + rect(57, 36, 68, 185, brown)
        + rect(132, 36, 67, 185, brown)
        + rect(111, 113, 7, 25, metal)
        + rect(139, 113, 7, 25, metal),
    )
    shelf = rect(44, 23, 168, 212, brown) + rect(54, 33, 148, 190, "#cfb08c")
    for y in (79, 139, 199):
        shelf += (
            rect(54, y, 148, 8, brown)
            + rect(63, y - 39, 18, 39, blue)
            + rect(85, y - 47, 17, 47, green)
            + rect(107, y - 34, 23, 34, "#b97869")
            + rect(136, y - 43, 16, 43, wood)
        )
    add(home, "Bookshelf", shelf)
    add(
        home,
        "Floor lamp",
        rect(121, 97, 14, 119, metal)
        + ellipse(128, 222, 54, 11, ink)
        + path("M83 33 H173 L205 109 H51Z", "#dfc487"),
    )
    add(
        home,
        "Desk computer",
        rect(29, 43, 198, 124, ink, 10)
        + rect(39, 53, 178, 101, blue)
        + rect(115, 167, 26, 35, metal)
        + rect(77, 202, 102, 12, metal)
        + rect(50, 224, 156, 12, ink),
    )
    add(
        home,
        "Television",
        rect(22, 59, 212, 133, ink, 12)
        + rect(33, 70, 190, 109, "#7d99a3", 6)
        + path("M75 192 L58 219 M181 192 L198 219", "none", ink, 12),
    )
    add(
        home,
        "Wall clock",
        ellipse(128, 128, 99, 99, brown)
        + ellipse(128, 128, 86, 86, "#f0eee6")
        + path("M128 64 V128 L172 150", "none", ink, 8)
        + ellipse(128, 128, 8, 8, ink),
    )
    add(
        home,
        "Mirror",
        ellipse(128, 113, 78, 98, wood)
        + ellipse(128, 113, 66, 85, "#9bbdc4")
        + rect(83, 214, 90, 13, brown),
    )
    add(
        home,
        "Picture frame",
        rect(29, 42, 198, 172, wood)
        + rect(42, 55, 172, 146, "#d5dfd9")
        + ellipse(164, 91, 20, 20, "#d9b86e")
        + path("M42 183 L88 116 131 162 171 127 214 187 V201 H42Z", green),
    )
    add(
        home,
        "Door",
        rect(54, 24, 148, 214, brown)
        + rect(64, 34, 128, 196, wood)
        + rect(79, 50, 98, 83, brown)
        + rect(79, 148, 98, 65, brown)
        + ellipse(177, 143, 7, 7, "#d0b168"),
    )
    add(
        home,
        "Window",
        rect(30, 31, 196, 191, wood)
        + rect(42, 43, 172, 167, "#9ebfca")
        + rect(121, 43, 14, 167, wood)
        + rect(42, 119, 172, 14, wood)
        + rect(20, 222, 216, 14, brown),
    )
    add(
        home,
        "Cabinet",
        rect(32, 68, 192, 155, wood)
        + rect(44, 81, 168, 43, brown)
        + rect(44, 136, 79, 74, brown)
        + rect(134, 136, 78, 74, brown)
        + rect(112, 97, 32, 9, metal)
        + rect(100, 165, 11, 25, metal)
        + rect(146, 165, 11, 25, metal),
    )
    environment = "Environment"
    add(
        environment,
        "Pine tree",
        rect(117, 162, 22, 71, brown)
        + path("M128 20 L211 145 H179 L230 199 H26 L77 145 H45Z", green),
        "trees",
    )
    add(
        environment,
        "Oak tree",
        rect(115, 133, 26, 101, brown)
        + ellipse(80, 102, 58, 61, green)
        + ellipse(167, 103, 61, 62, green)
        + ellipse(128, 65, 64, 53, "#7ca673"),
        "trees",
    )
    add(
        environment,
        "Birch tree",
        rect(117, 74, 23, 159, "#e4ded0")
        + path("M119 124 H132 M128 166 H139 M119 207 H130", "none", brown, 6)
        + ellipse(128, 65, 77, 49, green),
        "trees",
    )
    add(
        environment,
        "Palm tree",
        path("M110 235 Q143 140 123 65 H139 Q165 164 135 235Z", wood)
        + path(
            (
                "M132 71 Q60 11 25 94 Q84 65 132 80 Q201 14 235 92 Q173 66 132 80 Q180 "
                "57 201 133 Q153 88 132 80 Q83 66 64 145 Q116 88 132 71Z"
            ),
            green,
        ),
        "trees",
    )
    add(
        environment,
        "Bush",
        ellipse(67, 166, 45, 53, green)
        + ellipse(128, 141, 64, 78, "#80a971")
        + ellipse(190, 170, 45, 49, green),
        "bushes",
    )
    add(
        environment,
        "Grass tuft",
        path(
            (
                "M30 223 Q58 182 39 133 Q92 164 103 202 Q102 115 129 62 Q142 152 146 "
                "192 Q177 130 213 133 Q184 185 226 223Z"
            ),
            green,
        ),
        "bushes",
    )
    add(
        environment,
        "Mushroom",
        rect(113, 124, 31, 101, "#dcccae", 14)
        + path("M24 141 C26 6 230 6 232 141Z", "#b96a60")
        + ellipse(78, 104, 14, 12, "#eee4ce")
        + ellipse(145, 72, 16, 13, "#eee4ce")
        + ellipse(190, 118, 11, 10, "#eee4ce"),
        "bushes",
    )
    petals = "".join(
        ellipse(
            128 + 42 * math.cos(i * math.tau / 6),
            82 + 42 * math.sin(i * math.tau / 6),
            28,
            28,
            "#d6a183",
        )
        for i in range(6)
    )
    add(
        environment,
        "Flower",
        rect(121, 96, 14, 138, green)
        + path(
            "M123 190 Q48 178 68 145 Q113 144 123 190 M134 207 Q198 194 191 162 Q151 158 134 207",
            green,
        )
        + petals
        + ellipse(128, 82, 28, 28, "#d6bb70"),
        "bushes",
    )
    add(
        environment,
        "Leaf",
        path("M43 208 Q8 51 216 29 Q239 195 43 208Z", green)
        + path("M43 208 L176 72", "none", "#b1ca91", 7),
        "bushes",
    )
    add(
        environment,
        "Cactus",
        rect(109, 28, 38, 200, green, 19)
        + path(
            "M112 141 H65 Q45 141 45 120 V88 M143 174 H191 Q211 174 211 152 V115", "none", green, 28
        ),
        "bushes",
    )
    add(
        environment,
        "Rock",
        path("M25 209 L42 111 107 59 180 77 229 159 221 209Z", "#929b9f"),
        "terrain",
    )
    add(
        environment,
        "Boulder",
        path("M21 202 Q4 108 77 58 Q166 4 226 95 Q261 155 225 215Z", "#828e91"),
        "terrain",
    )
    add(environment, "Hill", path("M11 225 Q43 97 128 110 Q208 97 245 225Z", green), "terrain")
    add(
        environment,
        "Mountain",
        path("M15 226 L126 28 241 226Z", "#89949a")
        + path("M126 28 L172 108 145 99 128 122 104 97 80 110Z", "#e1e9e8"),
        "terrain",
    )
    add(environment, "Cloud", shapes()[16].body, "weather")
    rays = "".join(
        path(
            (
                f"M{128 + 80 * math.cos(i * math.pi / 4):.2f} "
                f"{128 + 80 * math.sin(i * math.pi / 4):.2f} L"
                f"{128 + 104 * math.cos(i * math.pi / 4):.2f} "
                f"{128 + 104 * math.sin(i * math.pi / 4):.2f}"
            ),
            "none",
            "#d9bb70",
            10,
        )
        for i in range(8)
    )
    add(environment, "Sun", rays + ellipse(128, 128, 62, 62, "#e3c66f"), "weather")
    add(environment, "Moon", shapes()[12].body.replace("#acb7c0", "#d5d8c1"), "weather")
    adventure = "Adventure props"
    add(
        adventure,
        "Treasure chest",
        rect(34, 104, 188, 115, brown)
        + path("M34 108 V79 Q34 34 79 34 H177 Q222 34 222 79 V108Z", wood)
        + rect(61, 35, 15, 184, "#d2b774")
        + rect(180, 35, 15, 184, "#d2b774")
        + rect(116, 99, 25, 48, "#d2b774"),
    )
    add(
        adventure,
        "Wooden crate",
        rect(33, 33, 190, 190, brown)
        + rect(45, 45, 166, 166, wood)
        + path("M51 51 L205 205 M205 51 L51 205", "none", brown, 19),
    )
    add(
        adventure,
        "Barrel",
        path("M65 34 Q24 128 65 223 H191 Q232 128 191 34Z", wood)
        + rect(48, 69, 160, 16, metal)
        + rect(43, 172, 170, 16, metal),
    )
    add(
        adventure,
        "Key",
        ellipse(79, 89, 49, 49, "#cdb16c")
        + ellipse(79, 89, 24, 24, "#4e5963")
        + path("M110 119 L214 221 M171 178 L191 158 M193 200 L214 179", "none", "#cdb16c", 20),
    )
    add(
        adventure,
        "Padlock",
        path("M77 115 V78 A51 51 0 0 1 179 78 V115", "none", metal, 20)
        + rect(55, 108, 146, 124, "#d4b86b", 15)
        + ellipse(128, 160, 12, 12, ink)
        + rect(121, 163, 14, 28, ink),
    )
    add(
        adventure,
        "Ladder",
        rect(55, 20, 17, 216, wood)
        + rect(184, 20, 17, 216, wood)
        + "".join(rect(68, y, 120, 14, brown) for y in (47, 88, 129, 170, 211)),
    )
    add(
        adventure,
        "Shovel",
        rect(120, 30, 16, 139, wood)
        + path("M88 151 H168 V183 Q168 213 128 236 Q88 213 88 183Z", metal)
        + path("M105 26 H151 V61 H105Z", "none", metal, 10),
    )
    add(
        adventure,
        "Pickaxe",
        path("M58 218 L158 57", "none", wood, 20)
        + path("M56 67 Q134 3 225 110 Q149 66 56 67Z", metal),
    )
    add(
        adventure,
        "Axe",
        path("M56 225 L162 34", "none", wood, 20)
        + path("M132 53 Q178 59 215 112 L181 150 Q148 112 108 97Z", metal),
    )
    add(
        adventure,
        "Hammer",
        path("M126 220 V80", "none", wood, 24) + rect(52, 38, 155, 58, metal, 7),
    )
    add(
        adventure,
        "Sword",
        path("M118 173 V42 L128 17 139 42 V173Z", metal)
        + rect(82, 161, 92, 17, "#b59a62")
        + rect(119, 179, 18, 51, brown)
        + ellipse(128, 231, 17, 10, "#b59a62"),
    )
    add(
        adventure,
        "Shield",
        shapes()[15].body.replace("#acb7c0", metal)
        + path("M128 51 L189 76 V132 Q184 178 128 201 Q72 178 67 132 V76Z", blue),
    )
    add(
        adventure,
        "Bow",
        path("M69 28 Q235 128 69 228", "none", wood, 16)
        + path("M69 28 L100 128 69 228", "none", "#d7d4c6", 4),
    )
    add(
        adventure,
        "Arrow",
        path(
            "M26 128 H225 M193 101 L225 128 193 155 M59 128 L32 105 M59 128 L32 151",
            "none",
            wood,
            10,
        ),
    )
    add(
        adventure,
        "Book",
        rect(51, 29, 157, 200, brown)
        + rect(66, 29, 142, 188, blue)
        + rect(64, 213, 144, 12, "#e6dec7")
        + rect(87, 63, 100, 12, "#d3ba7d"),
    )
    add(
        adventure,
        "Scroll",
        rect(63, 45, 129, 162, "#dfcfaa")
        + ellipse(64, 45, 27, 17, wood)
        + ellipse(192, 207, 27, 17, wood)
        + path("M89 85 H168 M89 112 H168 M89 139 H156", "none", brown, 6),
    )
    add(
        adventure,
        "Tent",
        path("M12 225 L128 37 244 225Z", "#b88b64")
        + path("M128 37 L187 225 H66Z", "#454e54")
        + path("M128 37 L66 225 128 207Z", "#d0ab79"),
    )
    food = "Food & drink"
    add(
        food,
        "Apple",
        ellipse(95, 142, 62, 77, "#be7167")
        + ellipse(159, 142, 62, 77, "#be7167")
        + path("M126 86 Q119 50 138 26", "none", brown, 12)
        + path("M137 54 Q183 12 205 49 Q171 80 137 54", green),
        "fruits",
    )
    add(
        food,
        "Pear",
        path(
            (
                "M128 44 C91 44 109 104 74 129 C15 177 60 235 128 230 C196 235 241 177 "
                "182 129 C147 104 165 44 128 44Z"
            ),
            "#b6bc72",
        )
        + path("M129 49 Q121 28 139 17", "none", brown, 10),
        "fruits",
    )
    add(
        food,
        "Banana",
        path("M40 40 Q93 170 221 121 Q199 224 99 210 Q34 194 40 40Z", "#d6bc69"),
        "fruits",
    )
    add(
        food,
        "Orange",
        ellipse(128, 140, 86, 86, "#d89b59")
        + path("M126 54 Q145 12 186 38 Q160 72 126 54Z", green),
        "fruits",
    )
    add(
        food,
        "Lemon",
        path("M24 139 Q28 68 111 53 Q199 39 232 116 Q225 190 145 207 Q55 217 24 139Z", "#ddc96e"),
        "fruits",
    )
    add(
        food,
        "Strawberry",
        path("M39 98 Q49 42 128 64 Q205 42 217 98 Q206 178 128 230 Q50 178 39 98Z", "#bd7168")
        + path("M69 76 L94 38 128 70 155 33 183 76 149 90 128 75 105 96Z", green),
        "fruits",
    )
    add(
        food,
        "Carrot",
        path("M84 82 Q130 46 176 82 L116 235Z", "#d39761")
        + path("M123 75 L96 25 M130 70 L136 16 M138 77 L178 32", "none", green, 17),
        "fruits",
    )
    add(
        food,
        "Bread loaf",
        rect(27, 83, 202, 131, "#bd925f", 35)
        + path("M70 106 L87 143 M115 99 L132 137 M160 104 L177 141", "none", "#e0bd86", 10),
    )
    add(
        food,
        "Cheese",
        path("M34 186 L41 89 214 50 V186Z", "#d5b96e")
        + path("M41 89 L214 50 214 110Z", "#e5ca83")
        + ellipse(87, 139, 14, 14, "#b79353")
        + ellipse(161, 153, 18, 18, "#b79353"),
    )
    add(
        food,
        "Fish",
        path("M33 139 L13 95 61 110 Q136 31 222 128 Q137 218 61 147 L13 171Z", blue)
        + ellipse(182, 122, 8, 8, ink),
    )
    add(
        food,
        "Bottle",
        path("M100 23 H156 V71 Q185 86 185 119 V225 H71 V119 Q71 86 100 71Z", blue)
        + rect(97, 20, 62, 22, metal)
        + rect(81, 132, 94, 62, "#e6dcca"),
        "drinkware",
    )
    add(
        food,
        "Mug",
        path("M181 86 H206 Q249 86 227 149 Q216 168 181 166", "none", wood, 18)
        + rect(39, 65, 151, 160, "#b68a75", 15),
        "drinkware",
    )
    vehicles = "Vehicles"

    def wheel(x: float) -> str:
        """Use matching tires and hubs for the original road vehicles."""
        return ellipse(x, 198, 29, 29, ink) + ellipse(x, 198, 13, 13, metal)

    add(
        vehicles,
        "Car",
        path("M24 123 L63 104 88 63 H165 L196 105 231 126 V193 H24Z", blue)
        + path("M97 75 H157 L180 108 H77Z", "#c2d9dd")
        + wheel(71)
        + wheel(189),
    )
    add(
        vehicles,
        "Bus",
        rect(19, 51, 218, 153, "#c9a86b", 14)
        + "".join(rect(x, 67, 40, 57, "#b7d0d7", 3) for x in (31, 81, 131))
        + rect(186, 68, 36, 127, "#536b78")
        + wheel(65)
        + wheel(193),
    )
    add(
        vehicles,
        "Van",
        path("M23 66 H153 L199 112 H234 V194 H23Z", "#b3b9b4")
        + path("M159 80 L187 114 H159Z", blue)
        + rect(41, 83, 88, 52, blue)
        + wheel(67)
        + wheel(191),
    )
    add(
        vehicles,
        "Truck",
        rect(13, 59, 135, 128, wood)
        + path("M154 94 H200 L239 137 V189 H154Z", blue)
        + path("M168 109 H194 L220 139 H168Z", "#c4d7d9")
        + wheel(58)
        + wheel(195),
    )
    add(
        vehicles,
        "Bicycle",
        ellipse(54, 178, 42, 42, "none")
        + path(
            "M54 178 L94 104 142 178 H54 L115 129 H174 L201 178 M94 104 H80 M168 128 L158 76 H184",
            "none",
            blue,
            9,
        )
        + ellipse(54, 178, 42, 42, "none").replace("/>", ' stroke="#303741" stroke-width="8"/>')
        + ellipse(201, 178, 42, 42, "none").replace("/>", ' stroke="#303741" stroke-width="8"/>'),
    )
    add(
        vehicles,
        "Boat",
        path("M15 143 H241 L206 210 H59Z", brown)
        + rect(76, 86, 103, 57, wood)
        + rect(102, 55, 49, 32, blue),
    )
    add(
        vehicles,
        "Sailboat",
        path("M16 179 H240 L206 222 H54Z", brown)
        + rect(122, 22, 10, 157, wood)
        + path("M116 31 L30 164 H116Z", "#e7e1d1")
        + path("M140 49 L215 164 H140Z", "#ba8970"),
    )
    add(
        vehicles,
        "Rocket",
        path("M89 192 V89 Q91 46 128 15 Q165 46 167 89 V192Z", "#c1c9c8")
        + path("M89 142 L55 207 H90 M167 142 L201 207 H166Z", blue)
        + ellipse(128, 103, 25, 25, blue)
        + path("M112 197 L128 243 144 197Z", "#d4a368"),
    )
    for name, body in (
        (
            "Football",
            ellipse(128, 128, 92, 92, "#deddd3")
            + radial(5, 0)
            .replace("#acb7c0", ink)
            .replace('points="', 'transform="translate(64 64) scale(.5)" points="'),
        ),
        (
            "Basketball",
            ellipse(128, 128, 92, 92, "#bf9469")
            + path(
                "M36 128 H220 M128 36 V220 M64 61 Q176 128 64 195 M192 61 Q80 128 192 195",
                "none",
                brown,
                6,
            ),
        ),
        (
            "Tennis ball",
            ellipse(128, 128, 85, 85, "#bac68b")
            + path("M66 70 Q163 128 66 186 M190 70 Q93 128 190 186", "none", "#e9ecd9", 9),
        ),
    ):
        add("Props & accessories", name, body, "balls")
    return tuple(values)


def original_objects() -> tuple[ObjectArt, ...]:
    """Return the complete original static SVG catalog in stable category order."""
    return (*shapes(), *props())
