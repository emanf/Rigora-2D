"""Private recovery packages preserve unsaved revisions and linked original assets."""

from rigora.application_services.documents import DocumentService
from rigora.application_services.recovery import RecoveryStore
from rigora.domain.entities import SceneObject


def test_recovery_embeds_linked_assets_without_saving_or_mutating_source(tmp_path):
    """A recovered snapshot remains portable after the external original is removed."""
    doc = DocumentService()
    doc.new("Unsaved changes")
    source = tmp_path / "source.rigora"
    doc.save(source)
    original_bytes = source.read_bytes()
    artwork = tmp_path / "art.svg"
    raw = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
    artwork.write_bytes(raw)
    asset = doc.import_asset(artwork, embed=False)
    baseline, history = doc.project, len(doc.history.undo_stack)
    store = RecoveryStore(tmp_path / "recovery")
    scratch, target = store.prepare(doc)
    store.write(scratch, target)
    assert doc.project is baseline and doc.dirty
    assert len(doc.history.undo_stack) == history and source.read_bytes() == original_bytes
    artwork.unlink()
    entry = store.entries()[0]
    restored = store.restore(entry)
    assert restored.path is None and restored.dirty
    assert restored.read_asset(asset.id) == raw
    assert restored.project.assets[0].id == asset.id
    assert restored.project.assets[0].storage == "embedded"


def test_corrupt_latest_recovery_retains_predecessor_and_never_deletes_other_runs(tmp_path):
    """A private predecessor survives a damaged latest checkpoint and another run's cleanup."""
    doc = DocumentService()
    doc.new()
    root = tmp_path / "recovery"
    store = RecoveryStore(root)
    scratch, target = store.prepare(doc)
    store.write(scratch, target)
    first = doc.project
    doc.add_entities(doc.scene.id, {"objects": (SceneObject(name="Later"),)})
    scratch, target = store.prepare(doc)
    store.write(scratch, target)
    target.write_bytes(b"damaged file")
    other = RecoveryStore(root)
    other.remove(doc.session_id)
    entries = other.entries()
    assert len(entries) == 1 and entries[0].path.name.endswith(".bak")
    assert other.restore(entries[0]).project == first
