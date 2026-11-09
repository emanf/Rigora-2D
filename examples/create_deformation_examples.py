"""Generate editable deformation studies using the application's canonical authoring services."""

import argparse
from pathlib import Path

from rigora.application_services.deformation_examples import (
    EXAMPLE_STYLES,
    populate_deformation_example,
)
from rigora.application_services.documents import DocumentService


def create(directory: Path, *, overwrite: bool = False) -> None:
    """Write five self-contained projects; existing files require an explicit overwrite flag."""
    directory.mkdir(parents=True, exist_ok=True)
    for style in EXAMPLE_STYLES:
        document = DocumentService()
        document.new(style)
        populate_deformation_example(document, style)
        name = style.lower().replace(" ", "-")
        document.save(directory / f"deformation-{name}.rigora", overwrite=overwrite)


def main() -> None:
    """Generate copies in the build folder unless another destination is explicitly requested."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("build/examples"))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    create(args.directory, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
