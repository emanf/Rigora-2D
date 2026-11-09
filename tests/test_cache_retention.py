"""Generated cache cleanup protects current, recent and unknown data."""

import json
import os
import time

from rigora.application_services.cache_retention import prune_catalogs
from rigora.application_services.illustration_cache import cached_catalog


def test_cleanup_only_removes_old_completed_unprotected_generations(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    old = time.time() - 10 * 86400
    folders = []
    for index in range(5):
        folder = root / f"illustrations-{index:016x}"
        folder.mkdir()
        marker = folder / "complete.json"
        marker.write_text(
            json.dumps({"identity": folder.name, "pack_sha256s": {"templates.rigpack": "hash"}})
        )
        os.utime(marker, (old + index, old + index))
        folders.append(folder)
    current = cached_catalog(root)
    current.mkdir()
    marker = current / "complete.json"
    marker.write_text(
        json.dumps({"identity": current.name, "pack_sha256s": {"templates.rigpack": "hash"}})
    )
    os.utime(marker, (old - 1, old - 1))
    unknown = root / "illustrations-ffffffffffffffff"
    unknown.mkdir()
    (unknown / "user.txt").write_text("keep")
    staging = root / ".preparing-in-progress"
    staging.mkdir()
    assert prune_catalogs(root, (folders[0],)) == 2
    assert folders[0].exists() and current.exists() and staging.exists() and unknown.exists()
    assert folders[3].exists() and folders[4].exists()
    assert not folders[1].exists() and not folders[2].exists()


def test_recent_generations_are_retained_even_beyond_count_limit(tmp_path):
    for index in range(4):
        folder = tmp_path / f"illustrations-{index:016x}"
        folder.mkdir()
        (folder / "complete.json").write_text(
            json.dumps({"identity": folder.name, "pack_sha256s": {"templates.rigpack": "hash"}})
        )
    assert prune_catalogs(tmp_path, keep=1) == 0
