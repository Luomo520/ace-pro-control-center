"""Shared data models for Ace Pro Control Center.

This module contains no Klipper dependencies.  Protocol, manager, Moonraker,
and frontend adapters use these models as the common status contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SLOTS_PER_DEVICE = 4


class DeviceModel(str, Enum):
    ACE1 = "ace1"
    ACE2 = "ace2"
    AUTO = "auto"


class ConnectionState(str, Enum):
    DISABLED = "disabled"
    OFFLINE = "offline"
    CONNECTING = "connecting"
    ONLINE = "online"
    ERROR = "error"


class SlotStatus(str, Enum):
    """Normalized per-slot state exposed to all clients."""

    UNKNOWN = "unknown"
    EMPTY = "empty"
    READY = "ready"
    FEEDING = "feeding"
    RETRACTING = "retracting"
    IDENTIFYING = "identifying"
    ERROR = "error"


class DryerStatus(str, Enum):
    UNKNOWN = "unknown"
    STOPPED = "stopped"
    HEATING = "heating"
    DRYING = "drying"
    COMPLETE = "complete"
    ERROR = "error"


def _normalize_color(value: Sequence[int]) -> Tuple[int, int, int]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise ValueError("color must contain exactly three RGB channels")
    channels = tuple(int(channel) for channel in value)
    if any(channel < 0 or channel > 255 for channel in channels):
        raise ValueError("RGB channels must be between 0 and 255")
    return channels  # type: ignore[return-value]


@dataclass(frozen=True)
class CapabilitySet:
    """Actions supported by one device after all safety gates are applied."""

    status: bool = True
    refresh: bool = True
    inventory: bool = True
    feed: bool = False
    retract: bool = False
    change_tool: bool = False
    feed_assist: bool = False
    dryer: bool = False
    rfid: bool = False
    physical_actions: bool = False
    blocked_reason: Optional[str] = None

    @classmethod
    def for_device(
        cls,
        model: DeviceModel,
        physical_actions_enabled: bool,
        enabled: bool = True,
    ) -> "CapabilitySet":
        if not enabled:
            return cls(
                status=False,
                refresh=False,
                blocked_reason="device_disabled",
            )
        if model == DeviceModel.ACE2:
            return cls(
                status=True,
                refresh=True,
                inventory=True,
                rfid=True,
                physical_actions=False,
                blocked_reason="ace2_read_only",
            )
        if model == DeviceModel.AUTO:
            return cls(
                status=True,
                refresh=True,
                inventory=True,
                physical_actions=False,
                blocked_reason="device_model_unresolved",
            )
        if not physical_actions_enabled:
            return cls(
                status=True,
                refresh=True,
                inventory=True,
                rfid=True,
                physical_actions=False,
                blocked_reason="physical_actions_disabled",
            )
        return cls(
            status=True,
            refresh=True,
            inventory=True,
            feed=True,
            retract=True,
            change_tool=True,
            feed_assist=True,
            dryer=True,
            rfid=True,
            physical_actions=True,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "refresh": self.refresh,
            "inventory": self.inventory,
            "feed": self.feed,
            "retract": self.retract,
            "change_tool": self.change_tool,
            "feed_assist": self.feed_assist,
            "dryer": self.dryer,
            "rfid": self.rfid,
            "physical_actions": self.physical_actions,
            "blocked_reason": self.blocked_reason,
        }


@dataclass
class SlotInventory:
    index: int
    status: SlotStatus = SlotStatus.UNKNOWN
    material: str = ""
    color: Tuple[int, int, int] = (0, 0, 0)
    temperature: int = 0
    rfid: bool = False
    spool_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.index < 0 or self.index >= SLOTS_PER_DEVICE:
            raise ValueError("slot index must be between 0 and 3")
        if not isinstance(self.status, SlotStatus):
            self.status = SlotStatus(str(self.status).strip().lower())
        self.material = str(self.material).strip()
        self.color = _normalize_color(self.color)
        self.temperature = int(self.temperature)
        if self.temperature < 0:
            raise ValueError("slot temperature must not be negative")
        if self.spool_id is not None:
            self.spool_id = str(self.spool_id).strip() or None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "display_slot": self.index + 1,
            "status": self.status.value,
            "material": self.material,
            "color": list(self.color),
            "temperature": self.temperature,
            "rfid": self.rfid,
            "spool_id": self.spool_id,
        }


@dataclass
class DryerState:
    status: DryerStatus = DryerStatus.UNKNOWN
    current_temperature: Optional[float] = None
    target_temperature: Optional[float] = None
    remaining_seconds: Optional[int] = None
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, DryerStatus):
            self.status = DryerStatus(str(self.status).strip().lower())
        if self.remaining_seconds is not None and self.remaining_seconds < 0:
            raise ValueError("dryer remaining time must not be negative")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "current_temperature": self.current_temperature,
            "target_temperature": self.target_temperature,
            "remaining_seconds": self.remaining_seconds,
            "error": self.error,
        }


def empty_slots() -> List[SlotInventory]:
    return [SlotInventory(index=index) for index in range(SLOTS_PER_DEVICE)]


@dataclass
class DeviceStatus:
    """Normalized status for one logical ``aceN`` device."""

    device_id: str
    model: DeviceModel
    connection: ConnectionState = ConnectionState.OFFLINE
    protocol: Optional[str] = None
    capabilities: CapabilitySet = field(default_factory=CapabilitySet)
    slots: List[SlotInventory] = field(default_factory=empty_slots)
    physical_actions_enabled: bool = False
    enabled: bool = True
    current_slot: Optional[int] = None
    temperature: Optional[float] = None
    dryer: DryerState = field(default_factory=DryerState)
    error: Optional[str] = None
    error_code: Optional[str] = None
    last_update: Optional[float] = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, DeviceModel):
            self.model = DeviceModel(str(self.model).strip().lower())
        if not isinstance(self.connection, ConnectionState):
            self.connection = ConnectionState(str(self.connection).strip().lower())
        if len(self.slots) != SLOTS_PER_DEVICE:
            raise ValueError("each ACE device must expose exactly four slots")
        indexes = [slot.index for slot in self.slots]
        if indexes != list(range(SLOTS_PER_DEVICE)):
            raise ValueError("device slots must be ordered continuously from 0 to 3")
        if self.current_slot is not None and not 0 <= self.current_slot < SLOTS_PER_DEVICE:
            raise ValueError("current slot must be between 0 and 3")
        if self.model != DeviceModel.ACE1 and self.physical_actions_enabled:
            raise ValueError(
                "only ACE1 may enable physical actions in Ace Pro Control Center"
            )
        if self.capabilities.physical_actions and not self.physical_actions_enabled:
            raise ValueError("capabilities cannot bypass the physical action gate")

    @classmethod
    def initial(
        cls,
        device_id: str,
        model: DeviceModel,
        enabled: bool,
        physical_actions_enabled: bool,
    ) -> "DeviceStatus":
        effective_actions = (
            enabled
            and model == DeviceModel.ACE1
            and bool(physical_actions_enabled)
        )
        return cls(
            device_id=device_id,
            model=model,
            connection=(ConnectionState.OFFLINE if enabled else ConnectionState.DISABLED),
            capabilities=CapabilitySet.for_device(
                model=model,
                physical_actions_enabled=effective_actions,
                enabled=enabled,
            ),
            physical_actions_enabled=effective_actions,
            enabled=enabled,
        )

    def slot(self, index: int) -> SlotInventory:
        if index < 0 or index >= SLOTS_PER_DEVICE:
            raise IndexError("slot index must be between 0 and 3")
        return self.slots[index]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "model": self.model.value,
            "connection": self.connection.value,
            "protocol": self.protocol,
            "capabilities": self.capabilities.to_dict(),
            "slots": [slot.to_dict() for slot in self.slots],
            "physical_actions_enabled": self.physical_actions_enabled,
            "enabled": self.enabled,
            "current_slot": self.current_slot,
            "temperature": self.temperature,
            "dryer": self.dryer.to_dict(),
            "error": self.error,
            "error_code": self.error_code,
            "last_update": self.last_update,
        }


def statuses_to_dict(statuses: Iterable[DeviceStatus]) -> List[Dict[str, Any]]:
    return [status.to_dict() for status in statuses]


__all__ = [
    "CapabilitySet",
    "ConnectionState",
    "DeviceModel",
    "DeviceStatus",
    "DryerState",
    "DryerStatus",
    "SLOTS_PER_DEVICE",
    "SlotInventory",
    "SlotStatus",
    "empty_slots",
    "statuses_to_dict",
]
