"""One logical four-slot ACE device."""

from __future__ import annotations

import copy
import re
import threading
import time
from typing import Any, Callable, Dict, Mapping, Optional

from .errors import (
    AceCapabilityError,
    AceDeviceOfflineError,
    AceSafetyError,
    AceTransportError,
)


SLOT_COUNT = 4
PHYSICAL_METHODS = {
    "feed",
    "retract",
    "stop_feed",
    "stop_retract",
    "enable_feed_assist",
    "disable_feed_assist",
    "start_drying",
    "stop_drying",
}
READY_STATES = {"ready", "idle", "standby", "complete", "completed", "online"}
ERROR_STATES = {"error", "fault", "jammed", "offline", "disconnected"}
INVENTORY_FIELDS = {"material", "color", "temperature", "rfid", "status"}
SLOT_METADATA_FIELDS = {"material", "color", "temperature", "sku", "spool_id"}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, Mapping):
        return source.get(name, default)
    return getattr(source, name, default)


def _color_hex(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            channels = [max(0, min(255, int(channel))) for channel in value[:3]]
        except (TypeError, ValueError) as exc:
            raise ValueError("Slot color must use #RRGGBB or three RGB channels") from exc
        return "#%02X%02X%02X" % tuple(channels)
    text = str(value).strip()
    if COLOR_RE.fullmatch(text):
        return text.upper()
    raise ValueError("Slot color must use #RRGGBB or three RGB channels")


def _rfid_identified(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return int(value) == 2
    return str(value).strip().lower() in {"2", "identified", "recognized"}


def _inventory_values(values: Mapping[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    if "material" in values:
        normalized["material"] = str(values["material"] or "").strip()
    if "color" in values:
        normalized["color"] = _color_hex(values["color"])
    temperature = values.get("temperature", values.get("temp"))
    if temperature is not None:
        normalized["temperature"] = int(temperature)
    if "rfid" in values:
        normalized["rfid"] = values["rfid"]
    if "status" in values:
        normalized["status"] = str(values["status"]).strip().lower()
    return normalized


class AceDevice:
    """Protocol-independent device state and action boundary.

    The Manager owns the shared path. This class owns only one physical ACE,
    its four slots, transport, request stream, and cached status.
    """

    def __init__(
        self,
        config: Any,
        protocol: Any,
        transport: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.device_id = str(_value(config, "device_id", "ace0"))
        self.model = str(_value(config, "model", "ace1")).lower()
        self.serial = str(_value(config, "serial", ""))
        self.enabled = bool(_value(config, "enabled", True))
        self.rfid_enabled = bool(_value(config, "rfid_enabled", True))
        configured_actions = bool(_value(config, "physical_actions_enabled", False))
        self.physical_actions_enabled = configured_actions and self.model == "ace1"
        self.bus_id = _value(config, "bus_id")
        self.device_uid = _value(config, "device_uid")
        self.protocol = protocol
        self.transport = transport
        self.identity_verified = self.model != "ace2"
        self.clock = clock
        self._transport_open = False
        self._lock = threading.RLock()
        self._last_error: Optional[Dict[str, Any]] = None
        self._physical_state_unknown = False
        self._status: Dict[str, Any] = {
            "device_id": self.device_id,
            "model": self.model,
            "protocol": getattr(protocol, "name", self.model),
            "connected": False,
            "state": "disabled" if not self.enabled else "offline",
            "action": None,
            "temperature": None,
            "dryer": {"active": False, "target": None, "remaining": None},
            "slots": [self._empty_slot(index) for index in range(SLOT_COUNT)],
            "current_slot": None,
            "last_update": None,
            "error": None,
            "physical_state_unknown": False,
        }

    @staticmethod
    def _empty_slot(index: int) -> Dict[str, Any]:
        return {
            "index": index,
            "label": "slot%d" % (index + 1),
            "status": "unknown",
            "material": "",
            "color": "#808080",
            "temperature": None,
            "rfid": None,
        }

    @property
    def connected(self) -> bool:
        return bool(self._status["connected"])

    @property
    def capabilities(self) -> Any:
        capabilities = getattr(self.protocol, "capabilities", set())
        if hasattr(capabilities, "to_dict"):
            return capabilities.to_dict()
        return capabilities

    def open(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            try:
                self.transport.open()
                self._transport_open = True
                if self.model == "ace2" and not self.identity_verified:
                    self._status.update(
                        connected=False, state="identity_unverified", error=None
                    )
                    return
                self._status.update(connected=False, state="connecting", error=None)
            except Exception as exc:
                self._set_error("connect_failed", str(exc), retryable=True)
                raise AceTransportError(str(exc), retryable=True) from exc

    def close(self) -> None:
        with self._lock:
            try:
                self.transport.close()
            finally:
                self._transport_open = False
                self._status.update(connected=False, state="offline")

    def refresh(self) -> Dict[str, Any]:
        if self.model == "ace2" and not self.identity_verified:
            raise AceDeviceOfflineError(
                "%s has not passed UID verification" % self.device_id,
                retryable=True,
            )
        if not self._transport_open:
            self.open()
        result = self._request("get_status", allow_offline=True)
        normalizer = getattr(self.protocol, "normalize_status", None)
        normalized = normalizer(result) if normalizer else result
        self._merge_status(normalized or {})
        return self.get_status()

    def wait_ready(
        self,
        timeout: float,
        *,
        poll_interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
    ) -> Dict[str, Any]:
        """Poll until the device confirms that its accepted motion is complete."""
        deadline = self.clock() + float(timeout)
        while True:
            status = self.refresh()
            state = str(status.get("state") or "unknown").strip().lower()
            action = str(status.get("action") or "").strip().lower()
            if state in ERROR_STATES:
                raise AceTransportError(
                    "%s entered state '%s' while waiting for motion" % (self.device_id, state),
                    details={"device_id": self.device_id, "state": state},
                )
            if state in READY_STATES:
                return status
            if self.clock() >= deadline:
                self._mark_physical_unknown("motion_completion_timeout")
                raise AceTransportError(
                    "%s did not confirm motion completion" % self.device_id,
                    code="physical_state_unknown",
                    details={"device_id": self.device_id, "state": state, "action": action},
                )
            sleep(min(float(poll_interval), max(0.0, deadline - self.clock())))

    def clear_physical_state_unknown(self) -> None:
        with self._lock:
            self._physical_state_unknown = False
            self._status["physical_state_unknown"] = False

    def get_status(self, eventtime: Optional[float] = None) -> Dict[str, Any]:
        with self._lock:
            status = copy.deepcopy(self._status)
            caps = self.capabilities
            if isinstance(caps, set):
                caps = {name: True for name in sorted(caps)}
            status["capabilities"] = copy.deepcopy(caps)
            status["physical_actions_enabled"] = self.physical_actions_enabled
            status["rfid_enabled"] = self.rfid_enabled
            status["bus_id"] = self.bus_id
            status["device_uid"] = self.device_uid
            status["identity_verified"] = self.identity_verified
            status["physical_state_unknown"] = self._physical_state_unknown
            return status

    def bind_protocol(self, protocol: Any) -> None:
        """Activate an ACE2 protocol only after configured UID verification."""
        with self._lock:
            self.protocol = protocol
            self.identity_verified = True
            self._status.update(
                protocol=getattr(protocol, "name", self.model),
                connected=False,
                state="offline",
                error=None,
            )

    def set_slot_inventory(self, slot: int, values: Mapping[str, Any]) -> Dict[str, Any]:
        self._validate_slot(slot)
        normalized = _inventory_values(
            {key: value for key, value in values.items() if key in INVENTORY_FIELDS or key == "temp"}
        )
        with self._lock:
            self._status["slots"][slot].update(normalized)
            return copy.deepcopy(self._status["slots"][slot])

    def feed(self, slot: int, length: float, speed: float) -> Dict[str, Any]:
        self._assert_physical("feed")
        self._validate_motion(slot, length, speed)
        return self._request("feed", {"index": slot, "length": length, "speed": speed})

    def retract(self, slot: int, length: float, speed: float) -> Dict[str, Any]:
        self._assert_physical("retract")
        self._validate_motion(slot, length, speed)
        return self._request("retract", {"index": slot, "length": length, "speed": speed})

    def stop_feed(self, slot: int) -> Dict[str, Any]:
        self._assert_physical("stop_feed")
        self._validate_slot(slot)
        return self._request("stop_feed", {"index": slot})

    def stop_retract(self, slot: int) -> Dict[str, Any]:
        self._assert_physical("stop_retract")
        self._validate_slot(slot)
        return self._request("stop_retract", {"index": slot})

    def enable_feed_assist(self, slot: int) -> Dict[str, Any]:
        self._assert_physical("enable_feed_assist")
        self._validate_slot(slot)
        return self._request("enable_feed_assist", {"index": slot})

    def disable_feed_assist(self, slot: int) -> Dict[str, Any]:
        self._assert_physical("disable_feed_assist")
        self._validate_slot(slot)
        return self._request("disable_feed_assist", {"index": slot})

    def start_drying(self, temperature: int, duration: int) -> Dict[str, Any]:
        self._assert_physical("start_drying")
        if temperature <= 0 or duration <= 0:
            raise ValueError("Dryer temperature and duration must be positive")
        result = self._request(
            "start_drying", {"temperature": temperature, "duration": duration}
        )
        self._status["dryer"].update(active=True, target=temperature)
        return result

    def stop_drying(self) -> Dict[str, Any]:
        self._assert_physical("stop_drying")
        result = self._request("stop_drying")
        self._status["dryer"].update(active=False, remaining=0)
        return result

    def _assert_physical(self, action: str) -> None:
        if self.model == "ace2" or not self.physical_actions_enabled:
            raise AceCapabilityError(
                "Physical action '%s' is disabled for %s" % (action, self.device_id),
                details={"device_id": self.device_id, "model": self.model},
            )
        if self._physical_state_unknown:
            raise AceSafetyError(
                "%s has an unresolved physical action; run explicit recovery first"
                % self.device_id,
                code="physical_state_unknown",
                details={"device_id": self.device_id, "action": action},
            )
        if not self.connected:
            raise AceDeviceOfflineError(
                "%s is offline" % self.device_id,
                retryable=True,
                details={"device_id": self.device_id},
            )

    def _request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        allow_offline: bool = False,
    ) -> Dict[str, Any]:
        if not self.connected and not allow_offline:
            raise AceDeviceOfflineError("%s is offline" % self.device_id, retryable=True)
        try:
            payload = self.protocol.encode_request(method, params or {})
            requester = self.transport.request
            if method in PHYSICAL_METHODS:
                requester = getattr(self.transport, "request_once", requester)
            raw = requester(payload)
            response = self.protocol.decode_response(raw)
        except Exception as exc:
            self._transport_open = False
            if method in PHYSICAL_METHODS:
                self._mark_physical_unknown(str(exc))
            else:
                self._set_error("request_failed", str(exc), retryable=True)
            raise AceTransportError(
                "%s request failed: %s" % (self.device_id, exc),
                code="physical_state_unknown" if method in PHYSICAL_METHODS else None,
                retryable=method not in PHYSICAL_METHODS,
            ) from exc
        if not isinstance(response, dict):
            self._set_error("invalid_response", "Protocol returned a non-object response", retryable=False)
            raise AceTransportError("Protocol returned a non-object response")
        if response.get("ok") is False or response.get("code", 0) not in (0, None):
            message = str(response.get("message") or response.get("msg") or "ACE request failed")
            retryable = bool(response.get("retryable", False))
            self._set_error("device_rejected", message, retryable=retryable)
            raise AceTransportError(
                message,
                retryable=bool(response.get("retryable", False)),
                details={"response": response},
            )
        return response.get("result", response)

    def _merge_status(self, value: Mapping[str, Any]) -> None:
        with self._lock:
            slots = value.get("slots")
            for key in ("state", "action", "temperature", "current_slot", "dryer"):
                if key in value:
                    self._status[key] = copy.deepcopy(value[key])
            if isinstance(slots, list):
                for index, slot in enumerate(slots[:SLOT_COUNT]):
                    if isinstance(slot, Mapping):
                        incoming = copy.deepcopy(dict(slot))
                        if not self.rfid_enabled:
                            for field in SLOT_METADATA_FIELDS:
                                incoming.pop(field, None)
                            incoming["rfid"] = 0
                        else:
                            material = str(incoming.get("material") or "").strip()
                            metadata_identified = bool(material) or _rfid_identified(
                                incoming.get("rfid")
                            )
                            if not material:
                                incoming.pop("material", None)
                            if not metadata_identified:
                                for field in SLOT_METADATA_FIELDS - {"material"}:
                                    incoming.pop(field, None)
                            elif "color" in incoming:
                                try:
                                    incoming["color"] = _color_hex(incoming["color"])
                                except ValueError:
                                    incoming.pop("color", None)
                            for field in ("sku", "spool_id"):
                                if field in incoming and not str(incoming[field] or "").strip():
                                    incoming.pop(field, None)
                        self._status["slots"][index].update(incoming)
                        self._status["slots"][index]["index"] = index
            self._status.update(connected=True, last_update=self.clock(), error=None)

    def _set_error(self, code: str, message: str, *, retryable: bool) -> None:
        error = {"code": code, "message": message, "retryable": retryable}
        self._last_error = error
        self._status.update(error=error, state="error", connected=False)

    def _mark_physical_unknown(self, message: str) -> None:
        self._physical_state_unknown = True
        self._status["physical_state_unknown"] = True
        self._set_error("physical_state_unknown", str(message), retryable=False)

    @staticmethod
    def _validate_slot(slot: int) -> None:
        if not isinstance(slot, int) or not 0 <= slot < SLOT_COUNT:
            raise ValueError("Slot must be in range 0..3")

    def _validate_motion(self, slot: int, length: float, speed: float) -> None:
        self._validate_slot(slot)
        if float(length) <= 0 or float(speed) <= 0:
            raise ValueError("Length and speed must be positive")
