"""Moonraker boundary for Ace Pro Control Center.

This component reads Klipper's cached ``ace`` object and translates a strict
structured action whitelist to fixed G-code commands.  It never imports the
Klipper-side driver and never accepts raw G-code from a client.
"""

from __future__ import annotations

import copy
import inspect
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from uuid import uuid4


API_VERSION = 3
SCHEMA_VERSION = "3.0.0"

ENDPOINTS = (
    ("/server/ace/status", ["GET"], "handle_status_request"),
    ("/server/ace/capabilities", ["GET"], "handle_capabilities_request"),
    ("/server/ace/action", ["POST"], "handle_action_request"),
)

DEVICE_RE = re.compile(r"^ace([0-3])$")
TOOL_RE = re.compile(r"^T(?:[0-9]|1[0-5])$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

IDLE_PRINT_STATES = {"idle", "standby", "complete", "ready"}
PRINT_SAFE_ACTIONS = {
    "refresh",
    "diagnose",
    "set_slot",
    "set_endless_spool",
    "start_drying",
    "stop_drying",
    "enable_feed_assist",
    "disable_feed_assist",
}
PHYSICAL_ACTIONS = {
    "select_tool",
    "unload",
    "feed",
    "retract",
    "enable_feed_assist",
    "disable_feed_assist",
    "start_drying",
    "stop_drying",
    "calibrate",
    "recover",
}
CONFIRMATION_ACTIONS = {
    "select_tool",
    "unload",
    "feed",
    "retract",
    "start_drying",
    "enable_feed_assist",
    "calibrate",
    "recover",
}

TOOLCHANGE_ACTIONS = {
    "select_tool",
    "unload",
    "set_endless_spool",
    "endless_spool_change",
}
FEED_ASSIST_ACTIONS = {"enable_feed_assist", "disable_feed_assist"}
SHARED_ENCODER_CALIBRATION_ACTIONS = (
    "encoder_calibration_start",
    "encoder_calibration_finish",
    "encoder_calibration_cancel",
)

CAPABILITY_ALIASES = {
    "select_tool": ("select_tool", "change_tool", "physical_actions"),
    "unload": ("unload", "retract", "physical_actions"),
    "feed": ("feed",),
    "retract": ("retract",),
    "enable_feed_assist": ("enable_feed_assist", "feed_assist"),
    "disable_feed_assist": ("disable_feed_assist", "feed_assist"),
    "start_drying": ("start_drying", "drying", "dryer"),
    "stop_drying": ("stop_drying", "drying", "dryer"),
    "set_slot": ("set_slot", "inventory"),
    "set_endless_spool": ("set_endless_spool", "endless_spool"),
    "calibrate": ("calibrate", "calibration"),
    "recover": ("recover", "recovery", "status"),
}

_CHINESE_RE = re.compile(r"[\u3400-\u9fff]")

_BLOCKED_REASON_MESSAGES = {
    "manual_mode": "当前处于手动模式，ACE 自动换料未启用。",
    "physical_actions_disabled": "ACE 设备的物理动作未启用。",
    "machine_hooks_incomplete": "自动换料所需的机器动作宏尚未完整配置。",
    "machine_macros_not_configured": "自动换料所需的机器动作宏尚未完整配置。",
    "encoder_calibration_active": "共享耗材编码器正在校准。",
    "encoder_not_ready": "共享耗材编码器保护尚未就绪。",
    "path_sensors_incomplete": "自动换料所需的耗材传感器尚未完整配置。",
    "lower_sensor_bypass_uncalibrated": "下方传感器旁路距离尚未校准。",
    "total_hub_sensor_missing": "多台 ACE 自动换料需要配置总五通传感器。",
    "branch_clearance_incomplete": "ACE 分支退出五通的回抽距离尚未全部校准。",
    "path_state_unknown": "共享耗材路径状态未知，需要先检查并恢复。",
}

_ENGLISH_USER_MESSAGES = {
    "Capability is unavailable.": "当前操作能力不可用。",
    "Capability is not supported.": "当前驱动或设备不支持此操作。",
    "The driver did not declare this action capability.": "驱动未声明此操作能力。",
    "The selected ACE target does not declare this capability.": "所选 ACE 目标未声明此操作能力。",
    "ACE2 is read-only in this release.": "当前版本中的 ACE2 仅支持读取状态。",
    "Physical actions are disabled.": "ACE 设备的物理动作未启用。",
    "The ACE device is offline.": "ACE 设备未连接。",
    "Automatic tool changing is disabled in manual mode.": "当前处于手动模式，ACE 自动换料未启用。",
    "Automatic tool changing is not ready.": "ACE 自动换料尚未就绪。",
}

_ERROR_FALLBACK_MESSAGES = {
    "status_unavailable": "无法读取 ACE 状态。",
    "ace_not_loaded": "Klipper 尚未加载 ACE 状态对象。",
    "execution_failed": "Klipper 未能完成 ACE 操作。",
    "toolchange_unavailable": "ACE 自动换料当前不可用。",
    "confirmation_required": "此 ACE 操作需要明确确认。",
    "print_state_blocked": "当前打印机状态禁止执行此 ACE 操作。",
    "path_busy": "共享耗材路径正忙。",
    "target_unavailable": "无法安全确定 ACE 操作目标。",
    "ace2_read_only": "当前版本中的 ACE2 仅支持读取状态。",
    "physical_actions_disabled": "所选 ACE 设备的物理动作未启用。",
    "device_offline": "所选 ACE 设备未连接。",
    "capability_unavailable": "当前 ACE 操作能力不可用。",
    "invalid_request": "请求格式无效。",
    "unknown_parameter": "请求包含不支持的参数。",
    "unknown_action": "请求的 ACE 操作不在允许列表中。",
    "invalid_params": "params 必须是 JSON 对象。",
    "missing_parameter": "缺少必需的 ACE 操作参数。",
    "invalid_confirmation": "confirm 参数必须是 true 或 false。",
    "invalid_client": "client 参数格式无效。",
    "duplicate_parameter": "请求包含重复参数。",
    "invalid_parameter": "ACE 操作参数无效。",
    "target_mismatch": "ACE 操作目标参数互相冲突。",
    "invalid_device": "ACE 设备编号无效。",
    "invalid_tool": "工具通道编号无效。",
}

_ERROR_NEXT_ACTIONS = {
    "status_unavailable": "请检查 Klipper 与 Moonraker 的连接和服务状态，然后重试。",
    "ace_not_loaded": "请检查 printer.cfg 是否已加载 ACE 配置，并重启 Klipper 后重试。",
    "execution_failed": "请查看 Klipper 控制台和日志，排除故障后重试。",
    "toolchange_unavailable": "请完成自动换料配置并确认系统就绪后重试。",
    "confirmation_required": "请确认操作风险后重新提交，并将 confirm 设置为 true。",
    "print_state_blocked": "请等待打印机进入空闲状态后重试。",
    "path_busy": "请等待当前耗材路径动作完成后重试。",
    "target_unavailable": "请检查设备、工具通道和槽位参数后重试。",
    "ace2_read_only": "当前版本请仅查看 ACE2 状态，不要执行物理动作。",
    "physical_actions_disabled": "请确认硬件和安全配置后，再启用该设备的物理动作。",
    "device_offline": "请检查 ACE 供电、串口和连接状态后重试。",
    "capability_unavailable": "请检查设备型号、连接状态和相关功能配置。",
    "invalid_request": "请按 API 文档提交 JSON 对象。",
    "unknown_parameter": "请移除不支持的参数后重试。",
    "unknown_action": "请使用驱动声明的 ACE 操作名。",
    "invalid_params": "请将 params 修改为 JSON 对象后重试。",
    "missing_parameter": "请补齐错误详情中列出的必需参数后重试。",
    "invalid_confirmation": "请将 confirm 设置为 true 或 false。",
    "invalid_client": "请填写 1 到 64 个字符的 client 标识。",
    "duplicate_parameter": "请仅保留一组同义参数后重试。",
    "invalid_parameter": "请按错误提示修正参数后重试。",
    "target_mismatch": "请让工具通道、设备和槽位指向同一目标。",
    "invalid_device": "请使用 ace0 到 ace3 中已经配置的设备编号。",
    "invalid_tool": "请使用 T0 到 T15 范围内的工具通道。",
}


def _contains_chinese(value: Any) -> bool:
    return bool(_CHINESE_RE.search(str(value or "")))


def _localize_user_text(
    value: Any, *, code: str = "", fallback: str = "ACE 操作当前不可用。"
) -> str:
    text = str(value or "").strip()
    if _contains_chinese(text):
        return text
    if text in _BLOCKED_REASON_MESSAGES:
        return _BLOCKED_REASON_MESSAGES[text]
    if text in _ENGLISH_USER_MESSAGES:
        return _ENGLISH_USER_MESSAGES[text]
    if code in _ERROR_FALLBACK_MESSAGES:
        return _ERROR_FALLBACK_MESSAGES[code]
    return fallback


def _localize_capability_reason(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _localize_user_text(
        text,
        code="capability_unavailable",
        fallback="当前操作不可用，请检查 ACE 驱动状态与配置。",
    )


def _error_next_action(code: str, retryable: bool) -> str:
    if code in _ERROR_NEXT_ACTIONS:
        return _ERROR_NEXT_ACTIONS[code]
    if retryable:
        return "请确认设备连接和服务状态恢复正常后重试。"
    return "请检查请求参数、ACE 配置和诊断信息。"


class RequestRejected(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Optional[Mapping] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = dict(details or {})


class ActionSpec:
    def __init__(
        self,
        required: Iterable[str] = (),
        optional: Iterable[str] = (),
        *,
        physical: bool = False,
        confirmation: bool = False,
    ) -> None:
        self.required = frozenset(required)
        self.optional = frozenset(optional)
        self.physical = physical
        self.confirmation = confirmation


ACTION_SPECS = {
    "refresh": ActionSpec(optional=("device",)),
    "diagnose": ActionSpec(optional=("device", "slot")),
    "select_tool": ActionSpec(
        required=("tool",), physical=True, confirmation=True
    ),
    "unload": ActionSpec(physical=True, confirmation=True),
    "feed": ActionSpec(
        required=("device", "length"),
        optional=("slot", "speed"),
        physical=True,
        confirmation=True,
    ),
    "retract": ActionSpec(
        required=("device", "length"),
        optional=("slot", "speed"),
        physical=True,
        confirmation=True,
    ),
    "enable_feed_assist": ActionSpec(
        optional=("device", "tool", "slot"),
        physical=True,
        confirmation=True,
    ),
    "disable_feed_assist": ActionSpec(
        optional=("device", "tool", "slot"),
        physical=True,
    ),
    "start_drying": ActionSpec(
        required=("device", "temperature", "duration"),
        physical=True,
        confirmation=True,
    ),
    "stop_drying": ActionSpec(required=("device",), physical=True),
    "set_slot": ActionSpec(
        required=("device", "slot"),
        optional=("material", "color", "temperature", "rfid", "status"),
    ),
    "set_endless_spool": ActionSpec(
        required=("enabled",), optional=("device", "match_mode")
    ),
    "encoder_calibration_start": ActionSpec(),
    "encoder_calibration_finish": ActionSpec(required=("length",)),
    "encoder_calibration_cancel": ActionSpec(),
    "calibrate": ActionSpec(
        required=("device", "mode"),
        optional=("slot",),
        physical=True,
        confirmation=True,
    ),
    "recover": ActionSpec(required=("device",), confirmation=True),
}


class AceStatus:
    """A real Moonraker component with injectable test boundaries."""

    def __init__(
        self,
        config: Any,
        *,
        status_provider: Optional[Callable] = None,
        action_runner: Optional[Callable] = None,
    ) -> None:
        self.server = config.get_server()
        self.klippy_apis = self.server.lookup_component("klippy_apis")
        self._status_provider = status_provider or self._query_klippy_status
        self._action_runner = action_runner or self.klippy_apis.run_gcode
        for path, methods, handler_name in ENDPOINTS:
            self.server.register_endpoint(path, methods, getattr(self, handler_name))

    async def _query_klippy_status(self) -> Mapping:
        return await self.klippy_apis.query_objects(
            {"ace": None, "print_stats": ["state"]}
        )

    async def _query_status(self) -> Dict[str, Any]:
        value = self._status_provider()
        if inspect.isawaitable(value):
            value = await value
        if isinstance(value, Mapping) and isinstance(value.get("status"), Mapping):
            value = value["status"]
        if not isinstance(value, Mapping):
            raise RequestRejected(
                "status_unavailable",
                "Klipper 返回了无效的对象状态响应。",
                retryable=True,
            )
        ace = value.get("ace")
        if not isinstance(ace, Mapping):
            raise RequestRejected(
                "ace_not_loaded",
                "Klipper 尚未提供 ACE Pro 管理中心状态对象。",
                retryable=True,
            )
        print_stats = value.get("print_stats")
        print_state = "unknown"
        if isinstance(print_stats, Mapping):
            state = print_stats.get("state")
            if isinstance(state, str) and state.strip():
                print_state = state.strip().lower()
        status = _normalize_driver_status(_json_safe(copy.deepcopy(dict(ace))))
        status["print_state"] = print_state
        status["system"]["print_state"] = print_state
        status.setdefault("schema_version", SCHEMA_VERSION)
        return status

    async def handle_status_request(self, web_request: Any) -> Dict[str, Any]:
        request_id = _request_id(web_request)
        try:
            status = await self._query_status()
            return _success(request_id, "status", status)
        except RequestRejected as exc:
            return _failure_from_rejection(request_id, "status", exc)
        except Exception as exc:
            return _failure(
                request_id,
                "status",
                "status_unavailable",
                "无法从 Klipper 读取 ACE 状态。",
                retryable=True,
                details={"exception_type": type(exc).__name__},
            )

    async def handle_capabilities_request(
        self, web_request: Any
    ) -> Dict[str, Any]:
        request_id = _request_id(web_request)
        try:
            status = await self._query_status()
            return _success(
                request_id,
                "capabilities",
                self._build_capabilities(status),
            )
        except RequestRejected as exc:
            return _failure_from_rejection(request_id, "capabilities", exc)
        except Exception as exc:
            return _failure(
                request_id,
                "capabilities",
                "status_unavailable",
                "无法从 Klipper 读取 ACE 功能能力。",
                retryable=True,
                details={"exception_type": type(exc).__name__},
            )

    async def handle_action_request(self, web_request: Any) -> Dict[str, Any]:
        request_id = _request_id(web_request)
        action = "unknown"
        try:
            payload = _request_payload(web_request)
            action, params, confirmed, client = _validate_payload(payload)
            status = await self._query_status()
            target = self._validate_action(action, params, confirmed, status)

            if action == "diagnose":
                return _success(
                    request_id,
                    action,
                    {
                        "action": action,
                        "accepted": True,
                        "completed": True,
                        "client": client,
                        "diagnostic": _cached_diagnostic(status, target),
                    },
                )

            command = _build_command(action, params, target, confirmed=confirmed)
            result = self._action_runner(command)
            if inspect.isawaitable(result):
                result = await result
            return _success(
                request_id,
                action,
                {
                    "action": action,
                    "accepted": True,
                    "completed": True,
                    "client": client,
                    "target": target,
                    "klipper_result": _json_safe(result),
                },
            )
        except RequestRejected as exc:
            return _failure_from_rejection(request_id, action, exc)
        except Exception as exc:
            return _failure(
                request_id,
                action,
                "execution_failed",
                "Klipper 拒绝了 ACE 操作，或执行该操作时发生故障。",
                retryable=True,
                details={"exception_type": type(exc).__name__},
            )

    def _validate_action(
        self,
        action: str,
        params: Mapping,
        confirmed: bool,
        status: Mapping,
    ) -> Dict[str, Any]:
        spec = ACTION_SPECS[action]
        target = _resolve_target(action, params, status)

        if _action_requires_toolchange(action, params) and not _toolchange_available(status):
            raise RequestRejected(
                "toolchange_unavailable",
                _toolchange_block_message(status),
                details={
                    "action": action,
                    "toolchange_mode": status.get("toolchange_mode"),
                    "toolchange_ready": status.get("toolchange_ready"),
                    "toolchange_blocked_reason": status.get(
                        "toolchange_blocked_reason"
                    ),
                },
            )

        if spec.confirmation and not confirmed:
            raise RequestRejected(
                "confirmation_required",
                "此 ACE 操作需要明确确认。",
                details={"action": action},
            )

        print_state = str(status.get("print_state") or "unknown").lower()
        if action not in PRINT_SAFE_ACTIONS and print_state not in IDLE_PRINT_STATES:
            raise RequestRejected(
                "print_state_blocked",
                "当前打印机状态禁止执行此 ACE 操作。",
                retryable=True,
                details={"action": action, "print_state": print_state},
            )

        if _path_busy(status) and action not in {
            "refresh",
            "diagnose",
            "disable_feed_assist",
            "encoder_calibration_cancel",
        }:
            raise RequestRejected(
                "path_busy",
                "共享耗材路径已有正在执行的操作。",
                retryable=True,
                details={"action": action},
            )

        device = _target_device(target, status)
        if spec.physical:
            if device is None:
                raise RequestRejected(
                    "target_unavailable",
                    "无法安全确定 ACE 物理操作目标。",
                )
            model = str(device.get("model") or "unknown").lower()
            if model == "ace2":
                raise RequestRejected(
                    "ace2_read_only",
                    "ACE2 完成真机验证前仅支持读取状态，物理动作已禁用。",
                    details={"device": target.get("device"), "action": action},
                )
            if not bool(device.get("physical_actions_enabled", False)):
                raise RequestRejected(
                    "physical_actions_disabled",
                    "所选 ACE 设备的物理动作未启用。",
                    details={"device": target.get("device"), "action": action},
                )
            if not bool(device.get("connected", False)):
                raise RequestRejected(
                    "device_offline",
                    "所选 ACE 设备未连接。",
                    retryable=True,
                    details={"device": target.get("device")},
                )

        disabling_unready_endless_spool = (
            action == "set_endless_spool"
            and params.get("enabled") is False
            and not _toolchange_available(status)
        )
        if action in SHARED_ENCODER_CALIBRATION_ACTIONS:
            available, reason = _encoder_calibration_capability(action, status)
            if not available:
                raise RequestRejected(
                    "capability_unavailable",
                    reason,
                    details={"action": action},
                )
        elif action not in {"refresh", "diagnose"} and not disabling_unready_endless_spool:
            available, reason = _action_capability(action, status, device)
            if not available:
                raise RequestRejected(
                    "capability_unavailable",
                    _localize_capability_reason(reason)
                    or "所选 ACE 目标未声明此操作能力。",
                    details={"device": target.get("device"), "action": action},
                )
        return target

    def _build_capabilities(self, status: Mapping) -> Dict[str, Any]:
        actions = {}
        for action, spec in ACTION_SPECS.items():
            params = _sample_target_params(action, status)
            target = _resolve_target(action, params, status, strict=False)
            device = _target_device(target, status)
            available = True
            reason = ""
            if action in SHARED_ENCODER_CALIBRATION_ACTIONS:
                available, reason = _encoder_calibration_capability(action, status)
            else:
                if action in TOOLCHANGE_ACTIONS and not _toolchange_available(status):
                    available, reason = False, _toolchange_block_message(status)
                if available and spec.physical:
                    model = str((device or {}).get("model") or "unknown").lower()
                    if device is None:
                        available, reason = False, "没有可用的已配置目标。"
                    elif model == "ace2":
                        available, reason = False, "当前版本中的 ACE2 仅支持读取状态。"
                    elif not bool(device.get("physical_actions_enabled", False)):
                        available, reason = False, "ACE 设备的物理动作未启用。"
                    elif not bool(device.get("connected", False)):
                        available, reason = False, "ACE 设备未连接。"
                if available and action not in {"refresh", "diagnose"}:
                    available, reason = _action_capability(action, status, device)
            actions[action] = {
                "available": available,
                "reason": reason,
                "physical": spec.physical,
                "allowed_when_printing": action in PRINT_SAFE_ACTIONS,
                "confirmation_required": spec.confirmation,
                "requires_confirmation": spec.confirmation,
                "required_params": sorted(spec.required),
                "optional_params": sorted(spec.optional),
            }
        return {
            "schema_version": SCHEMA_VERSION,
            "device_limit": 4,
            "tool_range": {"min": 0, "max": 15, "format": "Tn"},
            "toolchange_mode": status.get("toolchange_mode"),
            "toolchange_ready": bool(status.get("toolchange_ready", False)),
            "toolchange_blocked_reason": status.get("toolchange_blocked_reason"),
            "actions": actions,
        }


def _request_payload(web_request: Any) -> Mapping:
    getter = getattr(web_request, "get_args", None)
    value = getter() if callable(getter) else web_request
    if not isinstance(value, Mapping):
        raise RequestRejected("invalid_request", "请求正文必须是 JSON 对象。")
    return value


def _validate_payload(payload: Mapping) -> Tuple[str, Dict[str, Any], bool, str]:
    unknown = set(payload) - {"action", "params", "confirm", "client"}
    if unknown:
        raise RequestRejected(
            "unknown_parameter",
            "请求包含不支持的顶层字段，已拒绝处理。",
            details={"fields": sorted(str(item) for item in unknown)},
        )
    action = payload.get("action")
    if not isinstance(action, str) or action not in ACTION_SPECS:
        raise RequestRejected("unknown_action", "请求的 ACE 操作不在允许列表中。")
    params = payload.get("params", {})
    if not isinstance(params, Mapping):
        raise RequestRejected("invalid_params", "params 必须是 JSON 对象。")
    params = _canonicalize_params(action, params)
    spec = ACTION_SPECS[action]
    missing = spec.required - set(params)
    unknown_params = set(params) - spec.required - spec.optional
    if missing:
        raise RequestRejected(
            "missing_parameter",
            "缺少必需的 ACE 操作参数。",
            details={"fields": sorted(missing)},
        )
    if unknown_params:
        raise RequestRejected(
            "unknown_parameter",
            "请求包含不支持的 ACE 操作参数，已拒绝处理。",
            details={"fields": sorted(str(item) for item in unknown_params)},
        )
    _validate_params(action, params)
    confirm = payload.get("confirm", False)
    if not isinstance(confirm, bool):
        raise RequestRejected("invalid_confirmation", "confirm 必须是 true 或 false。")
    client = payload.get("client", "unknown")
    if not isinstance(client, str) or not 1 <= len(client) <= 64:
        raise RequestRejected("invalid_client", "client 必须是 1 到 64 个字符的字符串。")
    return action, params, confirm, client


def _canonicalize_params(action: str, params: Mapping) -> Dict[str, Any]:
    result = dict(params)
    aliases = {
        "device_id": "device",
        "duration_minutes": "duration",
        "target_temperature": "temperature",
    }
    for source, target in aliases.items():
        if source not in result:
            continue
        if target in result:
            raise RequestRejected(
                "duplicate_parameter",
                "参数 %s 与 %s 不能同时提供。" % (source, target),
            )
        result[target] = result.pop(source)
    if action in FEED_ASSIST_ACTIONS:
        for source, target in (("tool_id", "tool"), ("index", "slot")):
            if source not in result:
                continue
            if target in result:
                raise RequestRejected(
                    "duplicate_parameter",
                    "参数 %s 与 %s 不能同时提供。" % (source, target),
                )
            result[target] = result.pop(source)
    if action == "set_slot":
        for unsupported in ("spool_id", "maintenance"):
            if unsupported in result and result[unsupported] in (None, ""):
                result.pop(unsupported)
    return result


def _validate_params(action: str, params: Mapping) -> None:
    if "device" in params:
        _device_id(params["device"])
    if "tool" in params:
        _tool(params["tool"])
    if "slot" in params:
        _integer(params["slot"], "slot", 0, 3)
    if "length" in params:
        _number(params["length"], "length", 0.01, 2000.0)
    if "speed" in params:
        _number(params["speed"], "speed", 0.01, 1000.0)
    if "temperature" in params and params["temperature"] is not None:
        _number(params["temperature"], "temperature", 0.0, 100.0)
    if "duration" in params:
        _integer(params["duration"], "duration", 1, 1440)
    if "enabled" in params and not isinstance(params["enabled"], bool):
        raise RequestRejected("invalid_parameter", "enabled 必须是 true 或 false。")
    if "match_mode" in params and params["match_mode"] not in {"exact", "material"}:
        raise RequestRejected(
            "capability_unavailable",
            "当前版本的无限续料仅支持 exact 或 material 匹配模式。",
        )
    if "color" in params and not COLOR_RE.fullmatch(str(params["color"])):
        raise RequestRejected("invalid_parameter", "color 必须使用 #RRGGBB 格式。")
    for name in ("material", "rfid"):
        if name in params:
            _safe_text(params[name], name, 64)
    if "status" in params and params["status"] not in {
        "unknown", "empty", "ready", "feeding", "retracting", "identifying", "error"
    }:
        raise RequestRejected(
            "invalid_parameter", "status 不是受支持的槽位状态。"
        )
    if action == "calibrate":
        if params["mode"] not in {"probe", "save", "cancel"}:
            raise RequestRejected(
                "invalid_parameter", "校准模式必须是 probe、save 或 cancel。"
            )
    if action in FEED_ASSIST_ACTIONS:
        has_tool = params.get("tool") is not None
        has_device_slot = (
            params.get("device") is not None and params.get("slot") is not None
        )
        if not has_tool and not has_device_slot:
            raise RequestRejected(
                "missing_parameter",
                "辅助送料必须指定 tool，或同时指定 device 与 slot。",
                details={"required_alternatives": ["tool", "device+slot"]},
            )


def _resolve_target(
    action: str, params: Mapping, status: Mapping, *, strict: bool = True
) -> Dict[str, Any]:
    target = {"device": params.get("device"), "tool": params.get("tool"), "slot": params.get("slot")}
    if action == "select_tool":
        tool = _tool(params.get("tool"))
        target.update(tool=tool, device="ace%d" % (int(tool[1:]) // 4), slot=int(tool[1:]) % 4)
    elif action == "unload":
        current = _current_tool(status)
        if current is not None:
            target.update(tool=current, device="ace%d" % (int(current[1:]) // 4), slot=int(current[1:]) % 4)
    elif action in {"feed", "retract"}:
        if target.get("slot") is not None:
            slot = int(target["slot"])
            device_id = _device_id(target["device"])
            tool = "T%d" % (int(device_id[3:]) * 4 + slot)
            target.update(tool=tool, slot=slot)
        else:
            current = _current_tool(status)
            if current is not None:
                current_device = "ace%d" % (int(current[1:]) // 4)
                if current_device == target.get("device"):
                    target.update(tool=current, slot=int(current[1:]) % 4)
    elif action in FEED_ASSIST_ACTIONS:
        if target.get("tool") is not None:
            tool = _tool(target["tool"])
            expected_device = "ace%d" % (int(tool[1:]) // 4)
            expected_slot = int(tool[1:]) % 4
            if target.get("device") not in (None, expected_device):
                raise RequestRejected(
                    "target_mismatch",
                    "device 与请求的辅助送料工具通道不匹配。",
                )
            if target.get("slot") not in (None, expected_slot):
                raise RequestRejected(
                    "target_mismatch",
                    "slot 与请求的辅助送料工具通道不匹配。",
                )
            target.update(
                tool=tool, device=expected_device, slot=expected_slot
            )
        elif target.get("device") is not None and target.get("slot") is not None:
            device_id = _device_id(target["device"])
            slot = int(target["slot"])
            target.update(
                device=device_id,
                slot=slot,
                tool="T%d" % (int(device_id[3:]) * 4 + slot),
            )
    if (
        target.get("device") is None
        and action != "set_endless_spool"
        and action not in SHARED_ENCODER_CALIBRATION_ACTIONS
    ):
        devices = _devices(status)
        if len(devices) == 1:
            target["device"] = next(iter(devices))
    if strict and target.get("device") is not None:
        configured = _devices(status)
        if target["device"] not in configured:
            raise RequestRejected(
                "invalid_device", "请求的 ACE 设备尚未配置。"
            )
    if strict and action in {"feed", "retract"} and target.get("tool") is None:
        raise RequestRejected(
            "target_unavailable",
            "手动送料或回料必须指定槽位，或存在当前已装载的工具通道。",
        )
    return target


def _build_command(
    action: str, params: Mapping, target: Mapping, *, confirmed: bool = False
) -> str:
    if action == "select_tool":
        return "ACE_CHANGE_TOOL TOOL=%s" % _tool(params["tool"])
    if action == "unload":
        return "ACE_CHANGE_TOOL TOOL=TR"
    if action == "refresh":
        return _command("ACE_REFRESH", params, (("device", "DEVICE"),))
    if action in {"feed", "retract"}:
        name = "ACE_FEED" if action == "feed" else "ACE_RETRACT"
        return _command(
            name,
            dict(params, tool=target["tool"], speed=params.get("speed", 80)),
            (("tool", "TOOL"), ("length", "LENGTH"), ("speed", "SPEED")),
        )
    if action in FEED_ASSIST_ACTIONS:
        name = (
            "ACE_ENABLE_FEED_ASSIST"
            if action == "enable_feed_assist"
            else "ACE_DISABLE_FEED_ASSIST"
        )
        command_params = dict(target)
        if action == "enable_feed_assist" and confirmed:
            command_params["confirm"] = 1
        return _command(
            name,
            command_params,
            (
                ("device", "DEVICE"),
                ("tool", "TOOL"),
                ("slot", "SLOT"),
                ("confirm", "CONFIRM"),
            ),
        )
    if action == "start_drying":
        return _command(
            "ACE_START_DRYING",
            params,
            (("device", "DEVICE"), ("temperature", "TEMP"), ("duration", "DURATION")),
        )
    if action == "stop_drying":
        return _command("ACE_STOP_DRYING", params, (("device", "DEVICE"),))
    if action == "set_slot":
        return _command(
            "ACE_SET_SLOT",
            params,
            (("device", "DEVICE"), ("slot", "SLOT"), ("material", "MATERIAL"), ("color", "COLOR"), ("temperature", "TEMP"), ("rfid", "RFID"), ("status", "STATUS")),
        )
    if action == "set_endless_spool":
        return _command(
            "ACE_SET_ENDLESS_SPOOL",
            params,
            (("enabled", "ENABLE"), ("match_mode", "MATCH_MODE")),
        )
    if action == "encoder_calibration_start":
        return "ACE_ENCODER_CALIBRATE START=1"
    if action == "encoder_calibration_finish":
        return _command(
            "ACE_ENCODER_CALIBRATE",
            params,
            (("length", "LENGTH"),),
        )
    if action == "encoder_calibration_cancel":
        return "ACE_ENCODER_CALIBRATE CANCEL=1"
    if action == "calibrate":
        return _command(
            "ACE_CALIBRATE",
            params,
            (("device", "DEVICE"), ("mode", "MODE"), ("slot", "SLOT")),
        )
    if action == "recover":
        return _command("ACE_RECONNECT", params, (("device", "DEVICE"),))
    raise RequestRejected("unknown_action", "请求的 ACE 操作不在允许列表中。")


def _command(name: str, params: Mapping, fields: Sequence[Tuple[str, str]]) -> str:
    parts = [name]
    for source, target in fields:
        if source not in params or params[source] is None:
            continue
        value = params[source]
        if isinstance(value, bool):
            rendered = "1" if value else "0"
        elif isinstance(value, str):
            rendered = _quote_gcode(value)
        else:
            rendered = str(value)
        parts.append("%s=%s" % (target, rendered))
    return " ".join(parts)


def _quote_gcode(value: str) -> str:
    _safe_text(value, "string", 128)
    if re.fullmatch(r"[A-Za-z0-9_.:#/+\-]+", value):
        return value
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _normalize_driver_status(status: Mapping) -> Dict[str, Any]:
    """Adapt the Klipper manager cache to the stable frontend status shape."""

    result = dict(status)
    schema = result.get("schema_version", SCHEMA_VERSION)
    result["schema_version"] = str(schema) if schema is not None else SCHEMA_VERSION
    _normalize_toolchange_status(result)

    raw_devices = _devices(result)
    devices = []
    for device_id, raw in sorted(
        raw_devices.items(), key=lambda item: int(item[0][3:])
    ):
        item = dict(raw)
        index = int(device_id[3:])
        item["id"] = device_id
        item["device_id"] = device_id
        item["index"] = index
        if "connected" not in item:
            item["connected"] = str(item.get("connection", "")).lower() in {
                "connected",
                "ready",
            }
        raw_caps = item.get("capabilities", {})
        item["protocol_capabilities"] = _json_safe(raw_caps)
        item["capabilities"] = {
            "actions": _device_action_capabilities(item, raw_caps, result)
        }
        dryer = item.get("dryer")
        if isinstance(dryer, Mapping):
            dryer = dict(dryer)
            if "target" in dryer:
                dryer.setdefault("target_temperature", dryer["target"])
            if "remaining" in dryer:
                dryer.setdefault("remaining_minutes", dryer["remaining"])
            item["dryer"] = dryer
        slots = item.get("slots", [])
        normalized_slots = []
        if isinstance(slots, list):
            for slot_index, raw_slot in enumerate(slots[:4]):
                slot = dict(raw_slot) if isinstance(raw_slot, Mapping) else {}
                slot["index"] = slot_index
                slot.setdefault("tool", "T%d" % (index * 4 + slot_index))
                state = str(slot.get("state", slot.get("status", "unknown"))).lower()
                slot["state"] = state
                slot.setdefault(
                    "available",
                    state not in {"empty", "unavailable", "error", "missing"},
                )
                normalized_slots.append(slot)
        item["slots"] = normalized_slots
        endless = result.get("endless_spool")
        if isinstance(endless, Mapping):
            item.setdefault("endless_spool", dict(endless))
        devices.append(item)
    result["devices"] = devices

    path = result.get("path")
    if isinstance(path, Mapping):
        result.setdefault(
            "path_lock",
            {
                "locked": bool(path.get("busy", False)),
                "owner": path.get("owner", ""),
            },
        )
        transaction = path.get("transaction")
        if isinstance(transaction, Mapping):
            normalized_transaction = dict(transaction)
            normalized_transaction.setdefault(
                "active", bool(path.get("busy", False))
            )
            result.setdefault("transaction", normalized_transaction)

    system = result.get("system")
    if not isinstance(system, Mapping):
        system = {}
    system = dict(system)
    system.setdefault("print_state", result.get("print_state", "unknown"))
    system.setdefault("current_tool", result.get("current_tool"))
    system.setdefault("toolchange_mode", result["toolchange_mode"])
    system.setdefault("toolchange_ready", result["toolchange_ready"])
    system.setdefault(
        "toolchange_blocked_reason", result["toolchange_blocked_reason"]
    )
    result["system"] = system

    result["capabilities"] = _normalize_root_capabilities(
        result.get("capabilities"), result
    )
    return result


def _normalize_toolchange_status(result: Dict[str, Any]) -> None:
    legacy_contract = (
        "toolchange_mode" not in result and "toolchange_ready" not in result
    )
    raw_mode = result.get("toolchange_mode")
    if isinstance(raw_mode, str) and raw_mode.strip().lower() in {
        "manual",
        "automatic",
    }:
        mode = raw_mode.strip().lower()
    elif "toolchange_mode" not in result:
        mode = "automatic"
    else:
        mode = "manual"

    raw_ready = result.get("toolchange_ready")
    if isinstance(raw_ready, bool):
        ready = raw_ready
    elif legacy_contract or "toolchange_ready" not in result:
        ready = mode == "automatic"
    else:
        ready = False
    if mode != "automatic":
        ready = False

    blocked_reason = result.get("toolchange_blocked_reason")
    if isinstance(blocked_reason, str):
        blocked_reason = blocked_reason.strip() or None
    elif blocked_reason is not None:
        blocked_reason = None

    notice_present = "toolchange_notice" in result
    notice = _normalize_toolchange_notice(result.get("toolchange_notice"))
    raw_notices = result.get("toolchange_notices")
    notices = []
    if isinstance(raw_notices, list):
        for raw_notice in raw_notices:
            normalized = _normalize_toolchange_notice(raw_notice)
            if normalized is not None:
                notices.append(normalized)
    elif notice is not None:
        notices.append(dict(notice))
    if not notice_present and notices:
        notice = dict(notices[-1])

    result["toolchange_mode"] = mode
    result["toolchange_ready"] = ready
    result["toolchange_blocked_reason"] = blocked_reason
    result["toolchange_notice"] = notice
    result["toolchange_notices"] = notices


def _normalize_toolchange_notice(value: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(value, Mapping):
        return None
    sequence = value.get("sequence")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        return None
    code = value.get("code")
    command = value.get("command")
    message = value.get("message")
    if not all(isinstance(item, str) for item in (code, command, message)):
        return None
    command = command.strip().upper()
    if command != "TR" and not TOOL_RE.fullmatch(command):
        return None
    normalized_message = message.strip()
    if not _contains_chinese(normalized_message):
        if re.fullmatch(r"(?:T(?:[0-9]|1[0-5])|TR) was ignored\.?", normalized_message, re.I):
            normalized_message = (
                "已忽略 %s。ACE 自动换料尚未配置，当前仅可使用辅助送料。"
                % command
            )
        else:
            normalized_message = "已忽略 %s，ACE 自动换料当前不可用。" % command
    return {
        "sequence": sequence,
        "code": code.strip(),
        "command": command,
        "message": normalized_message,
    }


def _toolchange_available(status: Mapping) -> bool:
    return (
        status.get("toolchange_mode") == "automatic"
        and status.get("toolchange_ready") is True
    )


def _toolchange_block_message(status: Mapping) -> str:
    reason = status.get("toolchange_blocked_reason")
    if isinstance(reason, str) and reason.strip():
        return _localize_capability_reason(reason)
    if status.get("toolchange_mode") != "automatic":
        return "当前处于手动模式，ACE 自动换料未启用。"
    return "ACE 自动换料尚未就绪。"


def _action_requires_toolchange(action: str, params: Mapping) -> bool:
    if action == "set_endless_spool":
        return params.get("enabled") is True
    return action in TOOLCHANGE_ACTIONS


def _normalize_root_capabilities(value: Any, status: Mapping) -> Dict[str, Any]:
    container = dict(value) if isinstance(value, Mapping) else {}
    nested = container.get("actions")
    if isinstance(nested, Mapping):
        source = nested
    else:
        known_names = set(ACTION_SPECS) | {"endless_spool_change"}
        source = {
            name: item
            for name, item in container.items()
            if name in known_names
        }

    actions = {
        str(action): _normalized_capability_entry(str(action), raw)
        for action, raw in source.items()
        if isinstance(action, str)
        and (action in ACTION_SPECS or action == "endless_spool_change")
    }
    if not actions:
        actions = {
            "refresh": _capability_entry(True, False, True, False),
            "diagnose": _capability_entry(True, False, True, False),
            "set_endless_spool": _capability_entry(True, False, True, False),
        }
    if not _toolchange_available(status):
        for action in TOOLCHANGE_ACTIONS.intersection(actions):
            actions[action] = _blocked_capability(
                actions[action], _toolchange_block_message(status)
            )
    for action in SHARED_ENCODER_CALIBRATION_ACTIONS:
        available, reason = _encoder_calibration_capability(action, status)
        actions[action] = _capability_entry(
            available,
            False,
            False,
            False,
            reason,
        )
    container["actions"] = actions
    return container


def _action_capability_source(value: Any) -> Optional[Mapping]:
    if not isinstance(value, Mapping):
        return None
    nested = value.get("actions")
    if isinstance(nested, Mapping):
        return nested
    names = set(value)
    if names and names.issubset(ACTION_SPECS):
        return value
    return None


def _device_action_capabilities(
    device: Mapping, raw_capabilities: Any, status: Mapping
) -> Dict[str, Any]:
    source = _action_capability_source(raw_capabilities)
    if source is not None:
        actions = {
            str(action): _normalized_capability_entry(str(action), raw)
            for action, raw in source.items()
            if isinstance(action, str)
            and action in ACTION_SPECS
            and action not in SHARED_ENCODER_CALIBRATION_ACTIONS
        }
        return _apply_device_capability_gates(actions, device, status)

    caps = raw_capabilities if isinstance(raw_capabilities, Mapping) else {}
    physical_gate = (
        str(device.get("model", "unknown")).lower() == "ace1"
        and bool(device.get("physical_actions_enabled", False))
        and bool(caps.get("physical_actions", False))
    )
    connected = bool(device.get("connected", False))
    physical_available = physical_gate and connected
    blocked_reason = ""
    if str(device.get("model", "unknown")).lower() == "ace2":
        blocked_reason = "当前版本中的 ACE2 仅支持读取状态。"
    elif not physical_gate:
        blocked_reason = "ACE 设备的物理动作未启用。"
    elif not connected:
        blocked_reason = "ACE 设备未连接。"

    def physical(name: str, aliases: Sequence[str], confirmation: bool) -> Dict[str, Any]:
        supported = any(bool(caps.get(alias, False)) for alias in aliases)
        available = physical_available and supported
        reason = "" if available else blocked_reason or "当前驱动或设备不支持此操作。"
        return _capability_entry(available, True, name in PRINT_SAFE_ACTIONS, confirmation, reason)

    actions = {
        "refresh": _capability_entry(True, False, True, False),
        "diagnose": _capability_entry(True, False, True, False),
        "select_tool": physical(
            "select_tool", ("physical_actions", "change_tool"), True
        ),
        "unload": physical(
            "unload", ("physical_actions", "retract"), True
        ),
        "feed": physical("feed", ("feed",), True),
        "retract": physical("retract", ("retract",), True),
        "enable_feed_assist": physical(
            "enable_feed_assist", ("enable_feed_assist", "feed_assist"), True
        ),
        "disable_feed_assist": physical(
            "disable_feed_assist", ("disable_feed_assist", "feed_assist"), False
        ),
        "start_drying": physical(
            "start_drying", ("drying", "start_drying"), True
        ),
        "stop_drying": physical(
            "stop_drying", ("drying", "stop_drying"), False
        ),
        "set_slot": _capability_entry(
            bool(caps.get("inventory", True)), False, True, False
        ),
        "calibrate": _capability_entry(
            False, True, False, True, "当前版本尚未实现通用安全校准。"
        ),
        "recover": _capability_entry(
            bool(caps.get("status", True)), False, False, True
        ),
    }
    return _apply_device_capability_gates(actions, device, status)


def _normalized_capability_entry(action: str, raw: Any) -> Dict[str, Any]:
    spec = ACTION_SPECS.get(action)
    default_physical = bool(spec.physical) if spec is not None else True
    default_print_safe = action in PRINT_SAFE_ACTIONS
    default_confirmation = bool(spec.confirmation) if spec is not None else True
    if isinstance(raw, Mapping):
        entry = dict(_json_safe(raw))
        available = bool(
            entry.get(
                "available",
                entry.get("enabled", entry.get("supported", False)),
            )
        )
        physical = bool(entry.get("physical", default_physical))
        allowed_when_printing = bool(
            entry.get(
                "allowed_when_printing",
                entry.get("allowedWhenPrinting", default_print_safe),
            )
        )
        confirmation = bool(
            entry.get(
                "requires_confirmation",
                entry.get("confirmation_required", default_confirmation),
            )
        )
        reason = str(
            entry.get("reason")
            or entry.get("blocked_reason")
            or ("" if available else "当前操作能力不可用。")
        )
        reason = _localize_capability_reason(reason)
        entry.update(
            available=available,
            physical=physical,
            allowed_when_printing=allowed_when_printing,
            requires_confirmation=confirmation,
            confirmation_required=confirmation,
            reason=reason,
        )
        return entry
    return _capability_entry(
        bool(raw),
        default_physical,
        default_print_safe,
        default_confirmation,
        "" if bool(raw) else "当前操作能力不可用。",
    )


def _blocked_capability(value: Mapping, reason: str) -> Dict[str, Any]:
    entry = dict(value)
    reason = _localize_capability_reason(reason)
    entry["available"] = False
    entry["reason"] = reason
    entry["blocked_reason"] = reason
    return entry


def _apply_device_capability_gates(
    actions: Mapping[str, Mapping], device: Mapping, status: Mapping
) -> Dict[str, Any]:
    model = str(device.get("model", "unknown")).lower()
    physical_enabled = bool(device.get("physical_actions_enabled", False))
    connected = bool(device.get("connected", False))
    normalized = {}
    for action, raw in actions.items():
        entry = _normalized_capability_entry(action, raw)
        spec = ACTION_SPECS.get(action)
        is_physical = bool(spec.physical) if spec is not None else True
        if is_physical:
            if model == "ace2":
                entry = _blocked_capability(
                    entry, "当前版本中的 ACE2 仅支持读取状态。"
                )
            elif not physical_enabled:
                entry = _blocked_capability(
                    entry, "ACE 设备的物理动作未启用。"
                )
            elif not connected:
                entry = _blocked_capability(entry, "ACE 设备未连接。")
        if entry.get("available") and action in TOOLCHANGE_ACTIONS:
            if not _toolchange_available(status):
                entry = _blocked_capability(
                    entry, _toolchange_block_message(status)
                )
        normalized[action] = entry
    return normalized


def _capability_entry(
    available: bool,
    physical: bool,
    allowed_when_printing: bool,
    confirmation_required: bool,
    reason: str = "",
) -> Dict[str, Any]:
    reason = _localize_capability_reason(reason)
    return {
        "available": bool(available),
        "physical": bool(physical),
        "allowed_when_printing": bool(allowed_when_printing),
        "requires_confirmation": bool(confirmation_required),
        "confirmation_required": bool(confirmation_required),
        "reason": reason,
    }


def _devices(status: Mapping) -> Dict[str, Mapping]:
    value = status.get("devices", {})
    result = {}
    if isinstance(value, Mapping):
        iterable = value.items()
    elif isinstance(value, list):
        iterable = ((item.get("device_id", item.get("id")), item) for item in value if isinstance(item, Mapping))
    else:
        iterable = ()
    for key, item in iterable:
        if isinstance(key, str) and DEVICE_RE.fullmatch(key) and isinstance(item, Mapping):
            result[key] = item
    return result


def _target_device(target: Mapping, status: Mapping) -> Optional[Mapping]:
    device = target.get("device")
    return _devices(status).get(device) if isinstance(device, str) else None


def _current_tool(status: Mapping) -> Optional[str]:
    candidates = [status.get("current_tool"), status.get("active_tool")]
    system = status.get("system")
    if isinstance(system, Mapping):
        candidates.append(system.get("active_tool"))
    for value in candidates:
        if isinstance(value, str) and TOOL_RE.fullmatch(value):
            return value
    return None


def _path_busy(status: Mapping) -> bool:
    if bool(status.get("path_locked", False)):
        return True
    path_lock = status.get("path_lock")
    if isinstance(path_lock, Mapping) and bool(
        path_lock.get("locked", path_lock.get("active", False))
    ):
        return True
    path = status.get("path")
    if isinstance(path, Mapping) and bool(path.get("busy", False)):
        return True
    for name in ("transaction", "active_transaction", "activity"):
        value = status.get(name)
        if isinstance(value, Mapping) and bool(value.get("active", False)):
            return True
    return False


def _shared_encoder_status(status: Mapping) -> Optional[Mapping]:
    path = status.get("path")
    if not isinstance(path, Mapping):
        return None
    encoders = path.get("encoders")
    if not isinstance(encoders, Mapping):
        return None
    shared = encoders.get("shared")
    return shared if isinstance(shared, Mapping) else None


def _encoder_calibration_route_capability(status: Mapping) -> Tuple[bool, str]:
    if _path_busy(status):
        return False, "共享耗材路径正忙。"
    if _current_tool(status) is not None:
        return False, "编码器校准前必须先卸载当前工具通道。"

    feed_assist = status.get("feed_assist")
    feed_assist_active = bool(feed_assist) if isinstance(feed_assist, bool) else False
    if isinstance(feed_assist, Mapping):
        feed_assist_active = bool(
            feed_assist.get("enabled", feed_assist.get("active", False))
        ) or feed_assist.get("tool") not in (None, "")
    if feed_assist_active:
        return False, "编码器校准前必须关闭辅助送料。"

    path = status.get("path")
    path_state = path.get("state") if isinstance(path, Mapping) else None
    if str(path_state or "unknown").strip().lower() != "empty":
        return False, "编码器校准要求耗材路径为空。"
    return True, ""


def _encoder_calibration_capability(
    action: str, status: Mapping
) -> Tuple[bool, str]:
    shared = _shared_encoder_status(status)
    if shared is None or not bool(shared.get("configured", False)):
        return False, "共享耗材编码器未配置。"

    calibration_active = bool(shared.get("calibration_active", False))
    if action == "encoder_calibration_start":
        if calibration_active:
            return False, "共享耗材编码器校准正在进行。"
        return _encoder_calibration_route_capability(status)

    if not calibration_active:
        return False, "共享耗材编码器校准尚未开始。"
    if (
        action == "encoder_calibration_finish"
        and not bool(shared.get("available", False))
    ):
        return (
            False,
            "共享耗材编码器当前不可用，无法完成校准。",
        )
    if action == "encoder_calibration_finish":
        return _encoder_calibration_route_capability(status)
    return True, ""


def _action_capability(
    action: str, status: Mapping, device: Optional[Mapping]
) -> Tuple[bool, str]:
    aliases = CAPABILITY_ALIASES.get(action, (action,))
    for source in (status.get("actions"), status.get("capabilities"), (device or {}).get("capabilities")):
        decision = _capability_decision(source, aliases)
        if decision is not None:
            return decision
    return False, "驱动未声明此操作能力。"


def _capability_decision(source: Any, aliases: Sequence[str]) -> Optional[Tuple[bool, str]]:
    if isinstance(source, (list, tuple, set, frozenset)):
        available = any(alias in source for alias in aliases)
        return available, "" if available else "当前驱动或设备不支持此操作。"
    if not isinstance(source, Mapping):
        return None
    actions = source.get("actions")
    if isinstance(actions, Mapping):
        nested = _capability_decision(actions, aliases)
        if nested is not None:
            return nested
    for alias in aliases:
        if alias not in source:
            continue
        value = source[alias]
        if isinstance(value, Mapping):
            available = bool(value.get("available", value.get("enabled", value.get("supported", False))))
            reason = str(value.get("reason") or ("" if available else "当前操作能力不可用。"))
            return available, _localize_capability_reason(reason)
        return bool(value), "" if bool(value) else "当前操作能力不可用。"
    return None


def _cached_diagnostic(status: Mapping, target: Mapping) -> Dict[str, Any]:
    device_id = target.get("device")
    device = _devices(status).get(device_id, {})
    diagnostic = {
        "device": device_id,
        "slot": target.get("slot"),
        "connected": bool(device.get("connected", False)),
        "model": device.get("model", "unknown"),
        "state": device.get("state", "unknown"),
        "error": device.get("error", device.get("last_error")),
    }
    slot = target.get("slot")
    slots = device.get("slots")
    if isinstance(slot, int) and isinstance(slots, list) and slot < len(slots):
        diagnostic["slot_status"] = _json_safe(slots[slot])
    return diagnostic


def _sample_target_params(action: str, status: Mapping) -> Dict[str, Any]:
    devices = _devices(status)
    device = next(iter(devices), "ace0")
    samples = {
        "select_tool": {"tool": "T0"},
        "unload": {},
        "feed": {"device": device, "slot": 0, "length": 1, "speed": 1},
        "retract": {"device": device, "slot": 0, "length": 1, "speed": 1},
        "enable_feed_assist": {"device": device, "slot": 0},
        "disable_feed_assist": {"device": device, "slot": 0},
        "start_drying": {"device": device, "temperature": 40, "duration": 60},
        "stop_drying": {"device": device},
        "set_slot": {"device": device, "slot": 0},
        "set_endless_spool": {"enabled": False},
        "encoder_calibration_start": {},
        "encoder_calibration_finish": {"length": 100},
        "encoder_calibration_cancel": {},
        "calibrate": {"device": device, "mode": "probe"},
        "recover": {"device": device},
        "refresh": {"device": device},
        "diagnose": {"device": device},
    }
    return samples[action]


def _device_id(value: Any) -> str:
    if not isinstance(value, str) or not DEVICE_RE.fullmatch(value):
        raise RequestRejected("invalid_device", "device 必须是 ace0 到 ace3。")
    return value


def _tool(value: Any) -> str:
    if not isinstance(value, str) or not TOOL_RE.fullmatch(value):
        raise RequestRejected("invalid_tool", "tool 必须是 T0 到 T15。")
    return value


def _integer(value: Any, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RequestRejected(
            "invalid_parameter", "%s 超出允许范围。" % name
        )
    return value


def _number(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
        raise RequestRejected(
            "invalid_parameter", "%s 超出允许范围。" % name
        )
    return float(value)


def _safe_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise RequestRejected(
            "invalid_parameter", "%s 必须是长度符合要求的字符串。" % name
        )
    if any(char in value for char in ("\r", "\n", "\x00")):
        raise RequestRejected(
            "invalid_parameter", "%s 包含不安全字符。" % name
        )
    return value


def _request_id(web_request: Any) -> str:
    for name in ("get_request_id", "get_id"):
        getter = getattr(web_request, name, None)
        if callable(getter):
            value = getter()
            if value is not None and str(value).strip():
                return str(value)
    return "ace-v3-%s" % uuid4()


def _success(
    request_id: str, action: str, result: Mapping
) -> Dict[str, Any]:
    return {
        "ok": True,
        "api_version": API_VERSION,
        "request_id": request_id,
        "action": action,
        "state": "completed",
        "retryable": False,
        "result": _json_safe(result),
    }


def _failure_from_rejection(
    request_id: str, action: str, exc: RequestRejected
) -> Dict[str, Any]:
    return _failure(
        request_id,
        action,
        exc.code,
        exc.message,
        retryable=exc.retryable,
        details=exc.details,
    )


def _failure(
    request_id: str,
    action: str,
    code: str,
    message: str,
    *,
    retryable: bool,
    details: Optional[Mapping] = None,
) -> Dict[str, Any]:
    message = _localize_user_text(
        message,
        code=code,
        fallback="ACE 请求未能完成，请检查配置和诊断信息。",
    )
    next_action = _error_next_action(code, retryable)
    return {
        "ok": False,
        "api_version": API_VERSION,
        "request_id": request_id,
        "action": action,
        "state": "rejected" if code != "execution_failed" else "failed",
        "retryable": retryable,
        "error": {
            "code": code,
            "message": message,
            "reason": message,
            "next_action": next_action,
            "retryable": retryable,
            "source": "moonraker",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": _json_safe(details or {}),
        },
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


def load_component(config: Any) -> AceStatus:
    """Moonraker component loader."""

    return AceStatus(config)


__all__ = (
    "ACTION_SPECS",
    "AceStatus",
    "RequestRejected",
    "load_component",
)
