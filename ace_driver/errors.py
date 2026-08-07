"""Structured Ace Pro Control Center errors."""

from __future__ import annotations

from typing import Any, Dict, Optional


class AceError(RuntimeError):
    """Base error exposed to G-code, Moonraker, and both user interfaces."""

    code = "ace_error"

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        retryable: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.retryable = bool(retryable)
        self.details = dict(details or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class AceConfigError(AceError):
    code = "invalid_config"


class AceBusyError(AceError):
    code = "path_busy"


class AceCapabilityError(AceError):
    code = "capability_unavailable"


class AceDeviceOfflineError(AceError):
    code = "device_offline"


class AceSafetyError(AceError):
    code = "safety_rejected"


class AceTransportError(AceError):
    code = "transport_error"
