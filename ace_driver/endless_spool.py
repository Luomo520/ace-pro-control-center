"""Pure endless-spool candidate selection for a shared filament path."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

from .models import ConnectionState, DeviceStatus, SlotInventory, SlotStatus
from .tool_map import ToolMap, ToolMapError, ToolTarget, parse_tool


UNKNOWN_MATERIALS = {"", "?", "???", "unknown", "n/a", "none", "null"}


class MatchMode(str, Enum):
    EXACT = "exact"
    MATERIAL = "material"


@dataclass(frozen=True)
class EndlessSpoolDecision:
    candidate: Optional[ToolTarget]
    candidates: Tuple[ToolTarget, ...]
    reason: str
    rejected: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict() if self.candidate else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "reason": self.reason,
            "rejected": dict(self.rejected),
        }


class EndlessSpoolSelector:
    """Selects candidates only; it never performs a physical action."""

    def __init__(
        self,
        tool_map: ToolMap,
        match_mode: Union[MatchMode, str] = MatchMode.EXACT,
        allow_cross_device: bool = True,
    ):
        self.tool_map = tool_map
        try:
            self.match_mode = (
                match_mode
                if isinstance(match_mode, MatchMode)
                else MatchMode(str(match_mode).strip().lower())
            )
        except ValueError as exc:
            raise ValueError("match_mode must be exact or material") from exc
        self.allow_cross_device = bool(allow_cross_device)

    def select(
        self,
        current_tool: Union[int, str],
        devices: Sequence[DeviceStatus],
        excluded_tools: Iterable[Union[int, str]] = (),
    ) -> EndlessSpoolDecision:
        try:
            current_index = parse_tool(current_tool)
            source_target = self.tool_map.resolve(current_index)
        except ToolMapError as exc:
            return EndlessSpoolDecision(None, (), "invalid_current_tool", {"current": str(exc)})
        if source_target is None:
            return EndlessSpoolDecision(None, (), "no_current_tool", {})
        by_id = {device.device_id: device for device in devices}
        source_device = by_id.get(source_target.device_id)
        if source_device is None:
            return EndlessSpoolDecision(None, (), "source_device_missing", {})
        source_slot = source_device.slot(source_target.slot)
        source_material = _material(source_slot)
        if source_material in UNKNOWN_MATERIALS:
            return EndlessSpoolDecision(None, (), "source_material_unknown", {})
        excluded: Set[int] = {current_index}
        for tool in excluded_tools:
            try:
                parsed = parse_tool(tool)
            except ToolMapError:
                continue
            if parsed >= 0:
                excluded.add(parsed)

        candidates: List[ToolTarget] = []
        rejected: Dict[str, str] = {}
        for target in self.tool_map.mappings():
            if target.tool in excluded:
                continue
            if not self.allow_cross_device and target.device_id != source_target.device_id:
                rejected[target.tool_name] = "cross_device_disabled"
                continue
            device = by_id.get(target.device_id)
            if device is None:
                rejected[target.tool_name] = "device_missing"
                continue
            blocked_reason = _device_block_reason(device)
            if blocked_reason:
                rejected[target.tool_name] = blocked_reason
                continue
            slot = device.slot(target.slot)
            if slot.status != SlotStatus.READY:
                rejected[target.tool_name] = "slot_not_ready"
                continue
            if not _matches(source_slot, slot, self.match_mode):
                rejected[target.tool_name] = "material_mismatch"
                continue
            candidates.append(target)

        candidates.sort(
            key=lambda target: (
                (target.tool - current_index) % self.tool_map.tool_count,
                target.tool,
            )
        )
        if not candidates:
            return EndlessSpoolDecision(None, (), "no_safe_candidate", rejected)
        return EndlessSpoolDecision(
            candidate=candidates[0],
            candidates=tuple(candidates),
            reason="candidate_selected",
            rejected=rejected,
        )


def _material(slot: SlotInventory) -> str:
    return slot.material.strip().lower()


def _matches(source: SlotInventory, candidate: SlotInventory, mode: MatchMode) -> bool:
    source_material = _material(source)
    candidate_material = _material(candidate)
    if source_material in UNKNOWN_MATERIALS or candidate_material in UNKNOWN_MATERIALS:
        return False
    if source_material != candidate_material:
        return False
    if mode == MatchMode.MATERIAL:
        return True
    return tuple(source.color) == tuple(candidate.color)


def _device_block_reason(device: DeviceStatus) -> Optional[str]:
    if not device.enabled:
        return "device_disabled"
    if device.connection != ConnectionState.ONLINE:
        return "device_offline"
    if not device.physical_actions_enabled:
        return device.capabilities.blocked_reason or "physical_actions_disabled"
    if not device.capabilities.physical_actions or not device.capabilities.change_tool:
        return device.capabilities.blocked_reason or "tool_change_unsupported"
    return None


def select_candidate(
    current_tool: Union[int, str],
    devices: Sequence[DeviceStatus],
    tool_map: ToolMap,
    match_mode: Union[MatchMode, str] = MatchMode.EXACT,
    excluded_tools: Iterable[Union[int, str]] = (),
) -> EndlessSpoolDecision:
    return EndlessSpoolSelector(tool_map, match_mode).select(
        current_tool,
        devices,
        excluded_tools,
    )


__all__ = [
    "EndlessSpoolDecision",
    "EndlessSpoolSelector",
    "MatchMode",
    "UNKNOWN_MATERIALS",
    "select_candidate",
]
