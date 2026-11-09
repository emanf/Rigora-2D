"""Structured stderr logging without changing the process's root logger."""

import json
import logging
from datetime import UTC, datetime
from typing import TextIO

from rigora import __version__
from rigora.app.config import ApplicationConfig


class JsonFormatter(logging.Formatter):
    """Format application records as machine-readable JSON without configuring global logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Encode timestamp, severity, event, version, and optional exception details."""
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", "log.message"),
            "message": record.getMessage(),
            "version": __version__,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def create_logger(config: ApplicationConfig, stream: TextIO) -> logging.Logger:
    """Return an owned logger, intentionally outside logging's global registry."""
    logger = logging.Logger("rigora", level=config.log_level.value)
    logger.propagate = False
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    return logger
