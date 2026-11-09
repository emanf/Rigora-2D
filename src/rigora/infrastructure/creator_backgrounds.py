"""Small original SVG backdrops for the isolated Creator stage; never exported as character art."""

from rigora.infrastructure.illustration import svg


def background_source(name: str, custom: str = "") -> bytes:
    """Return a solid swatch or a flat studio/park/street setting without external resources."""
    colors = {
        "White": "#ffffff",
        "Gray": "#777777",
        "Black": "#101010",
        "Studio": "#b9b9b7",
        "Park": "#d1ded9",
        "Street": "#c7ccce",
    }
    color = custom or colors.get(name, "#303030")
    art = f'<rect width="640" height="480" fill="{color}"/>'
    if name == "Studio":
        art += '<path d="M 0 355 Q 320 310 640 355 L 640 480 L 0 480 Z" fill="#989997"/>'
        art += '<path d="M 0 400 L 640 400 M 0 445 L 640 445" stroke="#acadaa" fill="none"/>'
    elif name == "Park":
        art += (
            '<path d="M 0 330 Q 150 270 320 325 Q 500 280 640 320 L 640 480 L 0 480'
            ' Z" fill="#94ab91"/>'
        )
        art += '<path d="M 0 400 Q 320 340 640 395 L 640 480 L 0 480 Z" fill="#b6b29b"/>'
        art += (
            '<path d="M 60 310 L 60 165 M 570 310 L 570 155" stroke="#7a8272" stroke-width="15"/>'
        )
        art += (
            '<ellipse cx="60" cy="145" rx="65" ry="85" fill="#839a83"/><ellipse '
            'cx="570" cy="145" rx="70" ry="90" fill="#8da18b"/>'
        )
    elif name == "Street":
        art += (
            '<path d="M 0 345 L 0 140 L 105 140 L 105 345 M 545 345 L 545 100 L 640'
            ' 100 L 640 345" fill="#999fa1"/>'
        )
        art += '<path d="M 0 345 L 640 345 L 640 480 L 0 480 Z" fill="#6b7073"/>'
        art += (
            '<path d="M 0 352 L 640 352 M 0 420 L 640 420" stroke="#d6d7d3" '
            'stroke-width="3" stroke-dasharray="38 22"/>'
        )
    return svg(art, (0, 0, 640, 480))
