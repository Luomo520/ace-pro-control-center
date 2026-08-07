"""Read-only ACE generation-two protocol and shared-bus UID routing.

Frame and protobuf field meanings are cross-checked against the experimental
Kobra-S1/ACEPRO ACE2 adapter. V3 deliberately exposes only discovery and read
commands until ACE2 physical hardware validation is complete.
"""

from __future__ import annotations

import re
import struct
import threading
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .protocol import (
    AceProtocolError,
    AceReadOnlyError,
    AceResponseMismatchError,
    BaseProtocol,
    ProtocolCapabilities,
    crc16_mcrf4xx,
)


HEADER = b"\xFF\xAA"
TAIL = 0xFE
RESPONSE_FLAG = 0x80
DEVICE_ID_MASK = 0x7F
MAX_PAYLOAD_SIZE = 0xFF

COMMANDS = {
    "discover": 0,
    "assign_device_id": 1,
    "get_status": 6,
    "get_info": 7,
    "get_filament_info": 13,
}
COMMAND_NAMES = {value: key for key, value in COMMANDS.items()}
PHYSICAL_METHODS = {
    "feed",
    "retract",
    "enable_feed_assist",
    "disable_feed_assist",
    "stop_feed",
    "stop_retract",
    "start_drying",
    "stop_drying",
    "select_tool",
    "unload",
}


def normalize_uid(value: Any) -> Optional[Tuple[int, int, int]]:
    """Normalize an ACE2 UID into three unsigned 32-bit integers."""
    if value is None or str(value).strip().lower() in {"", "auto", "none"}:
        return None
    parts: Sequence[Any]
    if isinstance(value, (tuple, list)):
        parts = value
    else:
        parts = [part for part in re.split(r"[:.,/\-]+", str(value).strip()) if part]
    if len(parts) != 3:
        raise ValueError("ACE2 device_uid must contain exactly three integers")
    uid = tuple(
        int(part, 16) if isinstance(part, str) and part.lower().startswith("0x") else int(part)
        for part in parts
    )
    if any(part < 0 or part > 0xFFFFFFFF for part in uid):
        raise ValueError("ACE2 UID values must be unsigned 32-bit integers")
    return uid  # type: ignore[return-value]


class Ace2BusRouter:
    """Thread-safe mapping between immutable UID identity and bus address."""

    def __init__(self) -> None:
        self._configured: Dict[Tuple[int, int, int], int] = {}
        self._by_uid: Dict[Tuple[int, int, int], int] = {}
        self._by_address: Dict[int, Tuple[int, int, int]] = {}
        self._lock = threading.RLock()

    def configure(self, uid: Any, device_id: int) -> None:
        """Declare the stable configured UID to address mapping without binding it."""
        normalized = normalize_uid(uid)
        if normalized is None:
            raise ValueError("A concrete ACE2 UID is required in configuration")
        address = int(device_id)
        if not 1 <= address <= DEVICE_ID_MASK:
            raise ValueError("ACE2 device_id must be in range 1..127")
        with self._lock:
            if normalized in self._configured:
                raise ValueError("ACE2 UID is configured more than once")
            if address in self._configured.values():
                raise ValueError("ACE2 bus address is configured more than once")
            self._configured[normalized] = address

    def bind(self, uid: Any, device_id: int) -> None:
        normalized = normalize_uid(uid)
        if normalized is None:
            raise ValueError("A concrete ACE2 UID is required for binding")
        address = int(device_id)
        if not 1 <= address <= DEVICE_ID_MASK:
            raise ValueError("ACE2 device_id must be in range 1..127")
        with self._lock:
            configured_address = self._configured.get(normalized)
            if configured_address is not None and configured_address != address:
                raise ValueError("ACE2 binding does not match the configured address")
            other_uid = self._by_address.get(address)
            other_address = self._by_uid.get(normalized)
            if other_uid not in (None, normalized):
                raise ValueError("ACE2 bus address is already bound to another UID")
            if other_address not in (None, address):
                raise ValueError("ACE2 UID is already bound to another bus address")
            self._by_uid[normalized] = address
            self._by_address[address] = normalized

    def configured_address_for(self, uid: Any) -> Optional[int]:
        normalized = normalize_uid(uid)
        if normalized is None:
            return None
        with self._lock:
            return self._configured.get(normalized)

    def address_for(self, uid: Any) -> Optional[int]:
        normalized = normalize_uid(uid)
        if normalized is None:
            return None
        with self._lock:
            return self._by_uid.get(normalized)

    def uid_for(self, device_id: int) -> Optional[Tuple[int, int, int]]:
        with self._lock:
            return self._by_address.get(int(device_id))

    def route_matches(self, uid: Any, device_id: int) -> bool:
        normalized = normalize_uid(uid)
        if normalized is None:
            return False
        with self._lock:
            return (
                self._by_uid.get(normalized) == int(device_id)
                and self._by_address.get(int(device_id)) == normalized
            )


class Ace2Protocol(BaseProtocol):
    name = "ace2_proto_readonly"
    capabilities = ProtocolCapabilities(shared_bus=True)

    def __init__(
        self,
        *,
        device_uid: Any = None,
        device_id: Optional[int] = None,
        router: Optional[Ace2BusRouter] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self.device_uid = normalize_uid(device_uid)
        self.device_id = None if device_id is None else int(device_id)
        if self.device_id is not None and not 1 <= self.device_id <= DEVICE_ID_MASK:
            raise ValueError("ACE2 device_id must be in range 1..127")
        self.router = router or Ace2BusRouter()

    def encode_request(
        self, method: str, params: Optional[Mapping[str, Any]] = None
    ) -> bytes:
        normalized = str(method).strip().lower()
        if normalized in PHYSICAL_METHODS:
            raise AceReadOnlyError(
                "ACE2 physical action '%s' is disabled until hardware validation"
                % normalized
            )
        if normalized not in COMMANDS:
            raise AceProtocolError("Unsupported ACE2 read command: %s" % method)
        command = COMMANDS[normalized]
        values = dict(params or {})
        body = b""
        if normalized == "get_filament_info":
            index = int(values["index"])
            if not 0 <= index <= 3:
                raise ValueError("ACE2 slot index must be in range 0..3")
            body = _pb_uint(1, index)
        elif normalized == "assign_device_id":
            uid = normalize_uid(values.get("uid"))
            if uid is None:
                raise ValueError("assign_device_id requires a concrete UID")
            assigned_id = int(values["device_id"])
            if not 1 <= assigned_id <= DEVICE_ID_MASK:
                raise ValueError("ACE2 assigned device_id must be in range 1..127")
            body = (
                _pb_uint(1, uid[0])
                + _pb_uint(2, uid[1])
                + _pb_uint(3, uid[2])
                + _pb_uint(4, assigned_id)
            )
        if normalized in {"discover", "assign_device_id"}:
            flags = 0
        else:
            if self.device_id is None:
                raise AceProtocolError(
                    "ACE2 UID has not been assigned a unique bus address"
                )
            if self.device_uid is not None and not self.router.route_matches(
                self.device_uid, self.device_id
            ):
                raise AceProtocolError(
                    "ACE2 configured UID has not passed discovery and address binding"
                )
            flags = self.device_id
        request_id = self._allocate_request(command)
        inner = bytes(
            [flags, request_id & 0xFF, request_id >> 8, command, len(body)]
        ) + body
        return HEADER + inner + struct.pack("<H", crc16_mcrf4xx(inner)) + bytes([TAIL])

    def decode_response(self, payload: bytes) -> Dict[str, Any]:
        responses = self.decode_frames(payload)
        if not responses:
            raise AceProtocolError("ACE2 response contains no complete frame")
        pending = set(self.pending_request_ids)
        response = next(
            (item for item in responses if not pending or item.get("id") in pending),
            None,
        )
        if response is None:
            raise AceResponseMismatchError(
                "ACE2 response does not match a pending request"
            )
        request_id = int(response["id"])
        command = int(response["command_code"])
        self._match_response(request_id, command)
        response.setdefault("ok", response.get("code", 0) in (0, None))
        return response

    def decode_frames(self, data: bytes) -> List[Dict[str, Any]]:
        working = bytes(data)
        responses: List[Dict[str, Any]] = []
        offset = 0
        while offset < len(working):
            start = working.find(HEADER, offset)
            if start < 0:
                break
            if len(working) - start < 10:
                raise AceProtocolError("ACE2 response frame is truncated")
            payload_len = working[start + 6]
            end = start + 10 + payload_len
            if end > len(working):
                raise AceProtocolError("ACE2 response frame is truncated")
            frame = working[start:end]
            if frame[-1] != TAIL:
                raise AceProtocolError("ACE2 response has an invalid frame tail")
            inner = frame[2 : 7 + payload_len]
            received_crc = struct.unpack("<H", frame[7 + payload_len : 9 + payload_len])[0]
            if received_crc != crc16_mcrf4xx(inner):
                raise AceProtocolError("ACE2 response CRC mismatch")
            flags = frame[2]
            request_id = frame[3] | (frame[4] << 8)
            command = frame[5]
            device_id = flags & DEVICE_ID_MASK
            if command not in {COMMANDS["discover"], COMMANDS["assign_device_id"]} and device_id != self.device_id:
                raise AceProtocolError(
                    "ACE2 response is routed to device %d, expected %d"
                    % (device_id, self.device_id)
                )
            decoded = self._decode_payload(command, frame[7 : 7 + payload_len])
            response: Dict[str, Any] = {
                "id": request_id,
                "command": COMMAND_NAMES.get(command, "unknown"),
                "command_code": command,
                "device_id": device_id,
                "flags": flags,
            }
            response.update(decoded)
            responses.append(response)
            offset = end
        return responses

    def _decode_payload(self, command: int, payload: bytes) -> Dict[str, Any]:
        fields = _pb_decode(payload)
        if command == COMMANDS["discover"]:
            uid = (
                int(_pb_first(fields, 1, 0)),
                int(_pb_first(fields, 2, 0)),
                int(_pb_first(fields, 3, 0)),
            )
            return {"code": 0, "result": {"uid": uid}}
        if command == COMMANDS["assign_device_id"]:
            code = int(_pb_first(fields, 1, 0))
            return {
                "code": code,
                "message": "success" if code == 0 else "assignment_failed",
                "result": {"assigned": code == 0},
            }
        if command == COMMANDS["get_info"]:
            return {
                "code": 0,
                "result": {
                    "firmware": _as_text(_pb_first(fields, 1, b"")),
                    "boot_firmware": _as_text(_pb_first(fields, 2, b"")),
                },
            }
        if command == COMMANDS["get_status"]:
            return {"code": 0, "result": _decode_status(fields)}
        if command == COMMANDS["get_filament_info"]:
            code = int(_pb_first(fields, 12, 0))
            return {
                "code": code,
                "result": {
                    "index": int(_pb_first(fields, 1, 0)),
                    "sku": _as_text(_pb_first(fields, 3, b"")),
                    "material": _as_text(_pb_first(fields, 4, b"")),
                    "rfid": 2 if code == 0 else 0,
                },
            }
        raise AceProtocolError("Unsupported ACE2 response command: %d" % command)

    def normalize_status(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        value = payload.get("result", payload)
        if not isinstance(value, Mapping):
            raise AceProtocolError("ACE2 status result must be an object")
        raw_dryer = value.get("dryer") or value.get("dryer_status") or {}
        slots = []
        for index, raw_slot in enumerate(value.get("slots") or []):
            if not isinstance(raw_slot, Mapping):
                continue
            slots.append(
                {
                    "index": int(raw_slot.get("index", index)),
                    "status": str(raw_slot.get("status", "unknown")),
                    "material": str(raw_slot.get("material", "")),
                    "color": str(raw_slot.get("color", "#808080")),
                    "rfid": raw_slot.get("rfid"),
                    "status_detail": raw_slot.get("status_detail"),
                }
            )
        return {
            "state": str(value.get("status", "unknown")),
            "temperature": value.get("temp"),
            "humidity": value.get("humidity"),
            "dryer": dict(raw_dryer) if isinstance(raw_dryer, Mapping) else {},
            "slots": slots,
        }

    def get_status(self) -> bytes:
        return self.encode_request("get_status")

    def get_info(self) -> bytes:
        return self.encode_request("get_info")

    def discover(self) -> bytes:
        return self.encode_request("discover")

    def feed(self, *_args: Any, **_kwargs: Any) -> bytes:
        raise AceReadOnlyError("ACE2 feed is disabled until hardware validation")

    def retract(self, *_args: Any, **_kwargs: Any) -> bytes:
        raise AceReadOnlyError("ACE2 retract is disabled until hardware validation")

    def start_drying(self, *_args: Any, **_kwargs: Any) -> bytes:
        raise AceReadOnlyError("ACE2 drying is disabled until hardware validation")


class Ace2BusController:
    """Enforce configured UID discovery before assigning stable bus addresses."""

    def __init__(self, configured_uids: Sequence[Any]) -> None:
        if not configured_uids:
            raise ValueError("At least one configured ACE2 UID is required")
        self.router = Ace2BusRouter()
        for index, uid in enumerate(configured_uids, start=1):
            self.router.configure(uid, index)
        self._control = Ace2Protocol(router=self.router)
        self._verified_uids = set()
        self._pending_assignments: Dict[int, Tuple[Tuple[int, int, int], int]] = {}

    def encode_discover(self) -> bytes:
        return self._control.encode_request("discover")

    def decode_discovery_response(self, payload: bytes) -> Dict[str, Any]:
        response = self._control.decode_response(payload)
        uid = normalize_uid(response.get("result", {}).get("uid"))
        address = self.verify_discovered_uid(uid)
        response["result"]["configured_device_id"] = address
        return response

    def verify_discovered_uid(self, uid: Any) -> int:
        """Accept a discovered UID only when it exists in frozen configuration."""
        normalized = normalize_uid(uid)
        address = self.router.configured_address_for(normalized)
        if normalized is None or address is None:
            raise AceProtocolError("Discovered ACE2 UID is not present in configuration")
        self._verified_uids.add(normalized)
        return address

    def encode_assignment(self, uid: Any) -> bytes:
        normalized = normalize_uid(uid)
        address = self.router.configured_address_for(normalized)
        if normalized is None or address is None:
            raise AceProtocolError("ACE2 UID must be configured before assignment")
        if normalized not in self._verified_uids:
            raise AceProtocolError(
                "ACE2 UID must be discovered and verified before assignment"
            )
        frame = self._control.encode_request(
            "assign_device_id", {"uid": normalized, "device_id": address}
        )
        request_id = frame[3] | (frame[4] << 8)
        self._pending_assignments[request_id] = (normalized, address)
        return frame

    def decode_assignment_response(self, payload: bytes) -> Dict[str, Any]:
        request_id = payload[3] | (payload[4] << 8) if len(payload) >= 5 else -1
        assignment = self._pending_assignments.get(request_id)
        if assignment is None:
            raise AceProtocolError("ACE2 assignment response has no pending UID")
        response = self._control.decode_response(payload)
        if response.get("code", 0) != 0:
            raise AceProtocolError("ACE2 device address assignment was rejected")
        uid, address = assignment
        self.router.bind(uid, address)
        del self._pending_assignments[request_id]
        response["result"].update({"uid": uid, "device_id": address})
        return response

    def protocol_for(self, uid: Any) -> Ace2Protocol:
        normalized = normalize_uid(uid)
        address = self.router.address_for(normalized)
        if normalized is None or address is None:
            raise AceProtocolError(
                "ACE2 UID must be discovered and assigned before directed polling"
            )
        return Ace2Protocol(
            device_uid=normalized,
            device_id=address,
            router=self.router,
        )


def _pb_varint(value: int) -> bytes:
    result = bytearray()
    remaining = int(value)
    while remaining > 0x7F:
        result.append((remaining & 0x7F) | 0x80)
        remaining >>= 7
    result.append(remaining)
    return bytes(result)


def _pb_uint(field: int, value: int) -> bytes:
    return _pb_varint(field << 3) + _pb_varint(value)


def _pb_decode(data: bytes) -> Dict[int, List[Tuple[int, Any]]]:
    fields: Dict[int, List[Tuple[int, Any]]] = {}
    offset = 0
    while offset < len(data):
        tag, offset = _pb_read_varint(data, offset)
        field, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, offset = _pb_read_varint(data, offset)
        elif wire_type == 2:
            length, offset = _pb_read_varint(data, offset)
            end = offset + length
            if end > len(data):
                raise AceProtocolError("ACE2 protobuf field is truncated")
            value, offset = data[offset:end], end
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise AceProtocolError("ACE2 fixed32 field is truncated")
            value = struct.unpack("<I", data[offset : offset + 4])[0]
            offset += 4
        else:
            raise AceProtocolError("Unsupported ACE2 protobuf wire type: %d" % wire_type)
        fields.setdefault(field, []).append((wire_type, value))
    return fields


def _pb_read_varint(data: bytes, offset: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while offset < len(data) and shift <= 63:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
    raise AceProtocolError("ACE2 protobuf varint is truncated")


def _pb_first(fields: Mapping[int, List[Tuple[int, Any]]], field: int, default: Any) -> Any:
    return fields.get(field, [(0, default)])[0][1]


def _as_text(value: Any) -> str:
    return bytes(value).decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _decode_status(fields: Mapping[int, List[Tuple[int, Any]]]) -> Dict[str, Any]:
    work_states = {0: "init", 1: "ready", 2: "busy", 3: "upgrading"}
    dry_states = {0: "stop", 1: "drying", 2: "drying", 3: "stop", 4: "error", 5: "error"}
    slot_states = {
        0: "ready",
        1: "feeding",
        2: "unwinding",
        3: "shifting",
        4: "shifting",
        5: "preload",
        6: "upgrading",
    }
    dryer_payload = _pb_first(fields, 2, b"")
    dryer_fields = _pb_decode(dryer_payload) if dryer_payload else {}
    dryer_state = int(_pb_first(dryer_fields, 1, 0))
    slots = []
    for index, (_wire_type, slot_payload) in enumerate(fields.get(9, [])):
        slot_fields = _pb_decode(slot_payload)
        motor_state = int(_pb_first(slot_fields, 1, 0))
        filament_state = int(_pb_first(slot_fields, 2, 0))
        status = "empty" if filament_state == 0 else slot_states.get(motor_state, "error")
        slots.append(
            {
                "index": index,
                "status": status,
                "status_detail": motor_state,
                "rfid": filament_state if filament_state in {0, 1, 2, 3} else 0,
            }
        )
    return {
        "status": work_states.get(int(_pb_first(fields, 1, 0)), "unknown"),
        "temp": _pb_first(fields, 3, 0),
        "humidity": _pb_first(fields, 4, 0),
        "dryer": {
            "active": dryer_state in {1, 2},
            "status": dry_states.get(dryer_state, "unknown"),
            "target": _pb_first(dryer_fields, 2, 0),
            "duration": _pb_first(dryer_fields, 3, 0),
            "remaining": _pb_first(dryer_fields, 4, 0),
        },
        "slots": slots,
    }


__all__ = [
    "Ace2BusController",
    "Ace2BusRouter",
    "Ace2Protocol",
    "normalize_uid",
]
