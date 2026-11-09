"""Public Qt-free automation API over canonical Rigora application services."""

from rigora.application_services.automation import (
    API_VERSION,
    OPERATIONS,
    AutomationError,
    OperationResult,
    RigoraAPI,
)

__all__ = ["API_VERSION", "OPERATIONS", "AutomationError", "OperationResult", "RigoraAPI"]
