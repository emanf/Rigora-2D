import io
import json
import logging

import pytest

from rigora.app.application import ApplicationRuntime
from rigora.app.config import ApplicationConfig, LogLevel


def test_lifecycle_is_idempotent_and_logging_is_owned() -> None:
    stream = io.StringIO()
    root_handlers = logging.getLogger().handlers[:]
    runtime = ApplicationRuntime(ApplicationConfig(), log_stream=stream)
    assert not runtime.running
    runtime.shutdown()
    with runtime:
        assert runtime.running
        runtime.start()
    runtime.shutdown()
    assert not runtime.running
    assert logging.getLogger().handlers == root_handlers
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [record["event"] for record in records] == [
        "application.started",
        "application.stopped",
    ]
    assert all(record["timestamp"].endswith("+00:00") for record in records)
    assert all(record["level"] == "INFO" for record in records)
    assert all(record["version"] == runtime.info.version for record in records)
    assert not stream.closed


def test_failure_is_logged_and_runtime_stops() -> None:
    stream = io.StringIO()
    runtime = ApplicationRuntime(ApplicationConfig(), log_stream=stream)
    with pytest.raises(RuntimeError, match="fixture failure"), runtime:
        raise RuntimeError("fixture failure")
    assert not runtime.running
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert records[1]["event"] == "application.failed"
    assert "RuntimeError: fixture failure" in records[1]["exception"]
    assert records[-1]["event"] == "application.stopped"


def test_warning_level_filters_lifecycle_messages() -> None:
    stream = io.StringIO()
    with ApplicationRuntime(ApplicationConfig(LogLevel.WARNING), log_stream=stream):
        pass
    assert stream.getvalue() == ""
