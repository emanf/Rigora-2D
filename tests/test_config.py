import pytest

from rigora.app.config import ApplicationConfig, LogLevel, load_config


def test_defaults_and_precedence() -> None:
    assert load_config(environ={}) == ApplicationConfig(LogLevel.INFO)
    assert load_config(environ={"RIGORA_LOG_LEVEL": " debug "}).log_level is LogLevel.DEBUG
    assert (
        load_config(log_level="error", environ={"RIGORA_LOG_LEVEL": "BAD"}).log_level
        is LogLevel.ERROR
    )


@pytest.mark.parametrize("level", ["", "TRACE", "30"])
def test_invalid_level_is_actionable(level: str) -> None:
    with pytest.raises(ValueError, match="Invalid log level"):
        load_config(log_level=level, environ={})


def test_typed_config_rejects_invalid_construction() -> None:
    with pytest.raises(ValueError, match="LogLevel"):
        ApplicationConfig(log_level="BAD")  # type: ignore[arg-type]
