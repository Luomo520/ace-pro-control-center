"""Configuration parsing and validation for Ace Pro Control Center.

``parse_config`` accepts either Klipper's config wrapper or a plain mapping.
The plain mapping form mirrors Klipper section names and is intentionally kept
as a first-class entry point for tests, installers, and diagnostics.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .errors import AceConfigError
from .models import CapabilitySet, DeviceModel
from .tool_map import MAX_DEVICES, ToolMap


DRIVER_VERSION = 3
TOPOLOGY_MODE = "configured"
TOOLCHANGE_MODES = {"manual", "automatic"}
ENCODER_MODES = {"off", "monitor", "protect"}
ENCODER_PRINT_MODES = {"off", "monitor", "pause"}
TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX = 250.0
UPPER_SENSOR_FEED_TIMEOUT_MAX = 120.0
FIXED_SENSOR_NAMES = {
    "extruder_sensor_name": "extruder_sensor",
    "toolhead_sensor_name": "toolhead_sensor",
    "rdm_sensor_name": "rdm_sensor",
    "ace0_hub_sensor_name": "ace0_hub_sensor",
    "ace1_hub_sensor_name": "ace1_hub_sensor",
    "ace2_hub_sensor_name": "ace2_hub_sensor",
    "ace3_hub_sensor_name": "ace3_hub_sensor",
    "encoder_sensor_name": "shared_encoder",
}
DEFAULT_MACHINE_MACROS = {
    "pre_toolchange_macro": "_ace_prepare_toolchange",
    "cut_macro": "_ace_cut_filament",
    "load_to_toolhead_macro": "_ace_load_filament_to_toolhead",
    "unload_from_toolhead_macro": "_ace_unload_filament_from_toolhead",
    "wipe_nozzle_macro": "_ace_wipe_nozzle",
    "post_toolchange_macro": "_ace_restore_after_toolchange",
    "pause_on_error_macro": "_ace_pause_on_toolchange_error",
}
DEFAULT_CUT_MACRO = DEFAULT_MACHINE_MACROS["cut_macro"]
_MISSING = object()
_DEVICE_SECTION_RE = re.compile(r"^ace_device (ace[0-3])$")
_MACRO_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_MATERIAL_TYPES: Tuple[str, ...] = (
    "PLA",
    "PLA+",
    "PETG",
    "PETG-CF",
    "PETCF",
    "ABS",
    "ABSCF",
    "ASA",
    "TPU",
    "PA",
    "PA-CF",
    "PAHTCF",
    "PET-CF",
    "PC",
    "PBT-CF",
    "PEEK",
    "PVA",
    "HIPS",
)


class ConfigError(AceConfigError):
    """Raised when the driver cannot establish an unambiguous safe topology."""


@dataclass(frozen=True)
class SharedConfig:
    driver_version: int = DRIVER_VERSION
    toolchange_mode: str = "manual"
    material_types: Tuple[str, ...] = DEFAULT_MATERIAL_TYPES
    extruder_sensor_name: Optional[str] = None
    toolhead_sensor_name: Optional[str] = None
    rdm_sensor_name: Optional[str] = None
    ace0_hub_sensor_name: Optional[str] = None
    ace1_hub_sensor_name: Optional[str] = None
    ace2_hub_sensor_name: Optional[str] = None
    ace3_hub_sensor_name: Optional[str] = None
    extruder_sensor_pin: Optional[str] = None
    toolhead_sensor_pin: Optional[str] = None
    toolhead_sensor_bypass: bool = True
    toolhead_sensor_bypass_calibrated: bool = False
    rdm_sensor_pin: Optional[str] = None
    ace0_hub_sensor_pin: Optional[str] = None
    ace1_hub_sensor_pin: Optional[str] = None
    ace2_hub_sensor_pin: Optional[str] = None
    ace3_hub_sensor_pin: Optional[str] = None
    extruder_sensor_debounce_count: int = 2
    toolhead_sensor_debounce_count: int = 2
    rdm_sensor_debounce_count: int = 3
    ace_hub_sensor_debounce_count: int = 3
    encoder_sensor_name: Optional[str] = None
    encoder_sensor_pin: Optional[str] = None
    encoder_resolution: float = 0.0
    encoder_detection_length: float = 20.0
    encoder_min_tracking_ratio: float = 0.6
    encoder_mode: str = "off"
    encoder_print_mode: str = "off"
    encoder_print_detection_length: float = 20.0
    feed_speed: float = 80.0
    feed_fast_speed: float = 160.0
    feed_slip_compensation_length: float = 400.0
    feed_slip_compensation_speed: float = 25.0
    retract_speed: float = 80.0
    retract_fast_speed: float = 120.0
    retract_parking_speed: float = 25.0
    retract_parking_length: float = 200.0
    toolchange_load_length: float = 630.0
    upper_sensor_feed_timeout: float = 30.0
    toolchange_retract_length: float = 150.0
    bowden_tube_length: float = 1000.0
    toolhead_sensor_to_nozzle: float = 50.0
    toolhead_sensor_bypass_load_length: float = 25.0
    toolhead_feed_fast_speed: float = 10.0
    toolhead_feed_slow_speed: float = 5.0
    toolhead_feed_fast_length: float = 10.0
    toolhead_feed_fast_step: float = 5.0
    toolhead_feed_slow_step: float = 1.0
    toolhead_to_nozzle_speed: float = 8.0
    toolhead_sensor_max_feed_length: float = 200.0
    toolhead_unload_step_length: float = 50.0
    toolhead_unload_speed: float = 10.0
    toolhead_unload_max_attempts: int = 10
    ace_unload_step_length: float = 100.0
    rdm_clear_move_length: float = 100.0
    ace0_hub_retract_length: float = 0.0
    ace1_hub_retract_length: float = 0.0
    ace2_hub_retract_length: float = 0.0
    ace3_hub_retract_length: float = 0.0
    ace0_hub_clear_move_length: float = 0.0
    ace1_hub_clear_move_length: float = 0.0
    ace2_hub_clear_move_length: float = 0.0
    ace3_hub_clear_move_length: float = 0.0
    sensor_trigger_grace_time: float = 3.0
    max_dryer_temperature: float = 55.0
    endless_spool: bool = False
    endless_spool_match_mode: str = "exact"
    connection_supervision: bool = True
    require_path_hooks: bool = True
    require_cut_hook: bool = True

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "driver_version": self.driver_version,
            "toolchange_mode": self.toolchange_mode,
            "material_types": list(self.material_types),
            "extruder_sensor_name": self.extruder_sensor_name,
            "toolhead_sensor_name": self.toolhead_sensor_name,
            "rdm_sensor_name": self.rdm_sensor_name,
            "extruder_sensor_pin": self.extruder_sensor_pin,
            "toolhead_sensor_pin": self.toolhead_sensor_pin,
            "toolhead_sensor_bypass": self.toolhead_sensor_bypass,
            "toolhead_sensor_bypass_calibrated": self.toolhead_sensor_bypass_calibrated,
            "rdm_sensor_pin": self.rdm_sensor_pin,
            "extruder_sensor_debounce_count": self.extruder_sensor_debounce_count,
            "toolhead_sensor_debounce_count": self.toolhead_sensor_debounce_count,
            "rdm_sensor_debounce_count": self.rdm_sensor_debounce_count,
            "ace_hub_sensor_debounce_count": self.ace_hub_sensor_debounce_count,
            "encoder_sensor_name": self.encoder_sensor_name,
            "encoder_sensor_pin": self.encoder_sensor_pin,
            "encoder_resolution": self.encoder_resolution,
            "encoder_detection_length": self.encoder_detection_length,
            "encoder_min_tracking_ratio": self.encoder_min_tracking_ratio,
            "encoder_mode": self.encoder_mode,
            "encoder_print_mode": self.encoder_print_mode,
            "encoder_print_detection_length": self.encoder_print_detection_length,
            "feed_speed": self.feed_speed,
            "feed_fast_speed": self.feed_fast_speed,
            "feed_slip_compensation_length": self.feed_slip_compensation_length,
            "feed_slip_compensation_speed": self.feed_slip_compensation_speed,
            "retract_speed": self.retract_speed,
            "retract_fast_speed": self.retract_fast_speed,
            "retract_parking_speed": self.retract_parking_speed,
            "retract_parking_length": self.retract_parking_length,
            "toolchange_load_length": self.toolchange_load_length,
            "upper_sensor_feed_timeout": self.upper_sensor_feed_timeout,
            "toolchange_retract_length": self.toolchange_retract_length,
            "bowden_tube_length": self.bowden_tube_length,
            "toolhead_sensor_to_nozzle": self.toolhead_sensor_to_nozzle,
            "toolhead_sensor_bypass_load_length": self.toolhead_sensor_bypass_load_length,
            "toolhead_feed_fast_speed": self.toolhead_feed_fast_speed,
            "toolhead_feed_slow_speed": self.toolhead_feed_slow_speed,
            "toolhead_feed_fast_length": self.toolhead_feed_fast_length,
            "toolhead_feed_fast_step": self.toolhead_feed_fast_step,
            "toolhead_feed_slow_step": self.toolhead_feed_slow_step,
            "toolhead_to_nozzle_speed": self.toolhead_to_nozzle_speed,
            "toolhead_sensor_max_feed_length": self.toolhead_sensor_max_feed_length,
            "toolhead_unload_step_length": self.toolhead_unload_step_length,
            "toolhead_unload_speed": self.toolhead_unload_speed,
            "toolhead_unload_max_attempts": self.toolhead_unload_max_attempts,
            "ace_unload_step_length": self.ace_unload_step_length,
            "rdm_clear_move_length": self.rdm_clear_move_length,
            "sensor_trigger_grace_time": self.sensor_trigger_grace_time,
            "max_dryer_temperature": self.max_dryer_temperature,
            "endless_spool": self.endless_spool,
            "endless_spool_match_mode": self.endless_spool_match_mode,
            "connection_supervision": self.connection_supervision,
            "require_path_hooks": self.require_path_hooks,
            "require_cut_hook": self.require_cut_hook,
        }
        for index in range(MAX_DEVICES):
            prefix = "ace%d_hub" % index
            result[prefix + "_sensor_name"] = getattr(
                self, prefix + "_sensor_name"
            )
            result[prefix + "_sensor_pin"] = getattr(
                self, prefix + "_sensor_pin"
            )
            result[prefix + "_retract_length"] = getattr(
                self, prefix + "_retract_length"
            )
            result[prefix + "_clear_move_length"] = getattr(
                self, prefix + "_clear_move_length"
            )
        return result


@dataclass(frozen=True)
class MachineConfig:
    pre_toolchange_macro: Optional[str] = None
    cut_macro: Optional[str] = None
    load_to_toolhead_macro: Optional[str] = None
    unload_from_toolhead_macro: Optional[str] = None
    wipe_nozzle_macro: Optional[str] = None
    post_toolchange_macro: Optional[str] = None
    pause_on_error_macro: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pre_toolchange_macro": self.pre_toolchange_macro,
            "cut_macro": self.cut_macro,
            "load_to_toolhead_macro": self.load_to_toolhead_macro,
            "unload_from_toolhead_macro": self.unload_from_toolhead_macro,
            "wipe_nozzle_macro": self.wipe_nozzle_macro,
            "post_toolchange_macro": self.post_toolchange_macro,
            "pause_on_error_macro": self.pause_on_error_macro,
        }


@dataclass(frozen=True)
class DeviceConfig:
    device_id: str
    model: str
    serial: str
    enabled: bool = True
    rfid_enabled: bool = True
    physical_actions_enabled: bool = False
    bus_id: Optional[str] = None
    device_uid: Optional[str] = None
    transport: str = "serial"
    index: int = 0

    @property
    def capabilities(self) -> CapabilitySet:
        return CapabilitySet.for_device(
            DeviceModel(self.model),
            physical_actions_enabled=self.physical_actions_enabled,
            enabled=self.enabled,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "index": self.index,
            "model": self.model,
            "transport": self.transport,
            "serial": self.serial,
            "enabled": self.enabled,
            "rfid_enabled": self.rfid_enabled,
            "physical_actions_enabled": self.physical_actions_enabled,
            "bus_id": self.bus_id,
            "device_uid": self.device_uid,
            "capabilities": self.capabilities.to_dict(),
        }


@dataclass(frozen=True)
class DriverConfig:
    devices: Tuple[DeviceConfig, ...]
    shared: SharedConfig
    machine: MachineConfig
    topology_mode: str = TOPOLOGY_MODE
    driver_version: int = DRIVER_VERSION
    tool_map: ToolMap = field(init=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_map", ToolMap(len(self.devices)))

    @property
    def device_count(self) -> int:
        return len(self.devices)

    def device(self, device_id: str) -> DeviceConfig:
        for item in self.devices:
            if item.device_id == device_id:
                return item
        raise KeyError(device_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "driver_version": self.driver_version,
            "topology_mode": self.topology_mode,
            "shared": self.shared.to_dict(),
            "machine": self.machine.to_dict(),
            "devices": [device.to_dict() for device in self.devices],
            "tool_map": self.tool_map.to_dict(),
        }


def _fail(message: str) -> ConfigError:
    return ConfigError(message)


def _get(section: Any, key: str, default: Any = _MISSING) -> Any:
    if isinstance(section, Mapping):
        if key in section:
            return section[key]
        if default is not _MISSING:
            return default
        raise _fail("missing required option '%s'" % key)
    getter = getattr(section, "get", None)
    if getter is None:
        raise _fail("configuration section does not support get()")
    try:
        if default is _MISSING:
            value = getter(key, None)
            if value is None:
                raise _fail("missing required option '%s'" % key)
            return value
        return getter(key, default)
    except ConfigError:
        raise
    except Exception as exc:
        raise _fail("unable to read option '%s': %s" % (key, exc))


def _string(section: Any, key: str, default: Any = _MISSING) -> str:
    value = _get(section, key, default)
    if value is None:
        return ""
    return str(value).strip()


def _optional_string(section: Any, key: str) -> Optional[str]:
    value = _string(section, key, "")
    return value or None


def _material_types(section: Any) -> Tuple[str, ...]:
    value = _get(section, "material_types", ", ".join(DEFAULT_MATERIAL_TYPES))
    if not isinstance(value, str):
        raise _fail("option 'material_types' must be a comma-separated string")
    if not value.strip():
        raise _fail("option 'material_types' must contain at least 1 item")

    raw_items = value.split(",")
    if len(raw_items) > 32:
        raise _fail("option 'material_types' must contain at most 32 items")

    items: List[str] = []
    normalized_items = set()
    for index, raw_item in enumerate(raw_items, start=1):
        if any(unicodedata.category(character) == "Cc" for character in raw_item):
            raise _fail(
                "option 'material_types' item %d contains control characters" % index
            )
        item = raw_item.strip()
        if not item:
            raise _fail("option 'material_types' item %d must not be empty" % index)
        if len(item) > 32:
            raise _fail(
                "option 'material_types' item %d must be at most 32 characters" % index
            )
        normalized = item.casefold()
        if normalized in normalized_items:
            raise _fail(
                "option 'material_types' contains duplicate item '%s' "
                "(case-insensitive)" % item
            )
        normalized_items.add(normalized)
        items.append(item)
    return tuple(items)


def _integer(section: Any, key: str, default: Any = _MISSING) -> int:
    value = _get(section, key, default)
    if isinstance(value, bool):
        raise _fail("option '%s' must be an integer" % key)
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise _fail("option '%s' must be an integer" % key) from exc
    return parsed


def _number(section: Any, key: str, default: Any = _MISSING) -> float:
    value = _get(section, key, default)
    if isinstance(value, bool):
        raise _fail("option '%s' must be a number" % key)
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise _fail("option '%s' must be a number" % key) from exc
    if not math.isfinite(parsed):
        raise _fail("option '%s' must be a finite number" % key)
    return parsed


def _boolean(section: Any, key: str, default: Any = _MISSING) -> bool:
    value = _get(section, key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in ("1", "true", "yes", "on"):
        return True
    if normalized in ("0", "false", "no", "off"):
        return False
    raise _fail("option '%s' must be a boolean" % key)


def _validate_range(name: str, value: float, minimum: float, maximum: Optional[float] = None) -> float:
    if value < minimum or (maximum is not None and value > maximum):
        if maximum is None:
            raise _fail("option '%s' must be at least %s" % (name, minimum))
        raise _fail("option '%s' must be between %s and %s" % (name, minimum, maximum))
    return value


def _section_name(section: Any) -> Optional[str]:
    if isinstance(section, Mapping):
        value = section.get("__name__")
        return str(value).strip() if value else None
    getter = getattr(section, "get_name", None)
    if getter is None:
        return None
    try:
        return str(getter()).strip()
    except Exception:
        return None


def _get_wrapper_section(config: Any, name: str, required: bool) -> Any:
    getter = getattr(config, "getsection", None)
    if getter is None:
        if required:
            raise _fail("configuration wrapper does not expose section '%s'" % name)
        return None
    try:
        return getter(name)
    except Exception as exc:
        if required:
            raise _fail("missing required section [%s]: %s" % (name, exc))
        return None


def _split_sections(config: Any) -> Tuple[Any, Any, List[Tuple[str, Any]], Any]:
    if isinstance(config, Mapping):
        if "shared" in config or "devices" in config:
            shared = config.get("shared", config.get("ace"))
            hardware = config.get("hardware", config.get("ace_hardware"))
            machine = config.get("machine", config.get("ace_machine", {}))
            raw_devices = config.get("devices", [])
            if shared is None or hardware is None:
                raise _fail("plain config requires shared and hardware sections")
            devices: List[Tuple[str, Any]] = []
            if isinstance(raw_devices, Mapping):
                for name, section in raw_devices.items():
                    devices.append(("ace_device %s" % name, section))
            elif isinstance(raw_devices, Sequence) and not isinstance(raw_devices, (str, bytes)):
                for index, section in enumerate(raw_devices):
                    name = _section_name(section) or "ace_device ace%d" % index
                    devices.append((name, section))
            else:
                raise _fail("devices must be a list or mapping")
            return shared, hardware, devices, machine

        shared = config.get("ace")
        hardware = config.get("ace_hardware")
        if shared is None or hardware is None:
            raise _fail("plain config requires 'ace' and 'ace_hardware' sections")
        devices = [
            (str(name), section)
            for name, section in config.items()
            if str(name).startswith("ace_device ")
        ]
        return shared, hardware, devices, config.get("ace_machine", {})

    shared = config
    hardware = _get_wrapper_section(config, "ace_hardware", required=True)
    machine = _get_wrapper_section(config, "ace_machine", required=False)
    prefix_getter = getattr(config, "get_prefix_sections", None)
    if prefix_getter is None:
        raise _fail("configuration wrapper does not expose ace_device sections")
    try:
        raw_sections = list(prefix_getter("ace_device "))
    except Exception as exc:
        raise _fail("unable to enumerate ace_device sections: %s" % exc)
    devices = []
    for section in raw_sections:
        name = _section_name(section)
        if not name:
            raise _fail("ace_device section has no name")
        devices.append((name, section))
    return shared, hardware, devices, machine or {}


def _parse_shared(section: Any) -> SharedConfig:
    version = _integer(section, "driver_version", DRIVER_VERSION)
    if version != DRIVER_VERSION:
        raise _fail("[ace] driver_version must be 3")
    toolchange_mode = _string(section, "toolchange_mode", "manual").lower()
    if toolchange_mode not in TOOLCHANGE_MODES:
        raise _fail("toolchange_mode must be manual or automatic")
    material_types = _material_types(section)
    feed_speed = _validate_range("feed_speed", _number(section, "feed_speed", 80), 0.001)
    feed_fast_speed = _validate_range(
        "feed_fast_speed", _number(section, "feed_fast_speed", 160), 0.001
    )
    feed_slip_length = _validate_range(
        "feed_slip_compensation_length",
        _number(section, "feed_slip_compensation_length", 400),
        0,
    )
    feed_slip_speed = _validate_range(
        "feed_slip_compensation_speed",
        _number(section, "feed_slip_compensation_speed", 25),
        0.001,
    )
    retract_speed = _validate_range("retract_speed", _number(section, "retract_speed", 80), 0.001)
    retract_fast_speed = _validate_range(
        "retract_fast_speed", _number(section, "retract_fast_speed", 120), 0.001
    )
    retract_parking_speed = _validate_range(
        "retract_parking_speed", _number(section, "retract_parking_speed", 25), 0.001
    )
    retract_parking_length = _validate_range(
        "retract_parking_length", _number(section, "retract_parking_length", 200), 0
    )
    load_length = _validate_range(
        "toolchange_load_length", _number(section, "toolchange_load_length", 630), 0
    )
    retract_length = _validate_range(
        "toolchange_retract_length", _number(section, "toolchange_retract_length", 150), 0
    )
    bowden_length = _validate_range(
        "bowden_tube_length", _number(section, "bowden_tube_length", 1000), 0
    )
    nozzle_length = _validate_range(
        "toolhead_sensor_to_nozzle", _number(section, "toolhead_sensor_to_nozzle", 50), 0
    )
    max_dryer = _validate_range(
        "max_dryer_temperature", _number(section, "max_dryer_temperature", 55), 0, 90
    )
    extruder_sensor_pin = _optional_string(section, "extruder_sensor_pin")
    toolhead_sensor_pin = _optional_string(section, "toolhead_sensor_pin")
    toolhead_sensor_bypass = _boolean(section, "toolhead_sensor_bypass", True)
    toolhead_sensor_bypass_calibrated = _boolean(
        section, "toolhead_sensor_bypass_calibrated", False
    )
    rdm_sensor_pin = _optional_string(section, "rdm_sensor_pin")
    hub_sensor_pins = tuple(
        _optional_string(section, "ace%d_hub_sensor_pin" % index)
        for index in range(MAX_DEVICES)
    )
    encoder_sensor_pin = _optional_string(section, "encoder_sensor_pin")

    def configured_sensor_name(option: str, pin: Optional[str]) -> Optional[str]:
        legacy_name = _optional_string(section, option)
        return legacy_name or (FIXED_SENSOR_NAMES[option] if pin else None)

    extruder_sensor_name = configured_sensor_name(
        "extruder_sensor_name", extruder_sensor_pin
    )
    toolhead_sensor_name = configured_sensor_name(
        "toolhead_sensor_name", toolhead_sensor_pin
    )
    rdm_sensor_name = configured_sensor_name("rdm_sensor_name", rdm_sensor_pin)
    hub_sensor_names = tuple(
        configured_sensor_name(
            "ace%d_hub_sensor_name" % index, hub_sensor_pins[index]
        )
        for index in range(MAX_DEVICES)
    )
    encoder_sensor_name = configured_sensor_name(
        "encoder_sensor_name", encoder_sensor_pin
    )
    configured_sensor_names = [
        name
        for name in (extruder_sensor_name, toolhead_sensor_name, rdm_sensor_name)
        if name
    ]
    configured_sensor_names.extend(name for name in hub_sensor_names if name)
    normalized_sensor_names = [name.strip().lower() for name in configured_sensor_names]
    if len(normalized_sensor_names) != len(set(normalized_sensor_names)):
        raise _fail("filament sensor names must be unique")
    extruder_debounce = _integer(section, "extruder_sensor_debounce_count", 2)
    toolhead_debounce = _integer(section, "toolhead_sensor_debounce_count", 2)
    rdm_debounce = _integer(section, "rdm_sensor_debounce_count", 3)
    hub_debounce = _integer(section, "ace_hub_sensor_debounce_count", 3)
    unload_attempts = _integer(section, "toolhead_unload_max_attempts", 10)
    for name, value in (
        ("extruder_sensor_debounce_count", extruder_debounce),
        ("toolhead_sensor_debounce_count", toolhead_debounce),
        ("rdm_sensor_debounce_count", rdm_debounce),
        ("ace_hub_sensor_debounce_count", hub_debounce),
        ("toolhead_unload_max_attempts", unload_attempts),
    ):
        _validate_range(name, value, 1)
    match_mode = _string(section, "endless_spool_match_mode", "exact").lower()
    if match_mode not in {"exact", "material"}:
        raise _fail("endless_spool_match_mode must be exact or material")
    encoder_mode = _string(section, "encoder_mode", "off").lower()
    if encoder_mode not in ENCODER_MODES:
        raise _fail("encoder_mode must be off, monitor, or protect")
    encoder_print_mode = _string(section, "encoder_print_mode", "off").lower()
    if encoder_print_mode not in ENCODER_PRINT_MODES:
        raise _fail("encoder_print_mode must be off, monitor, or pause")
    return SharedConfig(
        driver_version=version,
        toolchange_mode=toolchange_mode,
        material_types=material_types,
        extruder_sensor_name=extruder_sensor_name,
        toolhead_sensor_name=toolhead_sensor_name,
        rdm_sensor_name=rdm_sensor_name,
        ace0_hub_sensor_name=hub_sensor_names[0],
        ace1_hub_sensor_name=hub_sensor_names[1],
        ace2_hub_sensor_name=hub_sensor_names[2],
        ace3_hub_sensor_name=hub_sensor_names[3],
        extruder_sensor_pin=extruder_sensor_pin,
        toolhead_sensor_pin=toolhead_sensor_pin,
        toolhead_sensor_bypass=toolhead_sensor_bypass,
        toolhead_sensor_bypass_calibrated=toolhead_sensor_bypass_calibrated,
        rdm_sensor_pin=rdm_sensor_pin,
        ace0_hub_sensor_pin=hub_sensor_pins[0],
        ace1_hub_sensor_pin=hub_sensor_pins[1],
        ace2_hub_sensor_pin=hub_sensor_pins[2],
        ace3_hub_sensor_pin=hub_sensor_pins[3],
        extruder_sensor_debounce_count=extruder_debounce,
        toolhead_sensor_debounce_count=toolhead_debounce,
        rdm_sensor_debounce_count=rdm_debounce,
        ace_hub_sensor_debounce_count=hub_debounce,
        encoder_sensor_name=encoder_sensor_name,
        encoder_sensor_pin=encoder_sensor_pin,
        encoder_resolution=_validate_range(
            "encoder_resolution",
            _number(section, "encoder_resolution", 0),
            0,
        ),
        encoder_detection_length=_validate_range(
            "encoder_detection_length",
            _number(section, "encoder_detection_length", 20),
            0.001,
        ),
        encoder_min_tracking_ratio=_validate_range(
            "encoder_min_tracking_ratio",
            _number(section, "encoder_min_tracking_ratio", 0.6),
            0.01,
            1.0,
        ),
        encoder_mode=encoder_mode,
        encoder_print_mode=encoder_print_mode,
        encoder_print_detection_length=_validate_range(
            "encoder_print_detection_length",
            _number(section, "encoder_print_detection_length", 20),
            0.001,
        ),
        feed_speed=feed_speed,
        feed_fast_speed=feed_fast_speed,
        feed_slip_compensation_length=feed_slip_length,
        feed_slip_compensation_speed=feed_slip_speed,
        retract_speed=retract_speed,
        retract_fast_speed=retract_fast_speed,
        retract_parking_speed=retract_parking_speed,
        retract_parking_length=retract_parking_length,
        toolchange_load_length=load_length,
        upper_sensor_feed_timeout=_validate_range(
            "upper_sensor_feed_timeout",
            _number(section, "upper_sensor_feed_timeout", 30),
            1,
            UPPER_SENSOR_FEED_TIMEOUT_MAX,
        ),
        toolchange_retract_length=retract_length,
        bowden_tube_length=bowden_length,
        toolhead_sensor_to_nozzle=nozzle_length,
        toolhead_sensor_bypass_load_length=_validate_range(
            "toolhead_sensor_bypass_load_length",
            _number(section, "toolhead_sensor_bypass_load_length", 25),
            0,
            TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX,
        ),
        toolhead_feed_fast_speed=_validate_range(
            "toolhead_feed_fast_speed",
            _number(section, "toolhead_feed_fast_speed", 10),
            0.001,
        ),
        toolhead_feed_slow_speed=_validate_range(
            "toolhead_feed_slow_speed",
            _number(section, "toolhead_feed_slow_speed", 5),
            0.001,
        ),
        toolhead_feed_fast_length=_validate_range(
            "toolhead_feed_fast_length",
            _number(section, "toolhead_feed_fast_length", 10),
            0,
        ),
        toolhead_feed_fast_step=_validate_range(
            "toolhead_feed_fast_step",
            _number(section, "toolhead_feed_fast_step", 5),
            0.001,
        ),
        toolhead_feed_slow_step=_validate_range(
            "toolhead_feed_slow_step",
            _number(section, "toolhead_feed_slow_step", 1),
            0.001,
        ),
        toolhead_to_nozzle_speed=_validate_range(
            "toolhead_to_nozzle_speed",
            _number(section, "toolhead_to_nozzle_speed", 8),
            0.001,
        ),
        toolhead_sensor_max_feed_length=_validate_range(
            "toolhead_sensor_max_feed_length",
            _number(section, "toolhead_sensor_max_feed_length", 200),
            0.001,
        ),
        toolhead_unload_step_length=_validate_range(
            "toolhead_unload_step_length",
            _number(section, "toolhead_unload_step_length", 50),
            0.001,
        ),
        toolhead_unload_speed=_validate_range(
            "toolhead_unload_speed",
            _number(section, "toolhead_unload_speed", 10),
            0.001,
        ),
        toolhead_unload_max_attempts=unload_attempts,
        ace_unload_step_length=_validate_range(
            "ace_unload_step_length",
            _number(section, "ace_unload_step_length", 100),
            0.001,
        ),
        rdm_clear_move_length=_validate_range(
            "rdm_clear_move_length",
            _number(section, "rdm_clear_move_length", 100),
            0,
        ),
        ace0_hub_retract_length=_validate_range(
            "ace0_hub_retract_length",
            _number(section, "ace0_hub_retract_length", 0),
            0,
        ),
        ace1_hub_retract_length=_validate_range(
            "ace1_hub_retract_length",
            _number(section, "ace1_hub_retract_length", 0),
            0,
        ),
        ace2_hub_retract_length=_validate_range(
            "ace2_hub_retract_length",
            _number(section, "ace2_hub_retract_length", 0),
            0,
        ),
        ace3_hub_retract_length=_validate_range(
            "ace3_hub_retract_length",
            _number(section, "ace3_hub_retract_length", 0),
            0,
        ),
        ace0_hub_clear_move_length=_validate_range(
            "ace0_hub_clear_move_length",
            _number(section, "ace0_hub_clear_move_length", 0),
            0,
        ),
        ace1_hub_clear_move_length=_validate_range(
            "ace1_hub_clear_move_length",
            _number(section, "ace1_hub_clear_move_length", 0),
            0,
        ),
        ace2_hub_clear_move_length=_validate_range(
            "ace2_hub_clear_move_length",
            _number(section, "ace2_hub_clear_move_length", 0),
            0,
        ),
        ace3_hub_clear_move_length=_validate_range(
            "ace3_hub_clear_move_length",
            _number(section, "ace3_hub_clear_move_length", 0),
            0,
        ),
        sensor_trigger_grace_time=_validate_range(
            "sensor_trigger_grace_time",
            _number(section, "sensor_trigger_grace_time", 3),
            0,
            30,
        ),
        max_dryer_temperature=max_dryer,
        endless_spool=_boolean(section, "endless_spool", False),
        endless_spool_match_mode=match_mode,
        connection_supervision=_boolean(section, "connection_supervision", True),
        require_path_hooks=_boolean(section, "require_path_hooks", True),
        require_cut_hook=_boolean(section, "require_cut_hook", True),
    )


def _parse_machine(section: Any) -> MachineConfig:
    values: Dict[str, Optional[str]] = {}
    for key in (
        "pre_toolchange_macro",
        "cut_macro",
        "load_to_toolhead_macro",
        "unload_from_toolhead_macro",
        "wipe_nozzle_macro",
        "post_toolchange_macro",
        "pause_on_error_macro",
    ):
        value = _string(section, key, DEFAULT_MACHINE_MACROS[key]) or None
        if value is not None and not _MACRO_RE.match(value):
            raise _fail("option '%s' is not a valid macro name" % key)
        values[key] = value
    return MachineConfig(**values)


def _parse_device(name: str, section: Any, expected_index: int) -> DeviceConfig:
    match = _DEVICE_SECTION_RE.match(name.strip().lower())
    if match is None:
        raise _fail("invalid device section [%s]; expected [ace_device ace%d]" % (name, expected_index))
    device_id = match.group(1)
    expected_id = "ace%d" % expected_index
    if device_id != expected_id:
        raise _fail("device sections must be continuous; expected [ace_device %s]" % expected_id)
    model = _string(section, "model").lower()
    if model not in (DeviceModel.ACE1.value, DeviceModel.ACE2.value, DeviceModel.AUTO.value):
        raise _fail("%s model must be ace1, ace2, or auto" % device_id)
    transport = _string(section, "transport", "serial").lower()
    if transport != "serial":
        raise _fail("%s transport must be serial" % device_id)
    enabled = _boolean(section, "enabled", True)
    rfid_enabled = _boolean(section, "rfid_enabled", True)
    serial = _string(section, "serial", "")
    if enabled and not serial:
        raise _fail("%s requires a serial path while enabled" % device_id)
    requested_actions = _boolean(section, "physical_actions_enabled", False)
    if model in (DeviceModel.ACE2.value, DeviceModel.AUTO.value) and requested_actions:
        reason = (
            "ACE2 is read-only in Ace Pro Control Center"
            if model == DeviceModel.ACE2.value
            else "auto model is unresolved"
        )
        raise _fail("%s cannot enable physical actions: %s" % (device_id, reason))
    bus_id = _optional_string(section, "bus_id")
    device_uid = _optional_string(section, "device_uid")
    if model == DeviceModel.ACE2.value:
        if not bus_id:
            raise _fail("%s ACE2 requires bus_id" % device_id)
        if not device_uid:
            raise _fail("%s ACE2 requires an explicit device_uid" % device_id)
        if device_uid.strip().lower() == "auto":
            raise _fail(
                "%s ACE2 device_uid=auto is unavailable until persistent discovery is implemented"
                % device_id
            )
    elif bus_id or device_uid:
        raise _fail("%s bus_id and device_uid are only valid for ACE2" % device_id)
    return DeviceConfig(
        device_id=device_id,
        index=expected_index,
        model=model,
        transport=transport,
        serial=serial,
        enabled=enabled,
        rfid_enabled=rfid_enabled,
        physical_actions_enabled=requested_actions and model == DeviceModel.ACE1.value,
        bus_id=bus_id,
        device_uid=device_uid,
    )


def _validate_topology(devices: Sequence[DeviceConfig]) -> None:
    serial_owners: Dict[str, List[DeviceConfig]] = {}
    buses: Dict[str, str] = {}
    uids: Dict[Tuple[str, str], str] = {}
    for device in devices:
        if not device.enabled:
            continue
        serial_owners.setdefault(device.serial, []).append(device)
        if device.model == DeviceModel.ACE2.value and device.bus_id:
            prior_serial = buses.setdefault(device.bus_id, device.serial)
            if prior_serial != device.serial:
                raise _fail(
                    "ACE2 bus_id '%s' must use one shared serial path" % device.bus_id
                )
            if device.device_uid and device.device_uid.lower() != "auto":
                key = (device.bus_id, device.device_uid.lower())
                prior_owner = uids.setdefault(key, device.device_id)
                if prior_owner != device.device_id:
                    raise _fail(
                        "ACE2 device_uid '%s' is duplicated on bus '%s'"
                        % (device.device_uid, device.bus_id)
                    )
    for serial, owners in serial_owners.items():
        if len(owners) == 1:
            continue
        if not all(device.model == DeviceModel.ACE2.value for device in owners):
            raise _fail("serial path '%s' cannot be shared by ACE1 or auto devices" % serial)
        bus_ids = {device.bus_id for device in owners}
        if len(bus_ids) != 1 or None in bus_ids:
            raise _fail(
                "shared ACE2 serial path '%s' requires the same explicit bus_id" % serial
            )


def parse_config(config: Any) -> DriverConfig:
    """Parse a Klipper config wrapper or sectioned plain mapping."""

    shared_section, hardware_section, raw_devices, machine_section = _split_sections(config)
    hardware_version = _integer(hardware_section, "driver_version", DRIVER_VERSION)
    if hardware_version != DRIVER_VERSION:
        raise _fail("[ace_hardware] driver_version must be 3")
    device_count = _integer(hardware_section, "device_count")
    if device_count < 1 or device_count > MAX_DEVICES:
        raise _fail("device_count must be between 1 and 4")
    topology_mode = _string(hardware_section, "topology_mode", TOPOLOGY_MODE).lower()
    if topology_mode != TOPOLOGY_MODE:
        raise _fail("topology_mode must be configured")
    raw_devices.sort(key=lambda item: item[0].lower())
    if len(raw_devices) != device_count:
        raise _fail(
            "device_count is %d but %d active ace_device sections were found"
            % (device_count, len(raw_devices))
        )
    devices = tuple(
        _parse_device(name, section, index)
        for index, (name, section) in enumerate(raw_devices)
    )
    _validate_topology(devices)
    return DriverConfig(
        devices=devices,
        shared=_parse_shared(shared_section),
        machine=_parse_machine(machine_section),
        topology_mode=topology_mode,
        driver_version=hardware_version,
    )


__all__ = [
    "ConfigError",
    "DEFAULT_CUT_MACRO",
    "DEFAULT_MACHINE_MACROS",
    "DRIVER_VERSION",
    "DeviceConfig",
    "DriverConfig",
    "MachineConfig",
    "FIXED_SENSOR_NAMES",
    "SharedConfig",
    "TOOLCHANGE_MODES",
    "parse_config",
]
