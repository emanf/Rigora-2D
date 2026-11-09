"""Explicit runtime ownership shared by desktop and headless adapters."""

import logging
import sys
from dataclasses import dataclass
from types import TracebackType
from typing import TextIO

from rigora import APP_NAME, __version__
from rigora.app.config import ApplicationConfig
from rigora.application_services.plugins import PluginManager
from rigora.infrastructure.logging import create_logger
from rigora.infrastructure.preferences import PreferencesStore


@dataclass(frozen=True, slots=True)
class ApplicationInfo:
    """Immutable application identity shared by desktop and headless adapters."""

    name: str = APP_NAME
    version: str = __version__
    milestone: str = "plugin-sdk"


class ApplicationRuntime:
    """Own one logger and its handlers; importing this module starts nothing."""

    def __init__(self, config: ApplicationConfig, *, log_stream: TextIO | None = None) -> None:
        """Retain validated configuration and an optional logging stream without starting work."""
        self.config = config
        self.info = ApplicationInfo()
        self._log_stream = log_stream
        self._logger: logging.Logger | None = None
        self.plugins = PluginManager(PreferencesStore(), safe_mode=config.safe_mode)

    @property
    def running(self) -> bool:
        """Report whether this runtime currently owns an active logger."""
        return self._logger is not None

    def start(self) -> None:
        """Create the owned logger and emit startup exactly once per active lifecycle."""
        if self.running:
            return
        self._logger = create_logger(self.config, self._log_stream or sys.stderr)
        self._logger.info("Application started", extra={"event": "application.started"})
        self.plugins.discover()
        self.plugins.restore()

    def shutdown(self) -> None:
        """Emit shutdown and release owned handlers even when logging fails."""
        logger = self._logger
        if logger is None:
            return
        try:
            self.plugins.shutdown()
            logger.info("Application stopped", extra={"event": "application.stopped"})
        finally:
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
                handler.close()
            self._logger = None

    def __enter__(self) -> "ApplicationRuntime":
        """Start the runtime for a context-managed application lifecycle."""
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Log an escaping failure and always release runtime resources."""
        try:
            if exc_value is not None and self._logger is not None:
                self._logger.error(
                    "Application failed",
                    exc_info=(type(exc_value), exc_value, traceback),
                    extra={"event": "application.failed"},
                )
        finally:
            self.shutdown()
