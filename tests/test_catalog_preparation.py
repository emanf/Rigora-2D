"""Real process cancellation cannot publish an incomplete generated catalog."""

from concurrent.futures import CancelledError

import pytest

from rigora.application_services.catalog_preparation import prepare_catalog
from rigora.application_services.illustration_cache import cached_catalog


def test_process_cancellation_cleans_staging_and_leaves_catalog_unpublished(tmp_path):
    with pytest.raises(CancelledError):
        prepare_catalog(tmp_path / "content", cancelled=lambda: True)
    assert not cached_catalog(tmp_path / "content").exists()
    assert not list((tmp_path / "content").glob(".preparing-*"))
