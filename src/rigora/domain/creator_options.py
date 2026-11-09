"""Shared visual option catalogs and default/retained-choice rules for SVG authoring."""

from dataclasses import replace

from rigora.domain.character_recipe import (
    PART_CHOICES,
    POSE_CHOICES,
    CharacterRecipe,
    canonical_hand_pose,
)
from rigora.domain.illustration_catalog import design_by_id

COMPONENT_CHOICES = {
    "Mouth": PART_CHOICES["Mouth"],
    "Clothing": (
        "none",
        "tee",
        "shirt",
        "jacket",
        "hoodie",
        "sport",
        "overshirt",
        "waistcoat",
        "suit jacket",
        "dress",
        "long dress",
        "dungarees",
        "coat",
        "shell",
        "formal suit",
        "tuxedo",
        "blazer",
        "polo",
        "cropped tee",
        "tank top",
        "striped tee",
        "cardigan",
        "robe",
        "raincoat",
    ),
    "Pants": (
        "none",
        "trousers",
        "shorts",
        "jeans",
        "joggers",
        "skirt",
        "formal trousers",
        "capri",
        "cargo shorts",
        "cargo trousers",
        "leggings",
        "wide trousers",
        "track pants",
        "bermuda shorts",
        "cuffed jeans",
    ),
    "Shoes": (
        "bare",
        "sneakers",
        "boots",
        "loafers",
        "sandals",
        "high tops",
        "canvas",
        "dress shoes",
        "ankle boots",
        "rain boots",
        "slippers",
    ),
    "Ties": (
        "none",
        "tie",
        "bow tie",
        "scarf",
        "skinny tie",
        "striped tie",
        "cravat",
        "long scarf",
        "neckerchief",
    ),
    "Headwear": ("none", "cap", "beanie", "top hat", "sun hat", "headphones", "crown"),
    "Glasses": (
        "none",
        "round",
        "square",
        "sunglasses",
        "sport",
        "oval",
        "aviator",
        "cat eye",
        "rimless",
        "half rim",
        "monocle",
    ),
    "Watches": ("none", "classic", "digital", "bracelet"),
    "Necklaces": ("none", "pendant", "pearls", "chain"),
    "Belts": ("none", "classic", "sash", "utility"),
    "Backwear": ("none", "backpack", "satchel", "cape"),
    "Hair": PART_CHOICES["Hair"],
    "Eyes": PART_CHOICES["Eyes"],
    "Hands": POSE_CHOICES["Hands"],
    "Nose": PART_CHOICES["Nose"],
    "Mustache": PART_CHOICES["Mustache"],
    "Beard": PART_CHOICES["Beard"],
}

OUTFIT_PRESETS = {
    "Everyday": {"Clothing": "tee", "Pants": "jeans", "Shoes": "sneakers"},
    "Business": {
        "Clothing": "suit jacket",
        "Pants": "trousers",
        "Shoes": "loafers",
        "Ties": "tie",
        "Belts": "classic",
        "Watches": "classic",
    },
    "Evening": {
        "Clothing": "waistcoat",
        "Pants": "trousers",
        "Shoes": "loafers",
        "Ties": "bow tie",
        "Watches": "classic",
    },
    "Runner": {
        "Clothing": "sport",
        "Pants": "shorts",
        "Shoes": "sneakers",
        "Headwear": "cap",
        "Watches": "digital",
    },
    "Garden": {
        "Clothing": "long dress",
        "Shoes": "boots",
        "Headwear": "sun hat",
        "Necklaces": "pendant",
    },
    "Winter": {
        "Clothing": "coat",
        "Pants": "jeans",
        "Shoes": "boots",
        "Headwear": "beanie",
        "Ties": "scarf",
    },
    "Explorer": {
        "Clothing": "overshirt",
        "Pants": "shorts",
        "Shoes": "boots",
        "Backwear": "backpack",
        "Belts": "utility",
    },
    "Celebration": {
        "Clothing": "dress",
        "Shoes": "sandals",
        "Necklaces": "pearls",
        "Headwear": "crown",
        "Watches": "bracelet",
    },
    "Courtroom": {
        "Clothing": "formal suit",
        "Pants": "formal trousers",
        "Ties": "tie",
        "Shoes": "loafers",
    },
    "Black tie": {
        "Clothing": "tuxedo",
        "Pants": "formal trousers",
        "Ties": "bow tie",
        "Shoes": "loafers",
    },
    "Smart casual": {"Clothing": "blazer", "Pants": "jeans", "Shoes": "loafers"},
    "Summer": {"Clothing": "tee", "Pants": "shorts", "Shoes": "sandals", "Glasses": "sunglasses"},
    "Weekend": {"Clothing": "striped tee", "Pants": "cargo shorts", "Shoes": "sneakers"},
    "Tennis": {"Clothing": "polo", "Pants": "shorts", "Shoes": "sneakers", "Headwear": "cap"},
    "Studio": {"Clothing": "cropped tee", "Pants": "capri", "Shoes": "sneakers"},
    "Training": {"Clothing": "tank top", "Pants": "joggers", "Shoes": "sneakers"},
    "Bookshop": {
        "Clothing": "cardigan",
        "Pants": "trousers",
        "Shoes": "loafers",
        "Glasses": "round",
    },
    "Scholar": {"Clothing": "robe", "Pants": "formal trousers", "Shoes": "loafers"},
    "Rainy day": {"Clothing": "raincoat", "Pants": "jeans", "Shoes": "boots", "Headwear": "beanie"},
}

CLOTHING_PAINTS = {
    "formal suit": "#25282b",
    "tuxedo": "#202124",
    "blazer": "#4b5968",
    "polo": "#6b8e9b",
    "cropped tee": "#af858b",
    "tank top": "#c4bcaa",
    "striped tee": "#dedbd2",
    "cardigan": "#827181",
    "robe": "#5b566b",
    "raincoat": "#c5ab63",
}
PLACEMENTS = {
    "Clothing": ("Behind accessories", "Front panels"),
    "Watches": ("Under sleeves", "Over sleeves"),
    "Belts": ("Under outerwear", "Over outerwear"),
}

CREATOR_LOOKS = {
    "kai": (
        "Runner",
        {"Top": "#7e9aa6", "Bottom": "#4b5d70", "Accent": "#d1ac6d", "Shoes": "#d8dcdb"},
    ),
    "mabel": ("Garden", {"Top": "#ad8492", "Hair": "#55454b", "Accent": "#d0b98d"}),
    "luca": ("Business", {"Top": "#626d7b", "Bottom": "#454e5a", "Accent": "#b69b75"}),
    "dot": ("Everyday", {"Top": "#b99679", "Bottom": "#657e8b", "Hair": "#524637"}),
}


def default_choice(recipe: CharacterRecipe, category: str) -> str:
    """Resolve one visible default independently of retained alternative checkboxes."""
    design = design_by_id(recipe.design_id)
    if category == "Clothing":
        return (
            recipe.worn.get(category)
            or recipe.wearing("Dresses")
            or recipe.wearing("Tops")
            or design.outfit
        )
    if category == "Mouth":
        return recipe.mouth_style
    if category == "Hands":
        return canonical_hand_pose(str(recipe.poses.get("Hands", "Relaxed")))
    if category in PART_CHOICES:
        return recipe.parts.get(
            category,
            design.hair if category == "Hair" else design.eye if category == "Eyes" else "None",
        )
    return str(recipe.worn.get(category, COMPONENT_CHOICES[category][0]))


def retained_choices(recipe: CharacterRecipe, category: str) -> tuple[str, ...]:
    """Always keep the visible default; old clothing recipes retain their saved alternatives."""
    extra = recipe.alternatives.get(category, ())
    if category == "Clothing":
        extra = (*extra, *recipe.alternatives.get("Tops", ()), *recipe.dress)
    if category == "Hands":
        extra = tuple(canonical_hand_pose(str(value)) for value in extra)
    return tuple(dict.fromkeys((default_choice(recipe, category), *extra)))


def choose(recipe: CharacterRecipe, category: str, value: str) -> CharacterRecipe:
    """Set a default appearance without checking the retained-alternative checkbox."""
    if category == "Mouth":
        return replace(recipe, mouth_style=value)
    if category == "Hands":
        return replace(recipe, poses={**recipe.poses, "Hands": value})
    if category in PART_CHOICES:
        return replace(recipe, parts={**recipe.parts, category: value})
    return replace(recipe, worn={**recipe.worn, category: value})


def outfit(recipe: CharacterRecipe, name: str) -> CharacterRecipe:
    """Apply a complete coordinated outfit while retaining unrelated authored alternatives."""
    return replace(recipe, worn=outfit_values(name))


def outfit_values(name: str) -> dict[str, str]:
    """Include empty choices so a complete outfit clears the preceding set's accessories."""
    defaults = {
        k: v[0]
        for k, v in COMPONENT_CHOICES.items()
        if k not in PART_CHOICES and k not in ("Mouth", "Hands")
    }
    return {**defaults, **OUTFIT_PRESETS[name]}


def retain_outfit_sets(recipe: CharacterRecipe) -> CharacterRecipe:
    """Keep all pieces needed by checked sets, including their empty accessory choices."""
    alternatives = dict(recipe.alternatives)
    for name in recipe.outfit_sets:
        for category, value in outfit_values(name).items():
            alternatives[category] = tuple(dict.fromkeys((*alternatives.get(category, ()), value)))
    return replace(recipe, alternatives=alternatives)
