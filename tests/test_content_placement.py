"""Every original template has a standalone specimen and shares atomic positioned placement."""

import pytest

from rigora.application_services.characters import CharacterService
from rigora.application_services.content_library import ContentService
from rigora.application_services.documents import DocumentService
from rigora.domain.geometry import transform_point
from rigora.domain.project import ProjectError
from rigora.infrastructure.content_packs import read_pack


def test_every_original_template_has_a_visible_evaluated_specimen(
    current_pack,
):
    """Preview all categories in an empty project, including incompatible target-dependent items."""
    pack, files = current_pack("rigs-effects")
    doc = DocumentService()
    doc.new()
    source = doc.project
    service = ContentService(doc)
    for item in pack.items:
        preview = service.preview(item, files, specimen=True)
        assert doc.project is source, item.name
        pose = preview.animation.pose
        assert not pose.warnings, (item.name, pose.warnings)
        assert any(n.visible for n in pose.nodes.values()), item.name
        if item.kind == "deformation":
            assert pose.meshes and preview.project.assets, item.name
        if item.kind == "action" or "motion" in item.payload:
            end = preview.animation.evaluator.range.end
            samples = [preview.animation.evaluate(end * factor) for factor in (0.17, 0.37, 0.63)]
            assert any(
                sample.nodes != pose.nodes or sample.meshes != pose.meshes for sample in samples
            ), item.name


def test_positioned_templates_match_scene_coordinates_and_undo_once(current_pack, tmp_path):
    """New content is placed at the previewed anchor without moving existing scene entities."""
    pack, files = current_pack("rigs-effects")
    props, prop_files = current_pack("objects")
    doc = DocumentService()
    doc.new()
    service = ContentService(doc)
    source = DocumentService()
    source.new()
    ContentService(source).apply(props.items[0], prop_files)
    path = tmp_path / "fragment.rigpack"
    ContentService(source).export_own(path, "Fragment", "Test", "CC0-1.0")
    scene_pack, scene_files = read_pack(path)
    for item in [
        next(item for item in pack.items if item.kind == "rig"),
        props.items[0],
        *scene_pack.items,
    ]:
        baseline = doc.project
        count = len(doc.history.undo_stack)
        sources = (
            scene_files if item.kind == "scene" else prop_files if item.kind == "artwork" else files
        )
        service.place(item, sources, position=(510, 370))
        assert len(doc.history.undo_stack) == count + 1
        assert all(camera in doc.scene.cameras for camera in baseline.scenes[0].cameras)
        if item.kind == "scene":
            imported = [
                c
                for c in doc.scene.cameras
                if c.id not in {c.id for c in baseline.scenes[0].cameras}
            ]
            assert len(imported) == 1
            assert imported[0].transform == source.scene.cameras[0].transform
            assert imported[0].extra.get("locked") is True
        roots = [
            n
            for n in doc.animation.pose.nodes.values()
            if n.parent_id is None and n.kind not in ("camera", "bone")
        ]
        points = [
            transform_point(
                n.world_matrix,
                n.local.pivot_x if item.payload.get("object_template") else 0,
                n.local.pivot_y if item.payload.get("object_template") else 0,
            )
            for n in roots
        ]
        assert min(p[0] for p in points) == pytest.approx(510), item.name
        assert min(p[1] for p in points) == pytest.approx(370), item.name
        doc.undo()
        assert doc.project == baseline


def test_rig_object_adoption_is_atomic_and_persists(current_pack, tmp_path):
    """The shared service retains object ownership across save/reload and rejects locked targets."""
    pack, files = current_pack("rigs-effects")
    template = next(item for item in pack.items if item.name == "Human · full body")
    doc = DocumentService()
    doc.new()
    characters = CharacterService(doc)
    owner = characters.create_object(name="Armature object")
    service = ContentService(doc)
    source = doc.project
    before = len(doc.history.undo_stack)
    rig = service.place(template, files, object_id=owner, position=(400, 300))
    assert characters.object_root(rig).id == owner
    assert characters.scene_objects() == (owner,)
    assert len(doc.history.undo_stack) == before + 1
    path = tmp_path / "owned-rig.rigora"
    doc.save(path)
    loaded = DocumentService()
    loaded.open(path)
    assert CharacterService(loaded).object_root(rig).id == owner
    doc.undo()
    assert doc.project == source
    characters.flags((owner,), locked=True)
    locked = doc.project
    before = len(doc.history.undo_stack)
    with pytest.raises(ProjectError, match="unlocked"):
        service.place(template, files, object_id=owner, position=(400, 300))
    assert doc.project == locked
    assert len(doc.history.undo_stack) == before
