"""Small authored fixtures test editor behavior independently of the optional preset inventory."""

from rigora.application_services.documents import DocumentService
from rigora.application_services.meshes import MeshService
from rigora.application_services.scene_editing import SceneEditingService
from rigora.domain.content import ContentItem
from rigora.domain.entities import Group


def background(doc: DocumentService) -> str:
    """Create a full-camera Object with owned artwork for selection and ordering regressions."""
    owner = Group(name="Backdrop", extra={"object_container": True})
    doc.add_entities(doc.scene.id, {"groups": (owner,)})
    service = MeshService(doc)
    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">'
        b'<rect width="1920" height="1080" fill="#555555"/></svg>'
    )
    mesh = service.mesh(service.import_image_bytes("backdrop.svg", source, 1, 1))
    SceneEditingService(doc).move_entries((mesh.object_id,), owner.id)
    return owner.id


def ball_item() -> tuple[ContentItem, dict[str, bytes]]:
    """Return a real portable vector item for native drag/drop tests."""
    source = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80">'
        b'<circle cx="40" cy="40" r="38" fill="#999999"/></svg>'
    )
    item = ContentItem(
        name="Fixture ball",
        kind="artwork",
        category="Props",
        author="Rigora tests",
        license="CC0-1.0",
        payload={"source": "ball.svg"},
    )
    return item, {"ball.svg": source}
