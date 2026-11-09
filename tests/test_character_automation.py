"""New character workflows remain available through the canonical Qt-free automation adapters."""

import pytest

from rigora.api import AutomationError, RigoraAPI
from rigora.resources import asset_path


def test_guide_face_phonemes_and_cartoon_helpers_share_public_api(tmp_path):
    """A local API client assembles, animates and exports real reusable character data."""
    api = RigoraAPI(tmp_path)
    api.execute("project_create")
    imported = api.execute(
        "character_parts_import", {"paths": [str(asset_path("examples/prop.svg"))]}
    )
    meshes = list(imported.data["mesh_ids"])
    rig = api.execute("character_rig_generate", {"template": "Winged", "meshes": meshes}).data[
        "rig_id"
    ]
    api.execute("character_mesh_generate", {"meshes": meshes, "columns": 4, "rows": 4})
    api.execute("character_bind", {"rig_id": rig, "meshes": meshes})
    bones = api.document.project.scenes[0].skeletons[0].bones
    api.execute("dynamics_configure", {"bones": [bones[1].id], "gravity": 100})
    face = api.execute("face_create", {"parent_bone": bones[1].id}).data["face_id"]
    api.execute("face_controls", {"face_id": face, "frame": 0, "expression": "Happy"})
    before = api.document.project
    api.execute(
        "lip_sync_set",
        {
            "face_id": face,
            "cues": [{"seconds": 0.2, "phoneme": "AH"}, {"seconds": 0.5, "phoneme": "M"}],
        },
        dry_run=True,
    )
    assert api.document.project is before
    with pytest.raises(AutomationError, match="Unknown phoneme"):
        api.execute(
            "lip_sync_set", {"face_id": face, "cues": [{"seconds": 0, "phoneme": "unknown"}]}
        )
    api.execute("bounce_apply", {"owner": bones[0].id, "duration": 24})
    api.execute("squash_apply", {"owner": bones[0].id, "frame": 0})
    baked = api.execute("dynamics_bake").data["clip_id"]
    assert baked
    api.execute("character_template_save", {"path": "character.rigpack"}, dry_run=True)
    assert not (tmp_path / "character.rigpack").exists()
    api.execute("character_template_save", {"path": "character.rigpack"})
    assert (tmp_path / "character.rigpack").is_file()
    with pytest.raises(AutomationError):
        api.execute("character_template_save", {"path": "../outside.rigpack"})
