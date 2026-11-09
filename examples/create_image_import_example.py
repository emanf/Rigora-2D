"""Create a self-contained PNG artwork project with connected, skinned bones."""

import argparse
from pathlib import Path

from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.rigging import RigService
from rigora.application_services.skinning import SkinService
from rigora.domain.project import SceneSettings
from rigora.resources import asset_path


def create(path: Path, *, overwrite: bool = False) -> None:
    """Embed original PNG art and bind a connected two-bone rig using canonical services."""
    document = DocumentService()
    document.new("Image import and needle bones", SceneSettings(width=800, height=600))
    meshes, rig = MeshService(document), RigService(document)
    with document.transaction("Create image import study"):
        mesh = meshes.import_image(asset_path("examples/torso.png"), 6, 10)
        root = rig.create_bone((400, 180), (400, 310))
        rig.update(root, name="Spine")
        child = rig.create_bone((400, 310), (400, 430), root)
        rig.update(child, name="Chest")
        SkinService(document).bind(mesh, (root, child))
    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path, overwrite=overwrite)


def main() -> None:
    """Write a demonstration copy, requiring explicit consent to overwrite an existing file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", type=Path, default=Path("build/examples/image-import-example.rigora")
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    create(args.path, overwrite=args.overwrite)


if __name__ == "__main__":
    main()
