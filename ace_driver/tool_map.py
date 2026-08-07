"""Stable mapping between global tools and configured ACE slots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterator, Optional, Union

from .models import SLOTS_PER_DEVICE


MAX_DEVICES = 4
UNLOAD_TOOL = -1


class ToolMapError(ValueError):
    pass


@dataclass(frozen=True)
class ToolTarget:
    tool: int
    device_index: int
    device_id: str
    slot: int

    @property
    def tool_name(self) -> str:
        return "T%d" % self.tool

    @property
    def display_slot(self) -> int:
        return self.slot + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "tool_name": self.tool_name,
            "device_index": self.device_index,
            "device_id": self.device_id,
            "slot": self.slot,
            "display_slot": self.display_slot,
        }


class ToolMap:
    """Configured-order mapping that is independent of USB enumeration."""

    def __init__(self, device_count: int):
        if isinstance(device_count, bool):
            raise ToolMapError("device_count must be an integer")
        try:
            device_count = int(device_count)
        except (TypeError, ValueError) as exc:
            raise ToolMapError("device_count must be an integer") from exc
        if device_count < 1 or device_count > MAX_DEVICES:
            raise ToolMapError("device_count must be between 1 and 4")
        self.device_count = device_count

    @property
    def tool_count(self) -> int:
        return self.device_count * SLOTS_PER_DEVICE

    def resolve(self, tool: Union[int, str]) -> Optional[ToolTarget]:
        tool_index = parse_tool(tool)
        if tool_index == UNLOAD_TOOL:
            return None
        if tool_index >= self.tool_count:
            raise ToolMapError(
                "T%d is not configured; valid tools are T0 through T%d"
                % (tool_index, self.tool_count - 1)
            )
        device_index, slot = divmod(tool_index, SLOTS_PER_DEVICE)
        return ToolTarget(
            tool=tool_index,
            device_index=device_index,
            device_id="ace%d" % device_index,
            slot=slot,
        )

    def for_slot(self, device: Union[int, str], slot: int) -> ToolTarget:
        device_index = parse_device_index(device)
        try:
            slot = int(slot)
        except (TypeError, ValueError) as exc:
            raise ToolMapError("slot must be an integer between 0 and 3") from exc
        if device_index >= self.device_count:
            raise ToolMapError("ace%d is not configured" % device_index)
        if slot < 0 or slot >= SLOTS_PER_DEVICE:
            raise ToolMapError("slot must be between 0 and 3")
        return self.resolve(device_index * SLOTS_PER_DEVICE + slot)  # type: ignore[return-value]

    def mappings(self) -> Iterator[ToolTarget]:
        for tool_index in range(self.tool_count):
            target = self.resolve(tool_index)
            if target is not None:
                yield target

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_count": self.device_count,
            "tool_count": self.tool_count,
            "tools": [target.to_dict() for target in self.mappings()],
        }


def parse_tool(tool: Union[int, str]) -> int:
    if isinstance(tool, bool):
        raise ToolMapError("boolean values are not valid tools")
    if isinstance(tool, int):
        tool_index = tool
    else:
        value = str(tool).strip().upper()
        if value in ("TR", "-1"):
            return UNLOAD_TOOL
        if value.startswith("T"):
            value = value[1:]
        if not value or not value.isdigit():
            raise ToolMapError("tool must be T0..T15 or TR")
        tool_index = int(value)
    if tool_index == UNLOAD_TOOL:
        return UNLOAD_TOOL
    if tool_index < 0 or tool_index >= MAX_DEVICES * SLOTS_PER_DEVICE:
        raise ToolMapError("tool must be T0..T15 or TR")
    return tool_index


def parse_device_index(device: Union[int, str]) -> int:
    if isinstance(device, bool):
        raise ToolMapError("boolean values are not valid device indexes")
    if isinstance(device, int):
        index = device
    else:
        value = str(device).strip().lower()
        if value.startswith("ace"):
            value = value[3:]
        if not value.isdigit():
            raise ToolMapError("device must be ace0..ace3")
        index = int(value)
    if index < 0 or index >= MAX_DEVICES:
        raise ToolMapError("device must be ace0..ace3")
    return index


__all__ = [
    "MAX_DEVICES",
    "ToolMap",
    "ToolMapError",
    "ToolTarget",
    "UNLOAD_TOOL",
    "parse_device_index",
    "parse_tool",
]
