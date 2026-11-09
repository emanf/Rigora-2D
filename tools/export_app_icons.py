"""Export theme-specific application icons from the canonical monochrome rig SVG.

Run with the existing GUI/render environment. This writes only branding assets;
it does not compile or rebuild the desktop application.
"""

from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def export_icons() -> None:
    """Write matching SVG/PNG pairs and multi-size ICO files for both neutral themes."""
    root = Path(__file__).resolve().parents[1] / "assets" / "icons" / "app"
    source = (root / "rigora-mark.svg").read_text(encoding="utf-8")
    for theme, ink, tile in (("dark", "#ffffff", "#000000"), ("light", "#000000", "#ffffff")):
        mark = source.replace('fill="#ffffff"', f'fill="{ink}"')
        for boxed in (False, True):
            svg = mark
            if boxed:
                svg = svg.replace(
                    "  <g fill=",
                    f'  <rect x="60" y="60" width="1160" height="1160" rx="190" '
                    f'fill="{tile}"/>\n  <g fill=',
                    1,
                )
            stem = root / f"rigora-{theme}{'' if boxed else '-mark'}"
            stem.with_suffix(".svg").write_text(svg, encoding="utf-8")
            renderer = QSvgRenderer(svg.encode("utf-8"))
            if not renderer.isValid():
                raise ValueError(f"Invalid icon SVG: {stem}")
            image = QImage(1024, 1024, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            if not image.save(str(stem.with_suffix(".png"))):
                raise OSError(f"Could not write icon: {stem}")
            if boxed:
                with Image.open(stem.with_suffix(".png")) as raster:
                    raster.save(
                        stem.with_suffix(".ico"),
                        sizes=[(size, size) for size in (16, 20, 24, 32, 48, 64, 128, 256)],
                    )
                if theme == "dark":
                    (root / "rigora.png").write_bytes(stem.with_suffix(".png").read_bytes())


if __name__ == "__main__":
    export_icons()
