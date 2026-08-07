"""Global orchestration for one shared toolhead and up to four ACE devices."""

from __future__ import annotations

import contextlib
import copy
import logging
import math
import threading
import time
import uuid
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

from . import PRODUCT_NAME_ZH, __version__
from .config import (
    DEFAULT_MATERIAL_TYPES,
    TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX,
)
from .device import AceDevice, SLOT_COUNT
from .endless_spool import EndlessSpoolSelector
from .errors import AceBusyError, AceError, AceSafetyError
from .i18n import localize_exception, localize_message
from .models import (
    ConnectionState,
    DeviceModel,
    DeviceStatus,
    SlotInventory,
    SlotStatus,
)
from .safety import SafetyContext, SafetyPolicy
from .tool_map import ToolMap


RECOVERY_PRINT_STATES = {"idle", "standby", "ready", "complete", "completed"}
RECOVERY_DEVICE_STATES = {"idle", "standby", "ready", "complete", "completed"}
TOOLCHANGE_NOTICE_LIMIT = 64
TOOLCHANGE_NOTICE_CODE = "ACE_TOOLCHANGE_NOT_CONFIGURED"
ACE_FEED_MONITOR_WINDOW_SECONDS = 2.0
ACE_FEED_NO_PROGRESS_SLEEP = 0.1
ENCODER_PRINT_MODES = {"off", "monitor", "pause"}
AUTOMATIC_TOOLCHANGE_HOOKS = (
    "pre_toolchange",
    "cut",
    "load_to_toolhead",
    "unload_from_toolhead",
    "wipe_nozzle",
    "post_toolchange",
    "pause_on_error",
)
MACHINE_HOOKS_REQUIRED_DETAIL = (
    "ACE 自动换料必须完整配置七个机器动作宏；V3 不支持尖端成型，"
    "因此切刀宏为必用项"
)
ENCODER_PRINT_POSSIBLE_CAUSES = (
    "耗材可能已经用尽、发生卡料或打滑，也可能没有经过共享编码器。",
    "共享编码器可能断开、配置不正确或未产生脉冲。",
)


def parse_tool(value: Any, device_count: int) -> Optional[int]:
    """Parse T0..T15 or TR. Return None for unload."""
    if value is None:
        raise ValueError("TOOL is required")
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in {"TR", "-1"}:
            return None
        if normalized.startswith("T"):
            normalized = normalized[1:]
        value = normalized
    tool = int(value)
    if tool == -1:
        return None
    maximum = device_count * SLOT_COUNT
    if not 0 <= tool < maximum:
        raise ValueError("Tool must be T0..T%d or TR" % (maximum - 1))
    return tool


def tool_target(tool: int) -> Tuple[int, int]:
    if not 0 <= int(tool) < 16:
        raise ValueError("Tool must be in range T0..T15")
    return int(tool) // SLOT_COUNT, int(tool) % SLOT_COUNT


class AceManager:
    """Serialize all physical actions through a single global path lock."""

    def __init__(
        self,
        devices: Iterable[AceDevice],
        *,
        shared: Optional[Any] = None,
        machine_hook: Optional[Callable[[str, Mapping[str, Any]], None]] = None,
        machine_hook_validator: Optional[Callable[[Iterable[str]], None]] = None,
        extruder_preflight: Optional[Callable[[Iterable[float]], None]] = None,
        sensor_state: Optional[Callable[[str], Optional[bool]]] = None,
        safety: Optional[SafetyPolicy] = None,
        print_state: Optional[Callable[[], str]] = None,
        state_store: Optional[Any] = None,
        encoder: Optional[Any] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.devices = list(devices)
        if not 1 <= len(self.devices) <= 4:
            raise ValueError("ACE device count must be in range 1..4")
        expected = ["ace%d" % index for index in range(len(self.devices))]
        actual = [device.device_id for device in self.devices]
        if actual != expected:
            raise ValueError("ACE devices must be continuous and ordered: %s" % expected)
        self.shared = shared or {}
        self.machine_hook = machine_hook
        self.machine_hook_validator = machine_hook_validator
        self.extruder_preflight = extruder_preflight
        self.sensor_state = sensor_state
        self.safety = safety or SafetyPolicy()
        self._print_state = print_state or (lambda: "standby")
        self.state_store = state_store
        self.encoder = encoder
        self._encoder_runtime_fault: Optional[Dict[str, Any]] = None
        self.clock = clock
        self.sleep = sleep
        self._encoder_print_mode = str(
            self._shared("encoder_print_mode", "off")
        ).strip().lower()
        if self._encoder_print_mode not in ENCODER_PRINT_MODES:
            raise ValueError("encoder_print_mode 只能填写 off、monitor 或 pause")
        self._encoder_print_detection_length = float(
            self._shared("encoder_print_detection_length", 20)
        )
        if (
            not math.isfinite(self._encoder_print_detection_length)
            or self._encoder_print_detection_length <= 0
        ):
            raise ValueError(
                "encoder_print_detection_length 必须是大于零的有限数值"
            )
        self._encoder_print_active = False
        self._encoder_print_state = (
            "off"
            if self._encoder_print_mode == "off"
            else "unavailable" if self.encoder is None else "inactive"
        )
        self._encoder_print_inactive_reason: Optional[str] = None
        self._encoder_print_last_position: Optional[float] = None
        self._encoder_print_last_counts: Optional[int] = None
        self._encoder_print_retraction = 0.0
        self._encoder_print_extrusion_since_motion = 0.0
        self._encoder_print_event_sequence = 0
        self._encoder_print_last_event: Optional[Dict[str, Any]] = None
        self._encoder_print_fault: Optional[Dict[str, Any]] = None
        self._encoder_print_fault_counts: Optional[int] = None
        self.toolchange_mode = str(
            self._shared("toolchange_mode", "automatic")
        ).strip().lower()
        if self.toolchange_mode not in {"manual", "automatic"}:
            raise ValueError("toolchange_mode must be manual or automatic")
        self._path_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._transaction: Optional[Dict[str, Any]] = None
        self._last_transaction: Optional[Dict[str, Any]] = None
        self._toolchange_notice_sequence = 0
        self._toolchange_notices = []
        self.feed_assist_tool: Optional[int] = None
        saved_tool = self._state_get("current_tool", None)
        self.current_tool = parse_tool(saved_tool, len(self.devices)) if saved_tool is not None else None
        default_path_state = "nozzle" if self.current_tool is not None else "empty"
        self.path_state = str(self._state_get("path_state", default_path_state))
        self.endless_spool_enabled = bool(self._state_get("endless_spool_enabled", False))
        self.endless_spool_match_mode = str(
            self._state_get(
                "endless_spool_match_mode",
                self._shared("endless_spool_match_mode", "exact"),
            )
        )
        self._restore_encoder_state()

    def restore_state(self) -> None:
        """Reload persisted state after all Klipper config objects are available."""
        saved_tool = self._state_get("current_tool", None)
        self.current_tool = (
            parse_tool(saved_tool, len(self.devices)) if saved_tool is not None else None
        )
        default_path_state = "nozzle" if self.current_tool is not None else "empty"
        self.path_state = str(self._state_get("path_state", default_path_state))
        self.endless_spool_enabled = bool(
            self._state_get("endless_spool_enabled", self.endless_spool_enabled)
        )
        self.endless_spool_match_mode = str(
            self._state_get("endless_spool_match_mode", self.endless_spool_match_mode)
        )
        self._restore_encoder_state()
        inventories = self._state_get("inventory", [])
        if isinstance(inventories, list):
            for device_index, slots in enumerate(inventories[: len(self.devices)]):
                if not isinstance(slots, list):
                    continue
                for slot_index, values in enumerate(slots[:SLOT_COUNT]):
                    if isinstance(values, Mapping):
                        self.devices[device_index].set_slot_inventory(slot_index, values)

    @property
    def path_busy(self) -> bool:
        return self._path_lock.locked()

    def get_toolchange_readiness(self) -> Dict[str, Any]:
        if self.toolchange_mode != "automatic":
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "manual_mode",
                "blocked_detail": "当前处于手动模式，ACE 自动换料未启用。",
            }
        actionable = any(
            device.enabled
            and device.model == "ace1"
            and device.physical_actions_enabled
            for device in self.devices
        )
        if not actionable:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "physical_actions_disabled",
                "blocked_detail": "没有任何 ACE1 设备启用物理动作。",
            }
        try:
            self._validate_hooks(AUTOMATIC_TOOLCHANGE_HOOKS)
        except Exception as exc:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "machine_hooks_incomplete",
                "blocked_detail": "%s。请检查机器宏配置：%s"
                % (MACHINE_HOOKS_REQUIRED_DETAIL, localize_exception(exc)),
            }
        encoder_status = self._encoder_status()
        if encoder_status.get("calibration_active"):
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "encoder_calibration_active",
                "blocked_detail": "共享耗材编码器正在校准。",
            }
        if encoder_status["mode"] == "protect" and not encoder_status["armed"]:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "encoder_not_ready",
                "blocked_detail": (
                    "共享耗材编码器处于保护模式，但编码器不可用或尚未完成校准。"
                ),
            }
        if self.sensor_state is None:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "path_sensors_incomplete",
                "blocked_detail": (
                    "自动换料必须配置可读取状态的上方耗材传感器。"
                ),
            }
        lower_bypassed = self._lower_sensor_bypassed()
        bypass_load_length = self._lower_sensor_bypass_load_length()
        if lower_bypassed and (
            not math.isfinite(bypass_load_length)
            or bypass_load_length <= 0
            or bypass_load_length > TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX
        ):
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "lower_sensor_bypass_uncalibrated",
                "blocked_detail": (
                    "旁路下方耗材传感器时，必须实测 "
                    "toolhead_sensor_bypass_load_length，并在确认后设置 "
                    "toolhead_sensor_bypass_calibrated: True；距离应大于零且不超过 %.1f mm。"
                    % TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX
                ),
            }
        try:
            sensors = self._sensor_snapshot(strict=True, for_control=True)
        except Exception as exc:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "path_sensors_incomplete",
                "blocked_detail": localize_exception(exc),
            }
        required_sensors = ("upper",) if lower_bypassed else ("upper", "lower")
        missing = [name for name in required_sensors if sensors.get(name) is None]
        if missing:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "path_sensors_incomplete",
                "blocked_detail": (
                    "以下必需的耗材传感器尚未配置：%s。"
                    % "、".join(
                        {"upper": "上方", "lower": "下方"}.get(name, name)
                        for name in missing
                    )
                ),
            }
        if len(self.devices) > 1 and sensors.get("rdm") is None:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "total_hub_sensor_missing",
                "blocked_detail": (
                    "多台 ACE 自动换料必须配置总五通传感器。"
                ),
            }
        uncalibrated = [
            device.device_id
            for device in self.devices
            if device.enabled
            and device.model == "ace1"
            and device.physical_actions_enabled
            and len(self.devices) > 1
            and self._hub_retract_length(device.device_id) <= 0
        ]
        if uncalibrated:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "branch_clearance_incomplete",
                "blocked_detail": (
                    "以下 ACE 分支尚未校准退出五通的回抽距离：%s。"
                    % ", ".join(uncalibrated)
                ),
            }
        if lower_bypassed and not self._lower_sensor_bypass_calibrated():
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "lower_sensor_bypass_uncalibrated",
                "blocked_detail": (
                    "旁路下方耗材传感器时，必须实测 "
                    "toolhead_sensor_bypass_load_length，并在确认后设置 "
                    "toolhead_sensor_bypass_calibrated: True；距离应大于零且不超过 %.1f mm。"
                    % TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX
                ),
            }
        if self.path_state not in {"empty", "nozzle"}:
            return {
                "mode": self.toolchange_mode,
                "ready": False,
                "blocked_reason": "path_state_unknown",
                "blocked_detail": "共享耗材路径状态未知，需要先检查并恢复。",
            }
        return {
            "mode": self.toolchange_mode,
            "ready": True,
            "blocked_reason": None,
            "blocked_detail": None,
        }

    def start(self) -> None:
        for device in self.devices:
            if device.enabled:
                try:
                    device.open()
                    device.refresh()
                except AceError:
                    # One offline device must not hide the remaining configured units.
                    continue

    def stop(self) -> None:
        for device in self.devices:
            try:
                device.close()
            except Exception:
                continue

    def refresh(
        self, device_id: Optional[str] = None, device: Optional[str] = None
    ) -> Dict[str, Any]:
        device_id = device_id if device_id is not None else device
        targets = self.devices if device_id is None else [self.get_device(device_id)]
        errors = []
        for device in targets:
            try:
                if not device.connected:
                    device.open()
                device.refresh()
            except AceError as exc:
                errors.append({"device_id": device.device_id, "error": exc.to_dict()})
        status = self.get_status()
        status["refresh_errors"] = errors
        return status

    def get_device(self, value: Any) -> AceDevice:
        if isinstance(value, int):
            index = value
        else:
            text = str(value).strip().lower()
            index = int(text[3:]) if text.startswith("ace") else int(text)
        if not 0 <= index < len(self.devices):
            raise ValueError("ACE device is not configured")
        return self.devices[index]

    def get_status(self, eventtime: Optional[float] = None) -> Dict[str, Any]:
        del eventtime
        with self._state_lock:
            current = None if self.current_tool is None else "T%d" % self.current_tool
            readiness = self.get_toolchange_readiness()
            material_types = self._shared("material_types", DEFAULT_MATERIAL_TYPES)
            if isinstance(material_types, str):
                material_types = tuple(
                    item.strip() for item in material_types.split(",")
                )
            devices = []
            for index, device in enumerate(self.devices):
                status = device.get_status()
                for slot in status.get("slots", []):
                    tool = index * SLOT_COUNT + int(slot["index"])
                    slot["tool"] = "T%d" % tool
                    slot["loaded"] = (
                        self.path_state == "nozzle"
                        and self.current_tool == tool
                    )
                    slot["feed_assist"] = self.feed_assist_tool == tool
                device_ready = (
                    readiness["ready"]
                    and device.model == "ace1"
                    and device.physical_actions_enabled
                )
                capabilities = status.get("capabilities")
                if isinstance(capabilities, dict):
                    capabilities.update(
                        select_tool=device_ready,
                        change_tool=device_ready,
                        unload=device_ready,
                    )
                status["toolchange_ready"] = device_ready
                status["toolchange_blocked_reason"] = (
                    None if device_ready else readiness["blocked_reason"]
                )
                status["feed_assist_slot"] = (
                    self.feed_assist_tool % SLOT_COUNT
                    if self.feed_assist_tool is not None
                    and self.feed_assist_tool // SLOT_COUNT == index
                    else None
                )
                devices.append(status)
            latest_notice = (
                copy.deepcopy(self._toolchange_notices[-1])
                if self._toolchange_notices
                else None
            )
            configured_endless = self.endless_spool_enabled
            effective_endless = configured_endless and readiness["ready"]
            sensor_snapshot = self._sensor_snapshot()
            result = {
                "schema_version": 3,
                "driver_version": __version__,
                "device_count": len(self.devices),
                "material_types": list(material_types),
                "current_tool": current,
                "current_tool_index": self.current_tool,
                "print_state": self._print_state(),
                "toolchange_mode": readiness["mode"],
                "toolchange_ready": readiness["ready"],
                "toolchange_blocked_reason": readiness["blocked_reason"],
                "toolchange_blocked_detail": readiness["blocked_detail"],
                "toolchange": copy.deepcopy(readiness),
                "toolchange_notice": latest_notice,
                "toolchange_notices": copy.deepcopy(self._toolchange_notices),
                "capabilities": {
                    "select_tool": readiness["ready"],
                    "change_tool": readiness["ready"],
                    "unload": readiness["ready"],
                    "set_endless_spool": readiness["ready"],
                    "endless_spool": readiness["ready"],
                    "recover": True,
                },
                "path": {
                    "busy": self.path_busy,
                    "state": self.path_state,
                    "sensors": self._status_sensor_snapshot(sensor_snapshot),
                    "sensor_policy": self._sensor_policy_status(),
                    "topology": self._topology_status(sensor_snapshot),
                    "encoders": {"shared": self._encoder_status()},
                    "transaction": copy.deepcopy(self._transaction),
                    "last_transaction": copy.deepcopy(self._last_transaction),
                },
                "endless_spool": {
                    "enabled": effective_endless,
                    "configured_enabled": configured_endless,
                    "match_mode": self.endless_spool_match_mode,
                },
                "feed_assist": self._feed_assist_status(),
                "devices": devices,
            }
            if effective_endless and self.current_tool is not None:
                result["endless_spool"]["decision"] = self._select_endless_candidate().to_dict()
            return result

    def perform_action(
        self,
        action: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        confirmed: bool = False,
        source: str = "gcode",
    ) -> Dict[str, Any]:
        params = dict(params or {})
        handlers = {
            "select_tool": self.change_tool,
            "unload": self.unload,
            "feed": self.feed,
            "retract": self.retract,
            "start_drying": self.start_drying,
            "stop_drying": self.stop_drying,
            "enable_feed_assist": self.enable_feed_assist,
            "disable_feed_assist": self.disable_feed_assist,
            "set_slot": self.set_slot,
            "refresh": self.refresh,
            "reconnect": self.reconnect,
            "set_endless_spool": self.set_endless_spool,
            "endless_spool_change": self.handle_runout,
        }
        handler = handlers.get(str(action))
        if handler is None:
            raise ValueError("Unsupported ACE action: %s" % action)
        if action == "select_tool":
            result = handler(params.get("tool"), confirmed=confirmed, source=source)
        elif action == "unload":
            result = handler(confirmed=confirmed, source=source)
        elif action in {
            "feed",
            "retract",
            "start_drying",
            "stop_drying",
            "enable_feed_assist",
            "disable_feed_assist",
        }:
            result = handler(params, confirmed=confirmed, source=source)
        elif action == "endless_spool_change":
            result = handler()
        else:
            result = handler(**params)
        return {"ok": True, "action": action, "result": result}

    def handle_tool_command(self, value: Any) -> Dict[str, Any]:
        readiness = self.get_toolchange_readiness()
        if readiness["ready"]:
            return self.change_tool(value, confirmed=True, source="gcode")
        command = self._tool_command_name(value)
        notice = self._record_toolchange_notice(command, readiness)
        return {
            "changed": False,
            "ignored": True,
            "command": command,
            "current_tool": (
                None if self.current_tool is None else "T%d" % self.current_tool
            ),
            "reason": readiness["blocked_reason"],
            "notice": notice,
        }

    def change_tool(
        self, value: Any, *, confirmed: bool = False, source: str = "gcode"
    ) -> Dict[str, Any]:
        self._assert_toolchange_ready()
        target = parse_tool(value, len(self.devices))
        if target is None:
            return self.unload(confirmed=confirmed, source=source)
        if target == self.current_tool:
            return {"changed": False, "current_tool": "T%d" % target}
        target_index, target_slot = tool_target(target)
        target_device = self.devices[target_index]
        context = SafetyContext(
            "select_tool", confirmed, source, self._print_state()
        )
        self.safety.assert_allowed(target_device, context)
        self._assert_path_available()
        self._assert_target_ready(target_device, target, target_slot)
        hooks = [
            "pre_toolchange",
            "load_to_toolhead",
            "wipe_nozzle",
            "post_toolchange",
            "pause_on_error",
        ]
        if self.current_tool is not None:
            hooks.extend(("cut", "unload_from_toolhead"))
        self._validate_hooks(hooks)

        with self._transaction_scope("select_tool", target="T%d" % target):
            old_tool = self.current_tool
            try:
                self._run_hook("pre_toolchange", {"from": old_tool, "to": target})
                self._preflight_toolhead_moves(
                    loading=True, unloading=old_tool is not None
                )
                if old_tool is not None:
                    self._unload_tool(old_tool, context)
                    # Once retraction succeeds, preserving the old tool would
                    # lie about the physical path if loading the target fails.
                    self.current_tool = None
                    self._state_set("current_tool", None)
                self._load_tool(target, context)
                self.current_tool = target
                self._state_set("current_tool", target)
                self._run_hook("wipe_nozzle", {"from": old_tool, "to": target})
                self._run_hook("post_toolchange", {"from": old_tool, "to": target})
            except Exception:
                try:
                    self._run_hook("pause_on_error", {"from": old_tool, "to": target})
                except Exception:
                    pass
                raise
        return {"changed": True, "from": old_tool, "current_tool": "T%d" % target}

    def unload(
        self, *, confirmed: bool = False, source: str = "gcode"
    ) -> Dict[str, Any]:
        self._assert_toolchange_ready()
        if self.current_tool is None:
            return {"changed": False, "current_tool": None}
        old_tool = self.current_tool
        index, _ = tool_target(old_tool)
        context = SafetyContext("unload", confirmed, source, self._print_state())
        self.safety.assert_allowed(self.devices[index], context)
        self._assert_path_available()
        self._validate_hooks(
            (
                "pre_toolchange",
                "cut",
                "unload_from_toolhead",
                "post_toolchange",
                "pause_on_error",
            )
        )
        with self._transaction_scope("unload", target="T%d" % old_tool):
            try:
                self._run_hook("pre_toolchange", {"from": old_tool, "to": None})
                self._preflight_toolhead_moves(loading=False, unloading=True)
                self._unload_tool(old_tool, context)
                self.current_tool = None
                self._state_set("current_tool", None)
                self._run_hook("post_toolchange", {"from": old_tool, "to": None})
            except Exception:
                try:
                    self._run_hook("pause_on_error", {"from": old_tool, "to": None})
                except Exception:
                    pass
                raise
        return {"changed": True, "from": old_tool, "current_tool": None}

    def feed(self, params: Mapping[str, Any], *, confirmed: bool, source: str) -> Any:
        tool = parse_tool(params.get("tool"), len(self.devices))
        if tool is None:
            raise ValueError("feed requires a tool")
        index, slot = tool_target(tool)
        device = self.devices[index]
        self.safety.assert_allowed(
            device, SafetyContext("feed", confirmed, source, self._print_state())
        )
        self._assert_manual_motion_path(tool)
        previous_path_state = self.path_state
        with self._transaction_scope("feed", target="T%d" % tool):
            length = float(params["length"])
            speed = float(params.get("speed", self._shared("feed_speed", 80)))
            encoder_token = self._start_ace_motion(
                device,
                "feed",
                length,
                required=previous_path_state == "nozzle",
            )
            try:
                result = device.feed(slot, length, speed)
                self._wait_for_motion(device, result, length, speed)
            except Exception as exc:
                self._cancel_ace_motion(encoder_token)
                self._set_path_unknown(str(exc))
                raise
            self._finish_ace_motion(
                device,
                slot,
                "feed",
                encoder_token,
                command_completed=self._motion_completed(result),
            )
            self._finalize_manual_motion(tool, "feed", previous_path_state)
            return result

    def retract(self, params: Mapping[str, Any], *, confirmed: bool, source: str) -> Any:
        tool = parse_tool(params.get("tool"), len(self.devices))
        if tool is None:
            raise ValueError("retract requires a tool")
        index, slot = tool_target(tool)
        device = self.devices[index]
        self.safety.assert_allowed(
            device, SafetyContext("retract", confirmed, source, self._print_state())
        )
        self._assert_manual_motion_path(tool)
        previous_path_state = self.path_state
        with self._transaction_scope("retract", target="T%d" % tool):
            length = float(params["length"])
            speed = float(params.get("speed", self._shared("retract_speed", 80)))
            encoder_token = self._start_ace_motion(
                device,
                "retract",
                length,
                required=previous_path_state == "nozzle",
            )
            try:
                result = device.retract(slot, length, speed)
                self._wait_for_motion(device, result, length, speed)
            except Exception as exc:
                self._cancel_ace_motion(encoder_token)
                self._set_path_unknown(str(exc))
                raise
            self._finish_ace_motion(
                device,
                slot,
                "retract",
                encoder_token,
                command_completed=self._motion_completed(result),
            )
            self._finalize_manual_motion(tool, "retract", previous_path_state)
            return result

    def enable_feed_assist(
        self, params: Mapping[str, Any], *, confirmed: bool, source: str
    ) -> Dict[str, Any]:
        self._assert_encoder_calibration_inactive()
        tool = self._resolve_feed_assist_tool(params, required=True)
        assert tool is not None
        index, slot = tool_target(tool)
        target = self.devices[index]
        context = SafetyContext(
            "enable_feed_assist", confirmed, source, self._print_state()
        )
        self.safety.assert_allowed(target, context)
        self._assert_target_ready(target, tool, slot)
        if self.feed_assist_tool == tool:
            return {"changed": False, "enabled": True, "tool": "T%d" % tool}

        with self._transaction_scope("enable_feed_assist", target="T%d" % tool):
            self._disable_active_feed_assist(source)
            result = target.enable_feed_assist(slot)
            self.feed_assist_tool = tool
        return {
            "changed": True,
            "enabled": True,
            "tool": "T%d" % tool,
            "device_id": target.device_id,
            "slot": slot,
            "result": result,
        }

    def _disable_active_feed_assist(self, source: str) -> None:
        previous = self.feed_assist_tool
        if previous is None:
            return
        old_index, old_slot = tool_target(previous)
        old_device = self.devices[old_index]
        self.safety.assert_allowed(
            old_device,
            SafetyContext(
                "disable_feed_assist", True, source, self._print_state()
            ),
        )
        old_device.disable_feed_assist(old_slot)
        self.feed_assist_tool = None

    def disable_feed_assist(
        self, params: Mapping[str, Any], *, confirmed: bool, source: str
    ) -> Dict[str, Any]:
        tool = self._resolve_feed_assist_tool(params, required=False)
        if tool is None:
            return {"changed": False, "enabled": False, "tool": None}
        index, slot = tool_target(tool)
        device = self.devices[index]
        self.safety.assert_allowed(
            device,
            SafetyContext(
                "disable_feed_assist", confirmed, source, self._print_state()
            ),
        )
        with self._transaction_scope("disable_feed_assist", target="T%d" % tool):
            result = device.disable_feed_assist(slot)
            if self.feed_assist_tool == tool:
                self.feed_assist_tool = None
        return {
            "changed": True,
            "enabled": False,
            "tool": "T%d" % tool,
            "device_id": device.device_id,
            "slot": slot,
            "result": result,
        }

    def start_drying(self, params: Mapping[str, Any], *, confirmed: bool, source: str) -> Any:
        device = self.get_device(params.get("device", "ace0"))
        temperature = int(params["temperature"])
        maximum = int(self._shared("max_dryer_temperature", 55))
        if temperature > maximum:
            raise AceSafetyError(
                "Dryer temperature exceeds the configured maximum",
                details={"requested": temperature, "maximum": maximum},
            )
        self.safety.assert_allowed(
            device, SafetyContext("start_drying", confirmed, source, self._print_state())
        )
        return device.start_drying(temperature, int(params.get("duration", 240)))

    def stop_drying(self, params: Mapping[str, Any], *, confirmed: bool, source: str) -> Any:
        device = self.get_device(params.get("device", "ace0"))
        self.safety.assert_allowed(
            device, SafetyContext("stop_drying", confirmed, source, self._print_state())
        )
        return device.stop_drying()

    def set_slot(self, device: Any, slot: Any, **values: Any) -> Dict[str, Any]:
        result = self.get_device(device).set_slot_inventory(int(slot), values)
        self._persist_inventory()
        return result

    def encoder_status(self) -> Dict[str, Any]:
        return self._encoder_status()

    def start_encoder_calibration(
        self,
        *,
        segment_length: Optional[float] = None,
        segments: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._assert_encoder_calibration_allowed()
        if self.encoder is None:
            raise AceSafetyError("共享耗材编码器未配置。")
        starter = getattr(self.encoder, "start_calibration", None)
        if not callable(starter):
            raise AceSafetyError("当前共享耗材编码器不支持校准。")
        try:
            if segment_length is None and segments is None:
                result = dict(starter())
            else:
                result = dict(
                    starter(
                        segment_length=(
                            150.0 if segment_length is None else segment_length
                        ),
                        segments=3 if segments is None else segments,
                    )
                )
        except Exception as exc:
            raise AceSafetyError(
                "共享耗材编码器校准无法开始。",
                code="encoder_calibration_failed",
                details={"error": str(exc)},
            )
        self._reset_encoder_print_monitor("calibrating")
        return result

    def finish_encoder_calibration(self, measured_length: Any) -> Dict[str, Any]:
        self._assert_encoder_calibration_allowed()
        try:
            length = float(measured_length)
        except (TypeError, ValueError) as exc:
            raise AceSafetyError(
                "编码器校准长度必须在 0.01 到 2000 mm 之间。"
            ) from exc
        if not math.isfinite(length) or not 0.01 <= length <= 2000.0:
            raise AceSafetyError(
                "编码器校准长度必须在 0.01 到 2000 mm 之间。"
            )
        if self.encoder is None:
            raise AceSafetyError("共享耗材编码器未配置。")
        finisher = getattr(self.encoder, "finish_calibration", None)
        if not callable(finisher):
            raise AceSafetyError("当前共享耗材编码器不支持校准。")
        try:
            result = dict(finisher(length))
        except Exception as exc:
            raise AceSafetyError(
                "共享耗材编码器校准无法完成。",
                code="encoder_calibration_failed",
                details={"error": str(exc)},
            )
        if result.get("calibrated"):
            self._state_set("encoder_resolution", result["resolution"])
            self._encoder_runtime_fault = None
            self._clear_encoder_fault()
            self._reset_encoder_print_monitor("calibration_finished")
        return result

    def cancel_encoder_calibration(self) -> Dict[str, Any]:
        self._assert_encoder_calibration_cancel_allowed()
        if self.encoder is None:
            raise AceSafetyError("共享耗材编码器未配置。")
        cancel = getattr(self.encoder, "cancel_calibration", None)
        if not callable(cancel):
            raise AceSafetyError(
                "当前共享耗材编码器不支持取消校准。"
            )
        try:
            result = dict(cancel() or {})
        except Exception as exc:
            raise AceSafetyError(
                "共享耗材编码器校准无法取消。",
                code="encoder_calibration_failed",
                details={"error": str(exc)},
            )
        result.setdefault("cancelled", True)
        result["calibration_active"] = False
        self._reset_encoder_print_monitor("calibration_cancelled")
        return result

    def _restore_encoder_state(self) -> None:
        if self.encoder is None:
            return
        saved = self._state_get("encoder_resolution", None)
        if saved is None:
            return
        try:
            resolution = float(saved)
        except (TypeError, ValueError):
            return
        if resolution <= 0:
            return
        setter = getattr(self.encoder, "set_resolution", None)
        if not callable(setter):
            return
        try:
            setter(resolution)
        except Exception as exc:
            self._encoder_runtime_fault = {
                "code": "encoder_restore_failed",
                "message": "已保存的编码器校准数据无法恢复。",
                "details": {"error": str(exc), "resolution": resolution},
                "mode": str(self._shared("encoder_mode", "off")),
            }

    def update_encoder_print_monitor(
        self, extruder_position: Any, *, print_state: Optional[str] = None
    ) -> Dict[str, Any]:
        current_print_state = str(
            self._print_state() if print_state is None else print_state
        ).strip().lower()
        try:
            position = float(extruder_position)
        except (TypeError, ValueError):
            position = None
        if position is not None and not math.isfinite(position):
            position = None

        event = None
        request_pause = False
        with self._state_lock:
            encoder_status = self._encoder_status()
            raw_counts = encoder_status.get("counts")
            try:
                counts = int(raw_counts) if raw_counts is not None else None
            except (TypeError, ValueError):
                counts = None
            self._update_encoder_print_fault_latch_locked(counts)
            sensors = self._sensor_snapshot()
            inactive_reason = self._encoder_print_inactive_reason_for(
                current_print_state,
                encoder_status,
                position,
                counts,
                sensors,
            )
            if inactive_reason is not None:
                state = {
                    "mode_off": "off",
                    "encoder_unconfigured": "unavailable",
                    "encoder_unavailable": "unavailable",
                    "extruder_position_unavailable": "unavailable",
                    "path_transaction": "suspended",
                    "encoder_calibrating": "calibrating",
                    "path_not_loaded": "inactive",
                }.get(
                    inactive_reason,
                    current_print_state
                    if current_print_state != "printing"
                    else "inactive",
                )
                self._reset_encoder_print_monitor_locked(
                    state, inactive_reason=inactive_reason
                )
                return self._encoder_print_monitor_status_locked()

            if (
                not self._encoder_print_active
                or self._encoder_print_last_position is None
                or self._encoder_print_last_counts is None
            ):
                self._encoder_print_active = True
                self._encoder_print_state = (
                    "fault" if self._encoder_print_fault is not None else "monitoring"
                )
                self._encoder_print_inactive_reason = None
                self._encoder_print_last_position = position
                self._encoder_print_last_counts = counts
                self._encoder_print_retraction = 0.0
                self._encoder_print_extrusion_since_motion = 0.0
                return self._encoder_print_monitor_status_locked()

            previous_position = self._encoder_print_last_position
            previous_counts = self._encoder_print_last_counts
            self._encoder_print_last_position = position
            self._encoder_print_last_counts = counts
            if counts < previous_counts:
                self._encoder_print_retraction = 0.0
                self._encoder_print_extrusion_since_motion = 0.0
                self._encoder_print_state = (
                    "fault" if self._encoder_print_fault is not None else "monitoring"
                )
                return self._encoder_print_monitor_status_locked()

            net_extrusion = self._encoder_print_net_extrusion(
                position - previous_position
            )
            if counts > previous_counts:
                self._encoder_print_extrusion_since_motion = 0.0
                self._encoder_print_fault = None
                self._encoder_print_fault_counts = None
                self._encoder_print_state = "monitoring"
                return self._encoder_print_monitor_status_locked()

            self._encoder_print_extrusion_since_motion += net_extrusion
            if self._encoder_print_fault is not None:
                self._encoder_print_state = "fault"
                return self._encoder_print_monitor_status_locked()
            if (
                self._encoder_print_extrusion_since_motion
                < self._encoder_print_detection_length
            ):
                self._encoder_print_state = "monitoring"
                return self._encoder_print_monitor_status_locked()

            event = self._record_encoder_print_fault_locked(
                current_print_state, sensors
            )
            request_pause = self._encoder_print_mode == "pause"

        logging.warning(
            "%s：%s 可能原因：%s",
            PRODUCT_NAME_ZH,
            event["message"],
            " ".join(event["possible_causes"]),
        )
        if request_pause:
            self._request_encoder_print_pause(event)
        return self._encoder_print_monitor_status()

    def _encoder_print_inactive_reason_for(
        self,
        print_state: str,
        encoder_status: Mapping[str, Any],
        position: Optional[float],
        counts: Optional[int],
        sensors: Mapping[str, Optional[bool]],
    ) -> Optional[str]:
        if self._encoder_print_mode == "off":
            return "mode_off"
        if not encoder_status.get("configured"):
            return "encoder_unconfigured"
        if print_state != "printing":
            return "print_not_active"
        if self.path_busy or self._transaction is not None:
            return "path_transaction"
        if encoder_status.get("calibration_active"):
            return "encoder_calibrating"
        if not self._encoder_print_path_loaded():
            return "path_not_loaded"
        if not encoder_status.get("available") or counts is None:
            return "encoder_unavailable"
        if position is None:
            return "extruder_position_unavailable"
        return None

    def _encoder_print_path_loaded(self) -> bool:
        # Logical ownership is authoritative here. A switch changing to
        # "no filament" may be the fault the encoder monitor needs to record.
        return self.path_state == "nozzle" and self.current_tool is not None

    def _encoder_print_net_extrusion(self, delta: float) -> float:
        if delta < 0:
            self._encoder_print_retraction += -delta
            return 0.0
        if delta <= 0:
            return 0.0
        recovered = min(delta, self._encoder_print_retraction)
        self._encoder_print_retraction -= recovered
        return delta - recovered

    def _update_encoder_print_fault_latch_locked(
        self, counts: Optional[int]
    ) -> None:
        if self._encoder_print_fault is None or counts is None:
            return
        if self._encoder_print_fault_counts is None:
            self._encoder_print_fault_counts = counts
            return
        if counts > self._encoder_print_fault_counts:
            self._encoder_print_fault = None
            self._encoder_print_fault_counts = None
            return
        if counts < self._encoder_print_fault_counts:
            self._encoder_print_fault_counts = counts

    def _record_encoder_print_fault_locked(
        self,
        print_state: str,
        sensors: Mapping[str, Optional[bool]],
    ) -> Dict[str, Any]:
        self._encoder_print_event_sequence += 1
        tool_index = self.current_tool
        device_id = None
        device_index = None
        if tool_index is not None:
            device_index, _slot = tool_target(tool_index)
            if 0 <= device_index < len(self.devices):
                device_id = self.devices[device_index].device_id
        sensor_snapshot = self._status_sensor_snapshot(sensors)
        probable_cause = self._encoder_print_probable_cause(sensors)
        context = {
            "tool": None if tool_index is None else "T%d" % tool_index,
            "device": device_id,
            "path_state": self.path_state,
            "print_state": print_state,
            "sensors": copy.deepcopy(sensor_snapshot),
        }
        event = {
            "sequence": self._encoder_print_event_sequence,
            "state": "fault",
            "code": "encoder_print_no_motion",
            "message": (
                "打印净挤出 %.3f mm 期间，共享耗材编码器没有检测到新的脉冲。"
                % self._encoder_print_extrusion_since_motion
            ),
            "probable_cause": probable_cause,
            "possible_causes": list(ENCODER_PRINT_POSSIBLE_CAUSES),
            "mode": self._encoder_print_mode,
            "timestamp": self.clock(),
            "detection_length": self._encoder_print_detection_length,
            "extrusion_since_motion": self._encoder_print_extrusion_since_motion,
            "headroom": 0.0,
            "tool": None if tool_index is None else "T%d" % tool_index,
            "tool_index": tool_index,
            "device": device_id,
            "device_index": device_index,
            "path_state": self.path_state,
            "print_state": print_state,
            "sensors": sensor_snapshot,
            "context": context,
            "pause_requested": self._encoder_print_mode == "pause",
        }
        self._encoder_print_last_event = copy.deepcopy(event)
        self._encoder_print_fault = copy.deepcopy(event)
        self._encoder_print_fault_counts = self._encoder_print_last_counts
        self._encoder_print_state = "fault"
        return event

    def _encoder_print_probable_cause(
        self, sensors: Mapping[str, Optional[bool]]
    ) -> str:
        if sensors.get("upper") is False:
            return (
                "耗材可能已经用尽，或在挤出机上方发生断料；"
                "请检查上方耗材传感器和料盘到挤出机的路径。"
            )
        if not self._lower_sensor_bypassed() and sensors.get("lower") is False:
            return (
                "耗材可能在挤出机下方断裂或缺失；"
                "请检查下方耗材传感器和打印头内的耗材路径。"
            )
        if sensors.get("upper") is True and (
            self._lower_sensor_bypassed() or sensors.get("lower") is True
        ):
            return (
                "喷嘴路径可能堵塞、挤出机可能打滑，"
                "或编码器滚轮没有随耗材转动。"
            )
        return (
            "耗材可能已经用尽、卡住或打滑，"
            "也可能是共享编码器漏计脉冲。"
        )

    def _request_encoder_print_pause(self, event: Mapping[str, Any]) -> None:
        try:
            self._run_hook(
                "pause_on_error",
                {"from": event.get("tool_index"), "to": event.get("tool_index")},
            )
        except Exception as exc:
            logging.exception(
                "%s：编码器打印监测无法请求暂停打印", PRODUCT_NAME_ZH
            )
            with self._state_lock:
                for target in (
                    self._encoder_print_last_event,
                    self._encoder_print_fault,
                ):
                    if target is not None and target.get("sequence") == event.get(
                        "sequence"
                    ):
                        target["pause_error"] = localize_exception(exc)

    def _reset_encoder_print_monitor(self, state: str = "inactive") -> None:
        with self._state_lock:
            self._reset_encoder_print_monitor_locked(state)

    def _reset_encoder_print_monitor_locked(
        self, state: str, *, inactive_reason: Optional[str] = None
    ) -> None:
        self._encoder_print_active = False
        self._encoder_print_state = str(state)
        self._encoder_print_inactive_reason = inactive_reason
        self._encoder_print_last_position = None
        self._encoder_print_last_counts = None
        self._encoder_print_retraction = 0.0
        self._encoder_print_extrusion_since_motion = 0.0

    def _encoder_print_monitor_status(self) -> Dict[str, Any]:
        with self._state_lock:
            return self._encoder_print_monitor_status_locked()

    def _encoder_print_monitor_status_locked(self) -> Dict[str, Any]:
        extrusion = max(0.0, self._encoder_print_extrusion_since_motion)
        return {
            "mode": self._encoder_print_mode,
            "enabled": self._encoder_print_mode != "off",
            "active": self._encoder_print_active,
            "state": self._encoder_print_state,
            "inactive_reason": self._encoder_print_inactive_reason,
            "detection_length": self._encoder_print_detection_length,
            "extrusion_since_motion": extrusion,
            "headroom": max(
                0.0, self._encoder_print_detection_length - extrusion
            ),
            "event_sequence": self._encoder_print_event_sequence,
            "last_event": copy.deepcopy(self._encoder_print_last_event),
            "fault": copy.deepcopy(self._encoder_print_fault),
        }

    def _encoder_status(self) -> Dict[str, Any]:
        mode = str(self._shared("encoder_mode", "off")).strip().lower()
        sensor_configured = bool(
            self.encoder is not None
            or self._shared("encoder_sensor_pin", None)
            or self._shared("encoder_sensor_name", None)
        )
        status: Dict[str, Any] = {
            "configured": sensor_configured,
            "available": False,
            "enabled": mode != "off",
            "mode": mode,
            "calibrated": False,
            "resolution": None,
            "detection_length": float(
                self._shared("encoder_detection_length", 20)
            ),
            "min_tracking_ratio": float(
                self._shared("encoder_min_tracking_ratio", 0.6)
            ),
            "counts": None,
            "position": None,
            "tracking_ratio": None,
            "armed": False,
            "calibration_active": False,
            "last_event": None,
            "fault": None,
        }
        if self.encoder is not None:
            status["configured"] = True
            getter = getattr(self.encoder, "get_status", None)
            if callable(getter):
                try:
                    current = getter()
                    if isinstance(current, Mapping):
                        status.update(dict(current))
                except Exception as exc:
                    status["fault"] = {
                        "code": "encoder_status_failed",
                        "message": "共享耗材编码器状态暂时不可用。",
                        "details": {"error": str(exc)},
                    }
        # The [ace] configuration is authoritative even when a pre-existing
        # Klipper encoder object reports stale runtime settings.
        status["configured"] = sensor_configured
        status["mode"] = mode
        status["enabled"] = status["mode"] != "off"
        if self._encoder_runtime_fault is not None:
            status["fault"] = copy.deepcopy(self._encoder_runtime_fault)
        elif isinstance(status.get("fault"), Mapping):
            fault = dict(copy.deepcopy(status["fault"]))
            fault["message"] = localize_message(
                fault.get("message"),
                code=str(fault.get("code") or "encoder_motion_fault"),
                details=fault.get("details")
                if isinstance(fault.get("details"), Mapping)
                else None,
            )
            if fault.get("reason"):
                fault["reason"] = localize_message(
                    fault["reason"], code=str(fault.get("code") or "")
                )
            status["fault"] = fault
        status["armed"] = bool(
            status["mode"] == "protect"
            and status.get("configured")
            and status.get("available")
            and status.get("calibrated")
            and not status.get("fault")
        )
        status["healthy"] = bool(
            status.get("configured")
            and status.get("available")
            and not status.get("fault")
        )
        status["print_monitor"] = self._encoder_print_monitor_status()
        return status

    def _assert_encoder_calibration_allowed(self) -> None:
        if self.encoder is None:
            raise AceSafetyError("共享耗材编码器未配置。")
        print_state = str(self._print_state() or "unknown").strip().lower()
        if print_state not in RECOVERY_PRINT_STATES:
            raise AceSafetyError(
                "只能在打印机空闲时校准编码器。",
                details={"print_state": print_state},
            )
        if self.path_busy:
            raise AceBusyError("共享耗材路径正忙。")
        if self.feed_assist_tool is not None:
            raise AceSafetyError(
                "校准编码器前必须关闭辅助送料。",
                details={"feed_assist_tool": "T%d" % self.feed_assist_tool},
            )
        if self.current_tool is not None or self.path_state != "empty":
            raise AceSafetyError(
                "校准编码器前必须卸载当前工具通道，并确认耗材路径为空。",
                details={
                    "path_state": self.path_state,
                    "current_tool": self.current_tool,
                },
            )

    def _assert_encoder_calibration_cancel_allowed(self) -> None:
        print_state = str(self._print_state() or "unknown").strip().lower()
        if print_state not in RECOVERY_PRINT_STATES:
            raise AceSafetyError(
                "只能在打印机空闲时取消编码器校准。",
                details={"print_state": print_state},
            )

    def _clear_encoder_fault(self) -> None:
        if self.encoder is None:
            return
        clearer = getattr(self.encoder, "clear_fault", None)
        if callable(clearer):
            try:
                clearer()
            except Exception:
                pass

    def reconnect(self, device: Optional[Any] = None) -> Dict[str, Any]:
        print_state = str(self._print_state() or "unknown").strip().lower()
        if print_state not in RECOVERY_PRINT_STATES:
            raise AceSafetyError(
                "The printer state blocks ACE recovery",
                details={"print_state": print_state},
            )
        targets = self.devices if device is None else [self.get_device(device)]
        uncertain = [
            item
            for item in targets
            if bool(item.get_status().get("physical_state_unknown", False))
        ]
        with self._transaction_scope("recover"):
            for item in targets:
                item.close()
                item.open()
                status = item.refresh()
                state = str(status.get("state") or "unknown").strip().lower()
                if state not in RECOVERY_DEVICE_STATES:
                    raise AceSafetyError(
                        "ACE recovery requires the device to report ready",
                        details={"device_id": item.device_id, "state": state},
                    )
            encoder_recovery_required = bool(
                self._encoder_runtime_fault
                and str(self._encoder_runtime_fault.get("mode") or "").lower()
                == "protect"
            )
            recovery_required = (
                bool(uncertain)
                or self.path_state == "unknown"
                or encoder_recovery_required
            )
            if recovery_required:
                if self.sensor_state is None:
                    self._set_path_unknown(
                        "Path sensors are required to recover an uncertain physical action"
                    )
                    raise AceSafetyError(
                        "Physical recovery requires configured path sensors",
                        code="path_state_unknown",
                    )
                if self.reconcile_path_state() not in {"empty", "nozzle"}:
                    raise AceSafetyError(
                        "Path sensors could not confirm a recoverable filament state",
                        code="path_state_unknown",
                    )
                for item in uncertain:
                    item.clear_physical_state_unknown()
            if self._encoder_runtime_fault is not None:
                self._encoder_runtime_fault = None
                self._clear_encoder_fault()
        return self.get_status()

    def reconcile_path_state(self) -> str:
        if self.sensor_state is None:
            return self.path_state
        try:
            sensors = self._sensor_snapshot(strict=True, for_control=True)
        except Exception as exc:
            self._set_path_unknown(str(exc))
            return self.path_state
        upper = sensors["upper"]
        lower = sensors["lower"]
        lower_confirmed = self._lower_sensor_bypassed() or lower is True
        if self._all_path_sensors_clear(sensors):
            self.current_tool = None
            self._state_set("current_tool", None)
            self._set_path_state("empty")
        elif (
            upper is True
            and lower_confirmed
            and self.current_tool is not None
            and self._loaded_route_matches(sensors, self.current_tool)
        ):
            self._set_path_state("nozzle")
        else:
            self._set_path_unknown("sensor state does not identify a complete V3 path")
        return self.path_state

    def set_endless_spool(
        self, enabled: Any, match_mode: Optional[str] = None, **_unused: Any
    ) -> Dict[str, Any]:
        requested = str(enabled).lower() in {"1", "true", "yes", "on"}
        if requested:
            self._assert_toolchange_ready()
        self.endless_spool_enabled = requested
        if match_mode is not None:
            normalized = str(match_mode).lower()
            if normalized not in {"exact", "material"}:
                raise ValueError("Endless spool match_mode must be exact or material")
            self.endless_spool_match_mode = normalized
        self._state_set("endless_spool_enabled", self.endless_spool_enabled)
        self._state_set("endless_spool_match_mode", self.endless_spool_match_mode)
        return {
            "enabled": self.endless_spool_enabled,
            "match_mode": self.endless_spool_match_mode,
        }

    def handle_runout(self) -> Dict[str, Any]:
        self._assert_toolchange_ready()
        if not self.endless_spool_enabled:
            raise AceSafetyError("Endless spool is disabled")
        if self.current_tool is None:
            raise AceSafetyError("No current tool is available for endless spool")
        old_tool = self.current_tool
        decision = self._select_endless_candidate()
        if decision.candidate is None:
            self._validate_hooks(("pause_on_error",))
            self._run_hook("pause_on_error", {"from": old_tool, "to": None})
            print_state = str(self._print_state() or "unknown").strip().lower()
            if print_state not in {"paused", "error", "cancelled"}:
                raise AceSafetyError(
                    "No endless-spool candidate was found and the printer did not pause",
                    details={"print_state": print_state, "tool": "T%d" % old_tool},
                )
            return {"changed": False, "decision": decision.to_dict()}
        result = self.change_tool(
            decision.candidate.tool_name, confirmed=True, source="runout"
        )
        old_device_index, old_slot = tool_target(old_tool)
        self.devices[old_device_index].set_slot_inventory(old_slot, {"status": "empty"})
        self._persist_inventory()
        return {"changed": True, "decision": decision.to_dict(), "toolchange": result}

    def _load_tool(self, tool: int, context: SafetyContext) -> None:
        index, slot = tool_target(tool)
        device = self.devices[index]
        self.safety.assert_allowed(device, context)
        self._assert_target_ready(device, tool, slot)
        self._disable_active_feed_assist(context.source)
        closed_loop = self.sensor_state is not None
        if closed_loop:
            occupied = {
                name: state
                for name, state in self._sensor_snapshot(
                    strict=True, for_control=True
                ).items()
                if state is True
            }
            if occupied:
                raise AceSafetyError(
                    "The shared filament path is not empty before loading",
                    details={"tool": "T%d" % tool, "sensors": occupied},
                )
            self._set_path_state("changing")
            try:
                self._feed_to_upper_sensor(device, slot, tool)
                self._assert_device_route_sensors(device, True)
            except Exception as exc:
                self._set_path_unknown(str(exc))
                raise
        else:
            self._set_path_state("changing")
            load_length = float(self._shared("toolchange_load_length", 630))
            load_speed = float(self._shared("feed_speed", 80))
            encoder_token = self._start_ace_motion(
                device, "load", load_length, required=True
            )
            try:
                result = device.feed(slot, load_length, load_speed)
                self._wait_for_motion(
                    device, result, load_length, load_speed
                )
            except Exception as exc:
                self._cancel_ace_motion(encoder_token)
                self._stop_ace_motion(device, slot, "feed")
                self._set_path_unknown(str(exc))
                raise
            self._finish_ace_motion(
                device,
                slot,
                "feed",
                encoder_token,
                command_completed=self._motion_completed(result),
            )
        device.enable_feed_assist(slot)
        self.feed_assist_tool = tool
        try:
            self._run_hook(
                "load_to_toolhead", {"tool": tool, "device": index, "slot": slot}
            )
            if closed_loop:
                if not self._sensor_stable("upper", True):
                    raise AceSafetyError("Upper filament sensor cleared during toolhead loading")
                if (
                    not self._lower_sensor_bypassed()
                    and not self._sensor_stable("lower", True)
                ):
                    raise AceSafetyError("Lower filament sensor did not confirm toolhead loading")
        except Exception:
            try:
                device.disable_feed_assist(slot)
            except Exception:
                pass
            if self.feed_assist_tool == tool:
                self.feed_assist_tool = None
            self._set_path_unknown("toolhead loading failed")
            raise
        self._set_path_state("nozzle")

    def _unload_tool(self, tool: int, context: SafetyContext) -> None:
        index, slot = tool_target(tool)
        device = self.devices[index]
        self.safety.assert_allowed(device, context)
        device.disable_feed_assist(slot)
        if self.feed_assist_tool == tool:
            self.feed_assist_tool = None
        hook_params = {"tool": tool, "device": index, "slot": slot}
        if self.sensor_state is None:
            self._set_path_state("changing")
            retract_length = float(
                self._shared("toolchange_retract_length", 150)
            )
            retract_speed = float(self._shared("retract_speed", 80))
            encoder_token = self._start_ace_motion(
                device, "unload", retract_length, required=True
            )
            try:
                self._run_hook("cut", hook_params)
                self._run_hook("unload_from_toolhead", hook_params)
                result = device.retract(slot, retract_length, retract_speed)
                self._wait_for_motion(
                    device, result, retract_length, retract_speed
                )
            except Exception as exc:
                self._cancel_ace_motion(encoder_token)
                self._stop_ace_motion(device, slot, "retract")
                self._set_path_unknown(str(exc))
                raise
            self._finish_ace_motion(
                device,
                slot,
                "retract",
                encoder_token,
                command_completed=self._motion_completed(result),
            )
            self._set_path_state("empty")
            return

        upper = self._sensor_stable("upper", True)
        lower_bypassed = self._lower_sensor_bypassed()
        lower = None if lower_bypassed else self._sensor_stable("lower", True)
        if lower_bypassed:
            if not upper:
                raise AceSafetyError(
                    "Saved tool state has no matching upper filament sensor signal",
                    details={"tool": "T%d" % tool},
                )
        else:
            if lower and not upper:
                raise AceSafetyError(
                    "Lower filament sensor is active while the upper sensor is clear"
                )
            if not upper and not lower:
                raise AceSafetyError(
                    "Saved tool state has no matching filament sensor signal",
                    details={"tool": "T%d" % tool},
                )
        self._assert_device_route_sensors(device, True)

        self._set_path_state("changing")
        try:
            if lower_bypassed or lower:
                self._run_hook("cut", hook_params)

            max_attempts = int(self._shared("toolhead_unload_max_attempts", 10))
            ace_step = float(self._shared("ace_unload_step_length", 100))
            ace_speed = float(self._shared("retract_fast_speed", 120))
            attempts = 0
            while self._sensor_stable("upper", True):
                if attempts >= max_attempts:
                    raise AceSafetyError(
                        "Upper filament sensor did not clear during coordinated unloading",
                        details={"attempts": attempts},
                    )
                if lower_bypassed or self._sensor("lower") is True:
                    self._run_hook("unload_from_toolhead", hook_params)
                encoder_token = self._start_ace_motion(
                    device, "unload", ace_step, required=True
                )
                try:
                    result = device.retract(slot, ace_step, ace_speed)
                    self._wait_for_motion(device, result, ace_step, ace_speed)
                except Exception:
                    self._cancel_ace_motion(encoder_token)
                    raise
                self._finish_ace_motion(
                    device,
                    slot,
                    "retract",
                    encoder_token,
                    command_completed=self._motion_completed(result),
                )
                attempts += 1

            self._retract_to_parking_position(device, slot)
            sensors = self._sensor_snapshot(strict=True, for_control=True)
            if not self._all_path_sensors_clear(sensors):
                raise AceSafetyError(
                    "Filament sensors did not confirm an empty shared path",
                    details={
                        "sensors": self._status_sensor_snapshot(sensors),
                        "device_id": device.device_id,
                    },
                )
        except Exception as exc:
            self._set_path_unknown(str(exc))
            raise
        self._set_path_state("empty")

    @contextlib.contextmanager
    def _transaction_scope(self, action: str, *, target: Optional[str] = None):
        if not self._path_lock.acquire(False):
            raise AceBusyError("The shared filament path is busy", retryable=True)
        self._reset_encoder_print_monitor("transaction")
        transaction = {
            "id": uuid.uuid4().hex,
            "action": action,
            "target": target,
            "state": "running",
            "started_at": self.clock(),
        }
        with self._state_lock:
            self._transaction = transaction
        try:
            yield transaction
        except Exception as exc:
            transaction.update(state="failed", finished_at=self.clock(), error=str(exc))
            raise
        else:
            transaction.update(state="completed", finished_at=self.clock())
        finally:
            with self._state_lock:
                self._last_transaction = copy.deepcopy(transaction)
                self._transaction = None
            self._path_lock.release()

    def _run_hook(self, name: str, params: Mapping[str, Any]) -> None:
        if self.machine_hook is not None:
            self.machine_hook(name, params)

    def _validate_hooks(self, names: Iterable[str]) -> None:
        if self.machine_hook_validator is not None:
            self.machine_hook_validator(tuple(names))

    def _preflight_toolhead_moves(self, *, loading: bool, unloading: bool) -> None:
        if self.extruder_preflight is None:
            return
        distances = []
        if unloading:
            distances.append(-float(self._shared("toolhead_unload_step_length", 50)))
        if loading and self._lower_sensor_bypassed():
            bypass_length = self._lower_sensor_bypass_load_length()
            if bypass_length > 0:
                distances.append(
                    min(
                        bypass_length,
                        float(self._shared("toolhead_feed_fast_step", 5)),
                    )
                )
        elif loading:
            maximum = float(self._shared("toolhead_sensor_max_feed_length", 200))
            fast_length = min(
                maximum, float(self._shared("toolhead_feed_fast_length", 10))
            )
            if fast_length > 0:
                distances.append(
                    min(
                        fast_length,
                        float(self._shared("toolhead_feed_fast_step", 5)),
                    )
                )
            slow_length = maximum - fast_length
            if slow_length > 0:
                distances.append(
                    min(
                        slow_length,
                        float(self._shared("toolhead_feed_slow_step", 1)),
                    )
                )
            nozzle_length = float(self._shared("toolhead_sensor_to_nozzle", 50))
            if nozzle_length > 0:
                distances.append(nozzle_length)
        self.extruder_preflight(tuple(distances))

    def _assert_toolchange_ready(self) -> None:
        readiness = self.get_toolchange_readiness()
        if readiness["ready"]:
            return
        raise AceSafetyError(
            "ACE 自动换料尚未就绪。",
            code="toolchange_not_ready",
            details={
                "toolchange_mode": readiness["mode"],
                "blocked_reason": readiness["blocked_reason"],
                "blocked_detail": readiness["blocked_detail"],
            },
        )

    @staticmethod
    def _tool_command_name(value: Any) -> str:
        text = str(value).strip().upper()
        if text in {"TR", "-1"}:
            return "TR"
        if text.startswith("T"):
            return text
        return "T%s" % text

    def _record_toolchange_notice(
        self, command: str, readiness: Mapping[str, Any]
    ) -> Dict[str, Any]:
        with self._state_lock:
            self._toolchange_notice_sequence += 1
            notice = {
                "sequence": self._toolchange_notice_sequence,
                "code": TOOLCHANGE_NOTICE_CODE,
                "command": command,
                "message": (
                    "ACE 自动换料未配置，已忽略 %s。"
                    "当前无法进行多色打印，仅可使用已启用的 ACE 辅助送料。"
                    % command
                ),
                "blocked_reason": readiness.get("blocked_reason"),
                "blocked_detail": readiness.get("blocked_detail"),
                "timestamp": self.clock(),
            }
            self._toolchange_notices.append(notice)
            del self._toolchange_notices[:-TOOLCHANGE_NOTICE_LIMIT]
            return copy.deepcopy(notice)

    def _resolve_feed_assist_tool(
        self, params: Mapping[str, Any], *, required: bool
    ) -> Optional[int]:
        value = params.get("tool")
        if value is not None and str(value).strip() != "":
            tool = parse_tool(value, len(self.devices))
            if tool is None:
                raise ValueError("feed assist requires T0..T%d" % (len(self.devices) * 4 - 1))
            return tool
        device_value = params.get("device_id", params.get("device"))
        slot_value = params.get("slot")
        if device_value is not None or slot_value is not None:
            if device_value is None or slot_value is None:
                raise ValueError("feed assist requires both device and slot")
            device = self.get_device(device_value)
            slot = int(slot_value)
            if not 0 <= slot < SLOT_COUNT:
                raise ValueError("feed assist slot must be in range 0..3")
            return self.devices.index(device) * SLOT_COUNT + slot
        if not required:
            return self.feed_assist_tool
        raise ValueError("feed assist requires TOOL or DEVICE and SLOT")

    def _feed_assist_status(self) -> Dict[str, Any]:
        if self.feed_assist_tool is None:
            return {
                "enabled": False,
                "tool": None,
                "device_id": None,
                "slot": None,
            }
        index, slot = tool_target(self.feed_assist_tool)
        return {
            "enabled": True,
            "tool": "T%d" % self.feed_assist_tool,
            "device_id": self.devices[index].device_id,
            "slot": slot,
        }

    @staticmethod
    def _motion_completed(result: Any) -> bool:
        return isinstance(result, Mapping) and result.get("completed") is True

    def _start_ace_motion(
        self,
        device: AceDevice,
        action: str,
        length: float,
        *,
        required: bool,
    ) -> Optional[Any]:
        if not required or self.encoder is None:
            return None
        status = self._encoder_status()
        mode = status["mode"]
        if mode == "off":
            return None
        if mode == "protect" and not status["armed"]:
            raise AceSafetyError(
                "共享耗材编码器保护尚未就绪。",
                code="encoder_not_ready",
                details={"encoder": status},
            )
        starter = getattr(self.encoder, "begin_motion", None)
        if not callable(starter):
            if mode == "protect":
                raise AceSafetyError(
                    "共享耗材编码器无法监测 ACE 动作。",
                    code="encoder_not_ready",
                )
            return None
        try:
            return starter(action, device.device_id, abs(float(length)))
        except Exception as exc:
            fault = {
                "code": "encoder_start_failed",
                "message": "共享耗材编码器无法开始动作监测。",
                "details": {"error": str(exc), "device_id": device.device_id},
                "mode": mode,
            }
            self._encoder_runtime_fault = fault
            if mode == "protect":
                raise AceSafetyError(
                    fault["message"],
                    code="encoder_motion_fault",
                    details=fault,
                )
            return None

    def _cancel_ace_motion(self, token: Optional[Any]) -> None:
        if token is None or self.encoder is None:
            return
        cancel = getattr(self.encoder, "cancel_motion", None)
        if callable(cancel):
            try:
                cancel(token)
            except Exception:
                pass

    def _finish_ace_motion(
        self,
        device: AceDevice,
        slot: int,
        action: str,
        token: Optional[Any],
        *,
        command_completed: bool,
    ) -> Optional[Dict[str, Any]]:
        if token is None or self.encoder is None:
            return None
        finisher = getattr(self.encoder, "finish_motion", None)
        settle_time = getattr(self.encoder, "get_settle_time", None)
        if callable(settle_time):
            try:
                self.sleep(max(0.0, min(0.5, float(settle_time()))))
            except Exception:
                pass
        if not callable(finisher):
            event = {
                "mode": self._encoder_status()["mode"],
                "fault": {
                    "code": "encoder_finish_failed",
                    "message": "共享耗材编码器无法完成动作监测。",
                },
            }
        else:
            try:
                raw_event = finisher(token, command_completed=command_completed)
                event = dict(raw_event or {})
            except Exception as exc:
                event = {
                    "mode": self._encoder_status()["mode"],
                    "fault": {
                        "code": "encoder_finish_failed",
                        "message": "共享耗材编码器动作监测未能完成。",
                        "details": {"error": str(exc)},
                    },
                }
        mode = str(event.get("mode") or self._encoder_status()["mode"])
        fault = event.get("fault")
        if not fault:
            if (
                self._encoder_runtime_fault is not None
                and self._encoder_runtime_fault.get("mode") != "protect"
            ):
                self._encoder_runtime_fault = None
            return event

        fault_data = dict(fault) if isinstance(fault, Mapping) else {
            "code": "encoder_motion_fault",
            "message": str(fault),
        }
        fault_data["message"] = localize_message(
            fault_data.get("message") or "共享耗材编码器未确认 ACE 耗材移动。",
            code=str(fault_data.get("code") or "encoder_motion_fault"),
            details=fault_data.get("details")
            if isinstance(fault_data.get("details"), Mapping)
            else None,
        )
        event["fault"] = copy.deepcopy(fault_data)
        runtime_fault = {
            "code": str(fault_data.get("code") or "encoder_motion_fault"),
            "message": str(
                fault_data.get("message")
                or "共享耗材编码器未确认 ACE 耗材移动。"
            ),
            "details": {
                "device_id": device.device_id,
                "slot": int(slot),
                "action": action,
                "event": event,
            },
            "mode": mode,
        }
        self._encoder_runtime_fault = runtime_fault
        if mode != "protect":
            return event

        self._stop_ace_motion(device, slot, action)
        self._set_path_unknown(runtime_fault["message"])
        raise AceSafetyError(
            runtime_fault["message"],
            code="encoder_motion_fault",
            details=runtime_fault["details"],
        )

    @staticmethod
    def _stop_ace_motion(device: AceDevice, slot: int, action: str) -> None:
        stop_name = "stop_feed" if action == "feed" else "stop_retract"
        stop = getattr(device, stop_name, None)
        if callable(stop):
            try:
                stop(slot)
            except Exception:
                pass

    def _wait_for_motion(
        self,
        device: AceDevice,
        result: Any,
        length: float,
        speed: float,
    ) -> None:
        if isinstance(result, Mapping) and result.get("completed") is True:
            return
        expected = max(0.0, float(length) / float(speed))
        if expected:
            self.sleep(expected + 0.1)
        device.wait_ready(
            max(5.0, min(120.0, expected * 0.5 + 5.0)),
            sleep=self.sleep,
        )

    def _feed_to_upper_sensor(self, device: AceDevice, slot: int, tool: int) -> None:
        started_at = self.clock()
        timeout = float(self._shared("upper_sensor_feed_timeout", 30))
        deadline = started_at + timeout
        fast_speed = float(
            self._shared("feed_fast_speed", self._shared("feed_speed", 80))
        )
        continuation_speed = float(
            self._shared("feed_slip_compensation_speed", 25)
        )
        segments = [
            [
                max(0.0, float(self._shared("toolchange_load_length", 630))),
                fast_speed,
            ],
            [
                max(
                    0.0,
                    float(self._shared("feed_slip_compensation_length", 400)),
                ),
                continuation_speed,
            ],
        ]
        reference_feed_limit = sum(length for length, _speed in segments)
        attempts = 0
        reference_feed_amount = 0.0
        encoder_events = []
        segment_index = 0
        while self.clock() < deadline:
            if self._sensor_stable("upper", True):
                if self.clock() < deadline:
                    return
                break

            remaining_time = max(0.0, deadline - self.clock())
            window_time = min(ACE_FEED_MONITOR_WINDOW_SECONDS, remaining_time)
            while (
                segment_index < len(segments)
                and segments[segment_index][0] <= 0
            ):
                segment_index += 1
            if segment_index < len(segments):
                remaining_length, speed = segments[segment_index]
                length = min(remaining_length, speed * window_time)
                segments[segment_index][0] = max(0.0, remaining_length - length)
            else:
                speed = continuation_speed
                length = speed * window_time
            if length <= 0 or speed <= 0:
                break

            attempts += 1
            reference_feed_amount += length
            encoder_token = self._start_ace_motion(
                device, "load", length, required=True
            )
            attempt_started_at = self.clock()
            try:
                result = device.feed(slot, length, speed)
                reached = self._wait_for_sensor_motion(
                    device,
                    result,
                    length,
                    speed,
                    "upper",
                    True,
                    lambda: device.stop_feed(slot),
                    hard_deadline=deadline,
                )
            except Exception:
                self._cancel_ace_motion(encoder_token)
                self._stop_ace_motion(device, slot, "feed")
                raise
            encoder_event = self._finish_ace_motion(
                device,
                slot,
                "feed",
                encoder_token,
                command_completed=self._motion_completed(result),
            )
            if encoder_event is not None:
                encoder_events.append(
                    {
                        "pulses": encoder_event.get("pulses"),
                        "measured_length": encoder_event.get("measured_length"),
                        "validation": encoder_event.get("validation", "movement"),
                        "fault": encoder_event.get("fault"),
                    }
                )
            if reached:
                return
            if self.clock() <= attempt_started_at and self.clock() < deadline:
                self.sleep(
                    min(ACE_FEED_NO_PROGRESS_SLEEP, deadline - self.clock())
                )

        self._stop_ace_motion(device, slot, "feed")
        elapsed = max(0.0, self.clock() - started_at)
        raise AceSafetyError(
            "Upper filament sensor did not trigger before the ACE feed timeout",
            code="upper_sensor_feed_timeout",
            details={
                "tool": "T%d" % tool,
                "device_id": device.device_id,
                "elapsed_seconds": elapsed,
                "timeout_seconds": timeout,
                "attempts": attempts,
                "reference_feed_amount": reference_feed_amount,
                "reference_feed_limit": reference_feed_limit,
                "continuation_feed_amount": max(
                    0.0, reference_feed_amount - reference_feed_limit
                ),
                "upper_sensor": self._sensor_snapshot().get("upper"),
                "encoder_events": encoder_events,
            },
        )

    def _retract_to_parking_position(self, device: AceDevice, slot: int) -> None:
        if len(self.devices) == 1:
            self._retract_legacy_parking_position(device, slot)
            return

        shared_segments = self._parking_retract_segments(
            float(self._shared("toolchange_retract_length", 150))
        )
        branch_length = self._hub_retract_length(device.device_id)
        clear_length = self._hub_clear_move_length(device.device_id)
        parking_speed = float(self._shared("retract_parking_speed", 25))
        hub_sensor = self._hub_sensor_key(device.device_id)
        common_state = self._sensor("rdm")
        hub_state = self._sensor(hub_sensor)

        if common_state is not None:
            self._retract_until_sensor_clear(
                device,
                slot,
                "rdm",
                shared_segments,
                "Total-hub sensor did not clear within the shared retract limit",
                monitor_encoder=True,
            )
            if hub_state is not None:
                self._retract_until_sensor_clear(
                    device,
                    slot,
                    hub_sensor,
                    ((branch_length, parking_speed),),
                    "%s first-stage hub sensor did not clear within its retract limit"
                    % device.device_id,
                )
            else:
                self._run_retract_segment(
                    device, slot, branch_length, parking_speed
                )
        elif hub_state is not None:
            self._retract_until_sensor_clear(
                device,
                slot,
                hub_sensor,
                shared_segments + ((branch_length, parking_speed),),
                "%s first-stage hub sensor did not clear within the combined retract limit"
                % device.device_id,
                monitor_encoder=True,
            )
        else:
            self._run_retract_segments(
                device,
                slot,
                shared_segments + ((branch_length, parking_speed),),
                monitor_encoder=True,
            )

        self._run_retract_segment(device, slot, clear_length, parking_speed)

    def _retract_legacy_parking_position(
        self, device: AceDevice, slot: int
    ) -> None:
        total = float(self._shared("toolchange_retract_length", 150))
        segments = self._parking_retract_segments(total)
        rdm_state = self._sensor("rdm")
        if rdm_state is None:
            for length, speed in segments:
                self._run_retract_segment(device, slot, length, speed)
            return

        cleared = rdm_state is False
        encoder_token = self._start_ace_motion(
            device,
            "unload",
            sum(length for length, _speed in segments),
            required=not cleared,
        )
        last_result = None
        for length, speed in segments:
            if cleared or length <= 0:
                continue
            try:
                last_result = device.retract(slot, length, speed)
                cleared = self._wait_for_sensor_motion(
                    device,
                    last_result,
                    length,
                    speed,
                    "rdm",
                    False,
                    lambda: device.stop_retract(slot),
                )
            except Exception:
                self._cancel_ace_motion(encoder_token)
                raise
        if not cleared:
            self._cancel_ace_motion(encoder_token)
            raise AceSafetyError(
                "Return-path sensor did not clear within the configured retract limit"
            )
        self._finish_ace_motion(
            device,
            slot,
            "retract",
            encoder_token,
            command_completed=self._motion_completed(last_result),
        )
        self._run_retract_segment(
            device,
            slot,
            float(self._shared("rdm_clear_move_length", 100)),
            float(self._shared("retract_parking_speed", 25)),
        )

    def _parking_retract_segments(self, total: float) -> Tuple[Tuple[float, float], ...]:
        parking_length = min(
            total, float(self._shared("retract_parking_length", min(200, total)))
        )
        return (
            (
                max(0.0, total - parking_length),
                float(self._shared("retract_fast_speed", 120)),
            ),
            (parking_length, float(self._shared("retract_parking_speed", 25))),
        )

    def _retract_until_sensor_clear(
        self,
        device: AceDevice,
        slot: int,
        sensor: str,
        segments: Iterable[Tuple[float, float]],
        error_message: str,
        *,
        monitor_encoder: bool = False,
    ) -> None:
        if self._sensor(sensor) is False:
            return
        segment_list = tuple(segments)
        encoder_token = self._start_ace_motion(
            device,
            "unload",
            sum(length for length, _speed in segment_list),
            required=monitor_encoder,
        )
        cleared = False
        last_result = None
        for length, speed in segment_list:
            if length <= 0:
                continue
            try:
                last_result = device.retract(slot, length, speed)
                cleared = self._wait_for_sensor_motion(
                    device,
                    last_result,
                    length,
                    speed,
                    sensor,
                    False,
                    lambda: device.stop_retract(slot),
                )
            except Exception:
                self._cancel_ace_motion(encoder_token)
                raise
            if cleared:
                break
        if not cleared:
            self._cancel_ace_motion(encoder_token)
            raise AceSafetyError(error_message)
        self._finish_ace_motion(
            device,
            slot,
            "retract",
            encoder_token,
            command_completed=self._motion_completed(last_result),
        )

    def _run_retract_segment(
        self, device: AceDevice, slot: int, length: float, speed: float
    ) -> None:
        if length <= 0:
            return
        result = device.retract(slot, length, speed)
        self._wait_for_motion(device, result, length, speed)

    def _run_retract_segments(
        self,
        device: AceDevice,
        slot: int,
        segments: Iterable[Tuple[float, float]],
        *,
        monitor_encoder: bool = False,
    ) -> None:
        segment_list = tuple(
            (float(length), float(speed))
            for length, speed in segments
            if float(length) > 0
        )
        if not segment_list:
            return
        encoder_token = self._start_ace_motion(
            device,
            "unload",
            sum(length for length, _speed in segment_list),
            required=monitor_encoder,
        )
        last_result = None
        try:
            for length, speed in segment_list:
                last_result = device.retract(slot, length, speed)
                self._wait_for_motion(device, last_result, length, speed)
        except Exception:
            self._cancel_ace_motion(encoder_token)
            raise
        self._finish_ace_motion(
            device,
            slot,
            "retract",
            encoder_token,
            command_completed=self._motion_completed(last_result),
        )

    def _wait_for_sensor_motion(
        self,
        device: AceDevice,
        result: Any,
        length: float,
        speed: float,
        sensor: str,
        expected_state: bool,
        stop_motion: Callable[[], Any],
        *,
        hard_deadline: Optional[float] = None,
    ) -> bool:
        completed = isinstance(result, Mapping) and result.get("completed") is True
        duration = max(0.0, float(length) / float(speed))
        grace_time = float(self._shared("sensor_trigger_grace_time", 3))
        deadline = self.clock() + (grace_time if completed else duration + grace_time)
        if hard_deadline is not None:
            deadline = min(deadline, float(hard_deadline))

        def sensor_reached_before_deadline() -> bool:
            if hard_deadline is not None and self.clock() >= float(hard_deadline):
                return False
            reached = self._sensor_stable(sensor, expected_state)
            return bool(
                reached
                and (
                    hard_deadline is None
                    or self.clock() < float(hard_deadline)
                )
            )

        if sensor_reached_before_deadline():
            if not completed:
                stop_motion()
                device.wait_ready(15.0, sleep=self.sleep)
            return True

        while self.clock() < deadline:
            self.sleep(min(0.025, max(0.0, deadline - self.clock())))
            if sensor_reached_before_deadline():
                if not completed:
                    stop_motion()
                    device.wait_ready(
                        max(5.0, min(120.0, duration + 5.0)), sleep=self.sleep
                    )
                return True
        if not completed:
            stop_motion()
            wait_timeout = max(5.0, min(120.0, duration + 5.0))
            if hard_deadline is not None and self.clock() >= float(hard_deadline):
                wait_timeout = 15.0
            device.wait_ready(wait_timeout, sleep=self.sleep)
        return False

    def _assert_target_ready(self, device: AceDevice, tool: int, slot: int) -> None:
        status = device.get_status()["slots"][slot].get("status")
        if str(status).strip().lower() not in {"ready", "available"}:
            raise AceSafetyError(
                "Target slot is not ready",
                details={"tool": "T%d" % tool, "slot_status": status},
            )

    def _assert_path_available(self) -> None:
        self._assert_encoder_calibration_inactive()
        if self.path_state not in {"empty", "nozzle"}:
            raise AceSafetyError(
                "The shared filament path requires manual recovery",
                code="path_state_unknown",
                details={"path_state": self.path_state},
            )

    def _assert_encoder_calibration_inactive(self) -> None:
        if self._encoder_status().get("calibration_active"):
            raise AceSafetyError(
                "共享耗材编码器校准期间禁止执行 ACE 动作。",
                code="encoder_calibration_active",
            )

    def _assert_manual_motion_path(self, tool: int) -> None:
        self._assert_path_available()
        if self.path_state == "nozzle" and self.current_tool is None:
            self._set_path_unknown("nozzle path has no owning tool")
            raise AceSafetyError(
                "The loaded filament path has no known owning tool",
                code="path_state_unknown",
            )
        if self.path_state == "empty" and self.current_tool is not None:
            self._set_path_unknown("empty path still has a persisted current tool")
            raise AceSafetyError(
                "The filament path and current tool state are inconsistent",
                code="path_state_unknown",
            )
        if self.current_tool is not None and self.current_tool != tool:
            raise AceSafetyError(
                "Another tool owns the shared filament path",
                details={"requested_tool": "T%d" % tool, "current_tool": "T%d" % self.current_tool},
            )

    def _finalize_manual_motion(
        self, tool: int, action: str, previous_path_state: str
    ) -> None:
        if self.sensor_state is None:
            if action == "feed" and previous_path_state == "empty":
                self._set_path_unknown(
                    "Manual feed entered an unobserved shared filament path"
                )
            elif action == "retract" and previous_path_state == "nozzle":
                self.current_tool = None
                self._state_set("current_tool", None)
                self._set_path_unknown(
                    "Manual retract changed a loaded path without sensor confirmation"
                )
            return

        try:
            sensors = self._sensor_snapshot(strict=True, for_control=True)
        except Exception as exc:
            self.current_tool = None
            self._state_set("current_tool", None)
            self._set_path_unknown(str(exc))
            return
        upper, lower = sensors["upper"], sensors["lower"]
        lower_confirmed = lower is True or (
            self._lower_sensor_bypassed()
            and previous_path_state == "nozzle"
            and self.current_tool == tool
        )
        if (
            upper is True
            and lower_confirmed
            and self._loaded_route_matches(sensors, tool)
        ):
            self.current_tool = tool
            self._state_set("current_tool", tool)
            self._set_path_state("nozzle")
            return
        if action == "retract" and self._all_path_sensors_clear(sensors):
            self.current_tool = None
            self._state_set("current_tool", None)
            self._set_path_state("empty")
            return
        self.current_tool = None
        self._state_set("current_tool", None)
        self._set_path_unknown(
            "Manual %s left a partially identified filament path" % action
        )

    def _set_path_state(self, state: str) -> None:
        if str(state) != self.path_state:
            self._reset_encoder_print_monitor("path_changed")
        self.path_state = str(state)
        self._state_set("path_state", self.path_state)
        if state != "unknown":
            self._state_set("path_error", None)

    def _set_path_unknown(self, reason: str) -> None:
        self._reset_encoder_print_monitor("path_unknown")
        self.path_state = "unknown"
        self._state_set("path_state", self.path_state)
        self._state_set("path_error", str(reason))

    def _sensor(self, name: str) -> Optional[bool]:
        if self.sensor_state is None:
            return None
        value = self.sensor_state(name)
        return None if value is None else bool(value)

    def _sensor_snapshot(
        self, *, strict: bool = False, for_control: bool = False
    ) -> Dict[str, Optional[bool]]:
        snapshot: Dict[str, Optional[bool]] = {}
        names = ["upper", "lower", "rdm"]
        if len(self.devices) > 1:
            names.extend(
                self._hub_sensor_key(device.device_id) for device in self.devices
            )
        for name in names:
            if for_control and name == "lower" and self._lower_sensor_bypassed():
                snapshot[name] = None
                continue
            try:
                snapshot[name] = self._sensor(name)
            except Exception:
                if strict:
                    raise
                snapshot[name] = None
        return snapshot

    def _lower_sensor_bypassed(self) -> bool:
        return bool(self._shared("toolhead_sensor_bypass", True))

    def _lower_sensor_bypass_load_length(self) -> float:
        return float(self._shared("toolhead_sensor_bypass_load_length", 25))

    def _lower_sensor_bypass_calibrated(self) -> bool:
        return bool(self._shared("toolhead_sensor_bypass_calibrated", False))

    def _sensor_policy_status(self) -> Dict[str, Any]:
        return {
            "upper": {
                "control_endpoint": True,
                "feed_timeout": float(
                    self._shared("upper_sensor_feed_timeout", 30)
                ),
            },
            "lower": {
                "bypassed": self._lower_sensor_bypassed(),
                "control_enabled": not self._lower_sensor_bypassed(),
                "monitor_only": self._lower_sensor_bypassed(),
                "calibrated": self._lower_sensor_bypass_calibrated(),
                "configured": bool(
                    self._shared("toolhead_sensor_name", None)
                    or self._shared("toolhead_sensor_pin", None)
                ),
                "bypass_load_length": self._lower_sensor_bypass_load_length(),
            }
        }

    def _sensor_stable(self, name: str, expected: bool) -> bool:
        counts = {
            "upper": int(self._shared("extruder_sensor_debounce_count", 2)),
            "lower": int(self._shared("toolhead_sensor_debounce_count", 2)),
            "rdm": int(self._shared("rdm_sensor_debounce_count", 3)),
        }
        count = counts.get(
            name, int(self._shared("ace_hub_sensor_debounce_count", 3))
        )
        for sample in range(max(1, count)):
            value = self._sensor(name)
            if value is None:
                raise AceSafetyError("Required filament sensor '%s' is not configured" % name)
            if value is not bool(expected):
                return False
            if sample + 1 < count:
                self.sleep(0.01)
        return True

    @staticmethod
    def _hub_sensor_key(device_id: str) -> str:
        return "%s_hub" % device_id

    def _hub_retract_length(self, device_id: str) -> float:
        return float(self._shared("%s_hub_retract_length" % device_id, 0))

    def _hub_clear_move_length(self, device_id: str) -> float:
        return float(self._shared("%s_hub_clear_move_length" % device_id, 0))

    def _status_sensor_snapshot(
        self, snapshot: Mapping[str, Optional[bool]]
    ) -> Dict[str, Any]:
        hubs = {}
        if len(self.devices) > 1:
            hubs = {
                device.device_id: snapshot.get(
                    self._hub_sensor_key(device.device_id)
                )
                for device in self.devices
            }
        return {
            "upper": snapshot.get("upper"),
            "lower": snapshot.get("lower"),
            "rdm": snapshot.get("rdm"),
            "hubs": hubs,
        }

    def _topology_status(
        self, snapshot: Mapping[str, Optional[bool]]
    ) -> Dict[str, Any]:
        current_device = None
        if self.current_tool is not None:
            device_index, _slot = tool_target(self.current_tool)
            if 0 <= device_index < len(self.devices):
                current_device = self.devices[device_index].device_id
        multi_device = len(self.devices) > 1
        return {
            "mode": "two_stage" if multi_device else "single_device",
            "current_device": current_device,
            "route": (
                ["device_hub", "rdm", "upper", "lower"]
                if multi_device
                else ["rdm", "upper", "lower"]
            ),
            "branch_clearance": {
                device.device_id: self._hub_retract_length(device.device_id)
                + self._hub_clear_move_length(device.device_id)
                for device in self.devices
            } if multi_device else {},
            "branches": {
                device.device_id: {
                    "sensor_configured": bool(
                        self._shared(
                            "%s_hub_sensor_name" % device.device_id, None
                        )
                        or self._shared(
                            "%s_hub_sensor_pin" % device.device_id, None
                        )
                    ),
                    "sensor_state": snapshot.get(
                        self._hub_sensor_key(device.device_id)
                    ),
                    "retract_length": self._hub_retract_length(device.device_id),
                    "clear_move_length": self._hub_clear_move_length(
                        device.device_id
                    ),
                    "calibrated": self._hub_retract_length(device.device_id) > 0,
                }
                for device in self.devices
            } if multi_device else {},
        }

    def _all_path_sensors_clear(
        self, sensors: Mapping[str, Optional[bool]]
    ) -> bool:
        if sensors.get("upper") is not False:
            return False

        lower = sensors.get("lower")
        if lower is True or (lower is None and not self._lower_sensor_bypassed()):
            return False

        optional_sensors = ["rdm"]
        if len(self.devices) > 1:
            optional_sensors.extend(
                self._hub_sensor_key(device.device_id) for device in self.devices
            )
        for name in optional_sensors:
            state = sensors.get(name)
            if state is True:
                return False
            if state is None and self._path_sensor_configured(name):
                return False
        return True

    def _path_sensor_configured(self, name: str) -> bool:
        prefix = {
            "upper": "extruder",
            "lower": "toolhead",
            "rdm": "rdm",
        }.get(name, name)
        return bool(
            self._shared(prefix + "_sensor_name", None)
            or self._shared(prefix + "_sensor_pin", None)
        )

    def _loaded_route_matches(
        self, sensors: Mapping[str, Optional[bool]], tool: int
    ) -> bool:
        device_index, _slot = tool_target(tool)
        if not 0 <= device_index < len(self.devices):
            return False
        device_id = self.devices[device_index].device_id
        route_keys = {"rdm"}
        if len(self.devices) > 1:
            route_keys.add(self._hub_sensor_key(device_id))
        for name in route_keys:
            state = sensors.get(name)
            if state is not None and state is not True:
                return False
        if len(self.devices) > 1:
            for device in self.devices:
                name = self._hub_sensor_key(device.device_id)
                if name not in route_keys and sensors.get(name) is True:
                    return False
        return True

    def _assert_device_route_sensors(
        self, device: AceDevice, expected: bool
    ) -> None:
        names = ["rdm"]
        if len(self.devices) > 1:
            names.append(self._hub_sensor_key(device.device_id))
        for name in names:
            state = self._sensor(name)
            if state is None:
                continue
            if not self._sensor_stable(name, expected):
                label = (
                    "total-hub" if name == "rdm" else "%s first-stage hub" % device.device_id
                )
                raise AceSafetyError(
                    "%s sensor did not report the expected filament state" % label,
                    details={"sensor": name, "expected": expected, "state": state},
                )

    def _shared(self, name: str, default: Any) -> Any:
        if isinstance(self.shared, Mapping):
            return self.shared.get(name, default)
        return getattr(self.shared, name, default)

    def _state_get(self, name: str, default: Any) -> Any:
        if self.state_store is None:
            return default
        getter = getattr(self.state_store, "get", None)
        return getter(name, default) if getter else default

    def _state_set(self, name: str, value: Any) -> None:
        if self.state_store is None:
            return
        setter = getattr(self.state_store, "set", None)
        if setter:
            setter(name, value)

    def _persist_inventory(self) -> None:
        inventories = []
        for device in self.devices:
            inventories.append(device.get_status().get("slots", []))
        self._state_set("inventory", inventories)

    def _select_endless_candidate(self):
        selector = EndlessSpoolSelector(
            ToolMap(len(self.devices)),
            match_mode=self.endless_spool_match_mode,
            allow_cross_device=True,
        )
        return selector.select(self.current_tool, self._selector_device_statuses())

    def _selector_device_statuses(self):
        statuses = []
        for device in self.devices:
            raw = device.get_status()
            slots = []
            for index, item in enumerate(raw.get("slots", [])[:SLOT_COUNT]):
                color = item.get("color", "#808080")
                if isinstance(color, str):
                    text = color.lstrip("#")
                    try:
                        color_value = tuple(int(text[offset : offset + 2], 16) for offset in (0, 2, 4))
                    except (TypeError, ValueError):
                        color_value = (128, 128, 128)
                else:
                    color_value = tuple(color[:3]) if isinstance(color, (list, tuple)) else (128, 128, 128)
                try:
                    slot_status = SlotStatus(str(item.get("status", "unknown")).lower())
                except ValueError:
                    slot_status = SlotStatus.UNKNOWN
                slots.append(
                    SlotInventory(
                        index=index,
                        status=slot_status,
                        material=str(item.get("material", "")),
                        color=color_value,
                        temperature=int(item.get("temperature") or 0),
                        rfid=bool(item.get("rfid", False)),
                    )
                )
            while len(slots) < SLOT_COUNT:
                slots.append(SlotInventory(index=len(slots)))
            model = DeviceModel(device.model)
            actions = device.physical_actions_enabled and model == DeviceModel.ACE1
            statuses.append(
                DeviceStatus.initial(
                    device.device_id,
                    model,
                    device.enabled,
                    actions,
                )
            )
            statuses[-1].connection = (
                ConnectionState.ONLINE if device.connected else ConnectionState.OFFLINE
            )
            statuses[-1].slots = slots
        return statuses
