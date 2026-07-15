from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, Mapping, Optional

MATERIAL_RE = re.compile(r"^[A-Za-z0-9._+-]{1,24}$")
DEFAULT_UPPER_SENSOR = "extruder_sensor"
DEFAULT_LOWER_SENSOR = "toolhead_sensor"


class AceRequestError(ValueError):
    def __init__(self, code: str, message: str, field: str = "", status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.status_code = status_code

    def to_dict(self) -> Dict[str, Any]:
        error = {"code": self.code, "message": self.message}
        if self.field:
            error["field"] = self.field
        return error


def _is_mapping(value: Any) -> bool:
    return isinstance(value, Mapping)


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if _is_mapping(value) else {}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
    return default


def _first_value(mapping: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return default


def _normalize_dryer(value: Any) -> Dict[str, Any]:
    dryer = _as_dict(value)
    raw_status = str(_first_value(dryer, "status", "state", "mode", default="stop") or "stop").lower()
    status = {
        "idle": "stop",
        "off": "stop",
        "stopped": "stop",
        "running": "drying",
        "active": "drying",
        "start": "drying",
    }.get(raw_status, raw_status)
    target = _safe_int(_first_value(dryer, "target_temp", "target_temperature", "temperature", default=0))
    duration = _safe_int(_first_value(dryer, "duration", "duration_minutes", default=0))
    remaining = _safe_int(_first_value(
        dryer,
        "remain_time",
        "remaining_minutes",
        "remaining_time",
        default=0,
    ))
    if duration > 0 and remaining > duration * 1.5 and remaining > 60:
        remaining = round(remaining / 60)
    if status == "stop" and remaining > 0:
        status = "drying"
    return {
        "active": status != "stop",
        "status": status,
        "target_temperature": target,
        "duration_minutes": duration,
        "remaining_minutes": remaining,
    }


def _parse_inventory(value: Any) -> list[Dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if not isinstance(value, list):
        value = []
    slots: list[Dict[str, Any]] = []
    for index in range(4):
        raw = _as_dict(value[index] if index < len(value) else {})
        color = raw.get("color", [0, 0, 0])
        if not isinstance(color, list) or len(color) != 3:
            color = [0, 0, 0]
        rgb = [max(0, min(255, _safe_int(channel))) for channel in color]
        slots.append({
            "index": index,
            "status": str(raw.get("status") or "empty"),
            "material": str(raw.get("material") or ""),
            "color": {"rgb": rgb, "hex": "#{:02X}{:02X}{:02X}".format(*rgb)},
            "temperature": _safe_int(raw.get("temp")),
            "loaded": False,
            "active": False,
        })
    return slots


def _sensor_state(sensor: Mapping[str, Any], name: str) -> Dict[str, Any]:
    available = bool(sensor)
    detected = _safe_bool(sensor.get("filament_detected"), False) if available else False
    return {"name": name, "available": available, "detected": detected}


def normalize_status(
    ace: Mapping[str, Any],
    variables: Mapping[str, Any],
    upper: Mapping[str, Any],
    lower: Mapping[str, Any],
    printing: bool = False,
    upper_name: str = DEFAULT_UPPER_SENSOR,
    lower_name: str = DEFAULT_LOWER_SENSOR,
) -> Dict[str, Any]:
    ace = _as_dict(ace)
    variables = _as_dict(variables)
    dryer = _normalize_dryer(_first_value(ace, "dryer", "dryer_status", default={}))
    endless = _as_dict(ace.get("endless_spool"))
    current_tool = _safe_int(variables.get("ace_current_index"), -1)
    slots = _parse_inventory(variables.get("ace_inventory"))

    hardware_slots = ace.get("slots")
    if isinstance(hardware_slots, list):
        for slot in slots:
            raw = _as_dict(hardware_slots[slot["index"]] if slot["index"] < len(hardware_slots) else {})
            if not slot["material"]:
                slot["material"] = str(raw.get("type") or "")
            if slot["status"] == "empty" and raw.get("status"):
                slot["status"] = str(raw.get("status"))
    for slot in slots:
        slot["loaded"] = current_tool == slot["index"]
        slot["active"] = slot["loaded"]

    connected = _safe_bool(ace.get("connected"), bool(ace))
    return {
        "api_version": 1,
        "driver": "ACEPROSV08",
        "connected": connected,
        "status": str(ace.get("status") or ("ready" if connected else "offline")),
        "busy": str(ace.get("status") or "").lower() == "busy",
        "stale": False,
        "current_tool": current_tool,
        "temperature": _safe_float(ace.get("temp")),
        "fan_speed": _safe_int(ace.get("fan_speed")),
        "feed_assist_index": _safe_int(ace.get("feed_assist_index"), -1),
        "dryer": dryer,
        "sensors": {
            "upper": _sensor_state(upper, upper_name),
            "lower": _sensor_state(lower, lower_name),
        },
        "endless_spool": {
            "enabled": _safe_bool(endless.get("enabled"), _safe_bool(variables.get("ace_endless_spool_enabled"))),
            "runout_detected": _safe_bool(endless.get("runout_detected")),
            "in_progress": _safe_bool(endless.get("in_progress")),
        },
        "printing": bool(printing),
        "slots": slots,
        "max_dryer_temperature": _safe_int(ace.get("max_dryer_temperature"), 65),
        "warnings": [],
    }


def _require_int(params: Mapping[str, Any], key: str, minimum: int, maximum: int) -> int:
    if key not in params:
        raise AceRequestError("missing_parameter", f"缺少参数 {key}", f"params.{key}")
    value = _safe_int(params.get(key), minimum - 1)
    if value < minimum or value > maximum:
        raise AceRequestError("invalid_parameter", f"{key} 必须在 {minimum} 到 {maximum} 之间", f"params.{key}")
    return value


def _reject_unknown(params: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise AceRequestError("invalid_parameter", f"不支持的参数: {', '.join(unknown)}", f"params.{unknown[0]}")


def _build_set_slot(params: Mapping[str, Any], max_dryer_temperature: int = 65) -> str:
    _reject_unknown(params, {"INDEX", "EMPTY", "COLOR", "MATERIAL", "TEMP"})
    index = _require_int(params, "INDEX", 0, 3)
    if _safe_bool(params.get("EMPTY")):
        return f"ACE_SET_SLOT INDEX={index} EMPTY=1"
    material = str(params.get("MATERIAL") or "").strip().upper()
    if not MATERIAL_RE.match(material):
        raise AceRequestError("invalid_parameter", "材料名称只能包含字母、数字、点、下划线、加号和减号", "params.MATERIAL")
    temp = _require_int(params, "TEMP", 1, 500)
    color = params.get("COLOR")
    if isinstance(color, str):
        parts = color.split(",")
    elif isinstance(color, list):
        parts = color
    else:
        raise AceRequestError("invalid_parameter", "颜色必须是 RGB 数组或逗号分隔值", "params.COLOR")
    if len(parts) != 3:
        raise AceRequestError("invalid_parameter", "颜色必须包含 3 个通道", "params.COLOR")
    rgb = [_safe_int(part, -1) for part in parts]
    if any(channel < 0 or channel > 255 for channel in rgb):
        raise AceRequestError("invalid_parameter", "颜色通道必须在 0 到 255 之间", "params.COLOR")
    return f"ACE_SET_SLOT INDEX={index} MATERIAL={material} COLOR={rgb[0]},{rgb[1]},{rgb[2]} TEMP={temp}"


def _build_change_tool(params: Mapping[str, Any], max_dryer_temperature: int = 65) -> str:
    _reject_unknown(params, {"TOOL"})
    return f"ACE_CHANGE_TOOL TOOL={_require_int(params, 'TOOL', -1, 3)}"


def _build_index_command(command: str) -> Callable[[Mapping[str, Any], int], str]:
    def builder(params: Mapping[str, Any], max_dryer_temperature: int = 65) -> str:
        _reject_unknown(params, {"INDEX"})
        return f"{command} INDEX={_require_int(params, 'INDEX', 0, 3)}"
    return builder


def _build_move(command: str) -> Callable[[Mapping[str, Any], int], str]:
    def builder(params: Mapping[str, Any], max_dryer_temperature: int = 65) -> str:
        _reject_unknown(params, {"INDEX", "LENGTH", "SPEED"})
        index = _require_int(params, "INDEX", 0, 3)
        length = _require_int(params, "LENGTH", 1, 500)
        speed = _require_int(params, "SPEED", 1, 120)
        return f"{command} INDEX={index} LENGTH={length} SPEED={speed}"
    return builder


def _build_drying(params: Mapping[str, Any], max_dryer_temperature: int = 65) -> str:
    _reject_unknown(params, {"TEMP", "DURATION"})
    temp = _require_int(params, "TEMP", 1, max_dryer_temperature)
    duration = _require_int(params, "DURATION", 1, 1440)
    return f"ACE_START_DRYING TEMP={temp} DURATION={duration}"


def _build_no_params(command: str) -> Callable[[Mapping[str, Any], int], str]:
    def builder(params: Mapping[str, Any], max_dryer_temperature: int = 65) -> str:
        _reject_unknown(params, set())
        return command
    return builder


COMMAND_BUILDERS: Dict[str, Callable[[Mapping[str, Any], int], str]] = {
    "ACE_SET_SLOT": _build_set_slot,
    "ACE_CHANGE_TOOL": _build_change_tool,
    "ACE_CHANGE_SPOOL": _build_index_command("ACE_CHANGE_SPOOL"),
    "ACE_FEED": _build_move("ACE_FEED"),
    "ACE_RETRACT": _build_move("ACE_RETRACT"),
    "ACE_ENABLE_FEED_ASSIST": _build_index_command("ACE_ENABLE_FEED_ASSIST"),
    "ACE_DISABLE_FEED_ASSIST": _build_index_command("ACE_DISABLE_FEED_ASSIST"),
    "ACE_START_DRYING": _build_drying,
    "ACE_STOP_DRYING": _build_no_params("ACE_STOP_DRYING"),
    "ACE_ENABLE_ENDLESS_SPOOL": _build_no_params("ACE_ENABLE_ENDLESS_SPOOL"),
    "ACE_DISABLE_ENDLESS_SPOOL": _build_no_params("ACE_DISABLE_ENDLESS_SPOOL"),
    "ACE_SAVE_INVENTORY": _build_no_params("ACE_SAVE_INVENTORY"),
    "ACE_QUERY_SLOTS": _build_no_params("ACE_QUERY_SLOTS"),
    "ACE_GET_CURRENT_INDEX": _build_no_params("ACE_GET_CURRENT_INDEX"),
    "ACE_TEST_RUNOUT_SENSOR": _build_no_params("ACE_TEST_RUNOUT_SENSOR"),
}


def build_gcode(payload: Mapping[str, Any], printing: bool = False, connected: bool = True, max_dryer_temperature: int = 65) -> str:
    command = str(payload.get("command") or "").strip().upper()
    params = payload.get("params") or {}
    if not _is_mapping(params):
        raise AceRequestError("invalid_request", "params 必须是对象", "params")
    if command not in COMMAND_BUILDERS:
        raise AceRequestError("unsupported_command", f"不支持的 ACE 命令: {command}", "command")
    if not connected and command not in {"ACE_QUERY_SLOTS", "ACE_GET_CURRENT_INDEX", "ACE_TEST_RUNOUT_SENSOR"}:
        raise AceRequestError("driver_offline", "ACEPROSV08 未连接", status_code=503)
    write_commands = {
        "ACE_SET_SLOT", "ACE_CHANGE_TOOL", "ACE_CHANGE_SPOOL", "ACE_FEED", "ACE_RETRACT",
        "ACE_ENABLE_FEED_ASSIST", "ACE_START_DRYING", "ACE_ENABLE_ENDLESS_SPOOL",
    }
    if printing and command in write_commands:
        raise AceRequestError("printer_busy", "打印中不允许执行该操作", status_code=409)
    return COMMAND_BUILDERS[command](dict(params), max_dryer_temperature)


class AceStatus:
    def __init__(self, config: Any):
        self.server = config.get_server()
        self.logger = logging.getLogger(__name__)
        self.klippy_apis = self.server.lookup_component("klippy_apis")
        self.upper_sensor_name = config.get("upper_sensor_name", DEFAULT_UPPER_SENSOR)
        self.lower_sensor_name = config.get("lower_sensor_name", DEFAULT_LOWER_SENSOR)
        self._last_status: Optional[Dict[str, Any]] = None

        self.server.register_endpoint("/server/ace/status", ["GET"], self.handle_status_request)
        self.server.register_endpoint("/server/ace/slots", ["GET"], self.handle_slots_request)
        self.server.register_endpoint("/server/ace/capabilities", ["GET"], self.handle_capabilities_request)
        self.server.register_endpoint("/server/ace/command", ["POST"], self.handle_command_request)
        self.logger.info("ACEPROSV08 status API loaded")

    async def _query(self) -> Dict[str, Any]:
        objects = {
            "ace": None,
            "save_variables": None,
            f"filament_switch_sensor {self.upper_sensor_name}": None,
            f"filament_switch_sensor {self.lower_sensor_name}": None,
            "print_stats": None,
            "idle_timeout": None,
        }
        data = await self.klippy_apis.query_objects(objects)
        if "status" in data and isinstance(data["status"], dict):
            data = data["status"]
        return data if isinstance(data, dict) else {}

    def _normalize_from_query(self, data: Mapping[str, Any]) -> Dict[str, Any]:
        variables = _as_dict(_as_dict(data.get("save_variables")).get("variables"))
        upper = _as_dict(data.get(f"filament_switch_sensor {self.upper_sensor_name}"))
        lower = _as_dict(data.get(f"filament_switch_sensor {self.lower_sensor_name}"))
        print_stats = _as_dict(data.get("print_stats"))
        idle_timeout = _as_dict(data.get("idle_timeout"))
        printing = str(print_stats.get("state") or "").lower() == "printing" or str(idle_timeout.get("state") or "").lower() == "printing"
        return normalize_status(
            _as_dict(data.get("ace")),
            variables,
            upper,
            lower,
            printing,
            self.upper_sensor_name,
            self.lower_sensor_name,
        )

    async def handle_status_request(self, webrequest: Any) -> Dict[str, Any]:
        try:
            status = self._normalize_from_query(await self._query())
            self._last_status = status
            return status
        except Exception as exc:
            self.logger.warning("ACE status query failed: %s", exc)
            if self._last_status:
                stale = dict(self._last_status)
                stale["stale"] = True
                stale["warnings"] = ["Klipper 状态读取失败，正在显示缓存数据"]
                return stale
            return normalize_status({}, {}, {}, {}, False, self.upper_sensor_name, self.lower_sensor_name)

    async def handle_slots_request(self, webrequest: Any) -> Dict[str, Any]:
        status = await self.handle_status_request(webrequest)
        return {"api_version": 1, "slots": status.get("slots", []), "warnings": status.get("warnings", [])}

    async def handle_capabilities_request(self, webrequest: Any) -> Dict[str, Any]:
        status = await self.handle_status_request(webrequest)
        return {
            "api_version": 1,
            "driver": "ACEPROSV08",
            "single_device": True,
            "slots": 4,
            "max_dryer_temperature": status.get("max_dryer_temperature", 65),
            "sensors": status.get("sensors", {}),
            "commands": sorted(COMMAND_BUILDERS),
            "warnings": status.get("warnings", []),
        }

    async def handle_command_request(self, webrequest: Any) -> Dict[str, Any]:
        try:
            payload = webrequest.get_args()
            if not isinstance(payload, dict):
                raise AceRequestError("invalid_request", "请求体必须是 JSON 对象")
            status = await self.handle_status_request(webrequest)
            gcode = build_gcode(
                payload,
                printing=bool(status.get("printing")),
                connected=bool(status.get("connected")),
                max_dryer_temperature=_safe_int(status.get("max_dryer_temperature"), 65),
            )
            await self.klippy_apis.run_gcode(gcode)
            return {"success": True, "command": payload.get("command"), "request_id": f"ace-{int(time.time() * 1000)}"}
        except AceRequestError as exc:
            return {"success": False, "error": exc.to_dict()}
        except Exception as exc:
            self.logger.error("ACE command failed: %s", exc, exc_info=True)
            return {"success": False, "error": {"code": "server_error", "message": str(exc)}}


def load_component(config: Any) -> AceStatus:
    return AceStatus(config)
