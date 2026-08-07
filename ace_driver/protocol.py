"""Protocol contracts and wire helpers shared by ACE generations.

Source notes:
- The Manager/Protocol separation follows Kobra-S1/ACEPRO.
- ACE1 framing and CRC behavior is cross-checked against ACEPROSV08 PROTOCOL.md.
- Public V3 interfaces in this module are new, model-neutral contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any, Dict, Mapping, Optional


class AceProtocolError(ValueError):
    """A frame or logical protocol response is invalid."""


class AceResponseMismatchError(AceProtocolError):
    """A response does not belong to any pending request."""


class AceReadOnlyError(AceProtocolError):
    """A physical command was rejected by a read-only protocol."""


@dataclass(frozen=True)
class ProtocolCapabilities:
    """Stable capability description consumed by the device and frontends."""

    status: bool = True
    info: bool = True
    inventory: bool = True
    feed: bool = False
    retract: bool = False
    feed_assist: bool = False
    drying: bool = False
    physical_actions: bool = False
    read_only: bool = True
    shared_bus: bool = False

    def to_dict(self) -> Dict[str, bool]:
        return {
            "status": self.status,
            "info": self.info,
            "inventory": self.inventory,
            "feed": self.feed,
            "retract": self.retract,
            "feed_assist": self.feed_assist,
            "drying": self.drying,
            "physical_actions": self.physical_actions,
            "read_only": self.read_only,
            "shared_bus": self.shared_bus,
        }


def crc16_mcrf4xx(data: bytes) -> int:
    """Return the CRC-16/MCRF4XX value used by ACE1 and ACE2 frames."""
    crc = 0xFFFF
    for byte in bytes(data):
        value = byte ^ (crc & 0xFF)
        value ^= (value & 0x0F) << 4
        crc = ((value << 8) | (crc >> 8)) ^ (value >> 4) ^ (value << 3)
    return crc & 0xFFFF


class BaseProtocol:
    """Thread-safe request ID allocation and response matching."""

    name = "ace"
    capabilities = ProtocolCapabilities()

    def __init__(self, *, request_id: int = 1, **_kwargs: Any) -> None:
        if not 1 <= int(request_id) <= 0xFFFF:
            raise ValueError("request_id must be in range 1..65535")
        self._next_request_id = int(request_id)
        self._pending: Dict[int, Any] = {}
        self._request_lock = threading.RLock()

    def _allocate_request(self, expected: Any) -> int:
        with self._request_lock:
            request_id = self._next_request_id
            self._next_request_id = 1 if request_id == 0xFFFF else request_id + 1
            self._pending[request_id] = expected
            return request_id

    def _match_response(self, request_id: int, actual: Any = None) -> None:
        with self._request_lock:
            if not self._pending:
                return
            if request_id not in self._pending:
                raise AceResponseMismatchError(
                    "Response ID %d does not match a pending request" % request_id
                )
            expected = self._pending[request_id]
            if expected is not None and actual is not None and expected != actual:
                raise AceResponseMismatchError(
                    "Response ID %d returned %r, expected %r"
                    % (request_id, actual, expected)
                )
            del self._pending[request_id]

    def _discard_request(self, request_id: int) -> None:
        with self._request_lock:
            self._pending.pop(int(request_id), None)

    @property
    def pending_request_ids(self):
        with self._request_lock:
            return tuple(sorted(self._pending))

    def encode_request(
        self, method: str, params: Optional[Mapping[str, Any]] = None
    ) -> bytes:
        raise NotImplementedError

    def decode_response(self, payload: bytes) -> Dict[str, Any]:
        raise NotImplementedError

    def normalize_status(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


def create_protocol(model: str, **kwargs: Any) -> BaseProtocol:
    """Create the protocol implementation for ``ace1`` or ``ace2``."""
    normalized = str(model or "").strip().lower().replace("-", "")
    if normalized in {"ace1", "acepro", "gen1"}:
        from .protocol_ace1 import Ace1Protocol

        return Ace1Protocol(**kwargs)
    if normalized in {"ace2", "gen2"}:
        from .protocol_ace2 import Ace2Protocol

        return Ace2Protocol(**kwargs)
    raise ValueError("Unsupported ACE model: %s" % model)


__all__ = [
    "AceProtocolError",
    "AceReadOnlyError",
    "AceResponseMismatchError",
    "BaseProtocol",
    "ProtocolCapabilities",
    "create_protocol",
    "crc16_mcrf4xx",
]
