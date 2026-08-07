"""ACE Pro generation-one JSON/RPC protocol.

Wire behavior is derived from ACEPROSV08 ``PROTOCOL.md`` and checked against
Kobra-S1/ACEPRO ``protocol_ace1.py``. The implementation is a V3 rewrite.
"""

from __future__ import annotations

import json
import struct
from typing import Any, Dict, List, Mapping, Optional

from .protocol import (
    AceProtocolError,
    AceResponseMismatchError,
    BaseProtocol,
    ProtocolCapabilities,
    crc16_mcrf4xx,
)


HEADER = b"\xFF\xAA"
TAIL = 0xFE
MIN_FRAME_SIZE = 7
MAX_PAYLOAD_SIZE = 1024


class Ace1Protocol(BaseProtocol):
    name = "ace1_json"
    capabilities = ProtocolCapabilities(
        feed=True,
        retract=True,
        feed_assist=True,
        drying=True,
        physical_actions=True,
        read_only=False,
    )

    _METHODS = {
        "get_status": "get_status",
        "get_info": "get_info",
        "get_filament_info": "get_filament_info",
        "feed": "feed_filament",
        "retract": "unwind_filament",
        "enable_feed_assist": "start_feed_assist",
        "disable_feed_assist": "stop_feed_assist",
        "stop_feed": "stop_feed_filament",
        "stop_retract": "stop_unwind_filament",
        "start_drying": "drying",
        "stop_drying": "drying_stop",
    }

    def encode_request(
        self, method: str, params: Optional[Mapping[str, Any]] = None
    ) -> bytes:
        rpc_method = self._METHODS.get(str(method), str(method))
        normalized = self._normalize_params(method, params or {})
        request_id = self._allocate_request(rpc_method)
        request: Dict[str, Any] = {"id": request_id, "method": rpc_method}
        if normalized:
            request["params"] = normalized
        try:
            payload = json.dumps(
                request, ensure_ascii=True, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError):
            self._discard_request(request_id)
            raise
        if len(payload) > MAX_PAYLOAD_SIZE:
            self._discard_request(request_id)
            raise AceProtocolError("ACE1 payload exceeds the 1024-byte safety limit")
        return (
            HEADER
            + struct.pack("<H", len(payload))
            + payload
            + struct.pack("<H", crc16_mcrf4xx(payload))
            + bytes([TAIL])
        )

    @staticmethod
    def _normalize_params(
        method: str, params: Mapping[str, Any]
    ) -> Dict[str, Any]:
        values = dict(params)
        if method in {"feed", "retract"}:
            values["index"] = int(values["index"])
            values["length"] = float(values["length"])
            values["speed"] = float(values["speed"])
        elif method in {"enable_feed_assist", "disable_feed_assist"}:
            values["index"] = int(values["index"])
        elif method == "start_drying":
            values = {
                "temp": int(values.get("temperature", values.get("temp"))),
                "fan_speed": int(values.get("fan_speed", 7000)),
                "duration": int(values["duration"]),
            }
        return values

    def decode_response(self, payload: bytes) -> Dict[str, Any]:
        responses = self.decode_frames(payload)
        if not responses:
            raise AceProtocolError("ACE1 response contains no complete frame")
        pending = set(self.pending_request_ids)
        response = next(
            (item for item in responses if not pending or item.get("id") in pending),
            None,
        )
        if response is None:
            raise AceResponseMismatchError(
                "ACE1 response does not match a pending request"
            )
        request_id = response.get("id")
        if not isinstance(request_id, int):
            raise AceProtocolError("ACE1 response is missing an integer request ID")
        self._match_response(request_id)
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
            if len(working) - start < MIN_FRAME_SIZE:
                raise AceProtocolError("ACE1 response frame is truncated")
            payload_len = struct.unpack("<H", working[start + 2 : start + 4])[0]
            if payload_len > MAX_PAYLOAD_SIZE:
                raise AceProtocolError("ACE1 response payload is too large")
            end = start + MIN_FRAME_SIZE + payload_len
            if end > len(working):
                raise AceProtocolError("ACE1 response frame is truncated")
            frame = working[start:end]
            if frame[-1] != TAIL:
                raise AceProtocolError("ACE1 response has an invalid frame tail")
            body = frame[4 : 4 + payload_len]
            received_crc = struct.unpack("<H", frame[4 + payload_len : 6 + payload_len])[0]
            if received_crc != crc16_mcrf4xx(body):
                raise AceProtocolError("ACE1 response CRC mismatch")
            try:
                decoded = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise AceProtocolError("ACE1 response contains invalid JSON") from exc
            if not isinstance(decoded, dict):
                raise AceProtocolError("ACE1 response JSON must be an object")
            responses.append(decoded)
            offset = end
        return responses

    def normalize_status(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        value = payload.get("result", payload)
        if not isinstance(value, Mapping):
            raise AceProtocolError("ACE1 status result must be an object")
        raw_dryer = value.get("dryer_status") or {}
        if not isinstance(raw_dryer, Mapping):
            raw_dryer = {}
        slots = []
        for index, raw_slot in enumerate(value.get("slots") or []):
            if not isinstance(raw_slot, Mapping):
                continue
            slot_index = int(raw_slot.get("index", index))
            color = _normalize_color(raw_slot.get("color"))
            slots.append(
                {
                    "index": slot_index,
                    "status": str(raw_slot.get("status", "unknown")),
                    "material": str(raw_slot.get("type") or raw_slot.get("material") or ""),
                    "color": color,
                    "rfid": raw_slot.get("rfid"),
                    "sku": raw_slot.get("sku"),
                }
            )
        return {
            "state": str(value.get("status", "unknown")),
            "temperature": value.get("temp"),
            "action": value.get("action"),
            "dryer": {
                "active": raw_dryer.get("status") == "drying",
                "status": raw_dryer.get("status", "stop"),
                "target": raw_dryer.get("target_temp"),
                "remaining": raw_dryer.get("remain_time"),
                "duration": raw_dryer.get("duration"),
            },
            "slots": slots,
        }

    def get_status(self) -> bytes:
        return self.encode_request("get_status")

    def get_info(self) -> bytes:
        return self.encode_request("get_info")

    def feed(self, index: int, length: float, speed: float) -> bytes:
        return self.encode_request(
            "feed", {"index": index, "length": length, "speed": speed}
        )

    def retract(self, index: int, length: float, speed: float) -> bytes:
        return self.encode_request(
            "retract", {"index": index, "length": length, "speed": speed}
        )

    def start_drying(self, temperature: int, duration: int) -> bytes:
        return self.encode_request(
            "start_drying", {"temperature": temperature, "duration": duration}
        )

    def stop_drying(self) -> bytes:
        return self.encode_request("stop_drying")


def _normalize_color(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        return text if text.startswith("#") else "#" + text
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        channels = [max(0, min(255, int(item))) for item in value[:3]]
        return "#%02X%02X%02X" % tuple(channels)
    return "#808080"


__all__ = ["Ace1Protocol"]
