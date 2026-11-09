"""Validated configuration, resolved explicitly at startup."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class LogLevel(StrEnum):
    """Supported structured logging thresholds accepted by configuration and the CLI."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class ApplicationConfig:
    """Immutable validated startup options shared across application adapters."""

    log_level: LogLevel = LogLevel.INFO
    safe_mode: bool = False

    def __post_init__(self) -> None:
        """Reject unvalidated logging thresholds before runtime initialization."""
        if not isinstance(self.log_level, LogLevel):
            raise ValueError("log_level must be a LogLevel value")
        if type(self.safe_mode) is not bool:
            raise ValueError("safe_mode must be a boolean")


def load_config(
    *,
    log_level: str | None = None,
    safe_mode: bool | None = None,
    environ: Mapping[str, str] | None = None,
) -> ApplicationConfig:
    """Resolve CLI override, then environment, then defaults; never write settings."""
    source = os.environ if environ is None else environ
    raw_level = log_level if log_level is not None else source.get("RIGORA_LOG_LEVEL", "INFO")
    try:
        level = LogLevel(raw_level.strip().upper())
    except ValueError as error:
        choices = ", ".join(LogLevel)
        raise ValueError(f"Invalid log level {raw_level!r}; choose {choices}.") from error
    raw_safe = source.get("RIGORA_SAFE_MODE", "0").strip().lower()
    if safe_mode is None and raw_safe not in ("0", "1", "false", "true"):
        raise ValueError("RIGORA_SAFE_MODE must be 0, 1, false or true.")
    return ApplicationConfig(
        log_level=level, safe_mode=safe_mode if safe_mode is not None else raw_safe in ("1", "true")
    )
