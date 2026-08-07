"""Klipper component adapter for the Ace Pro Control Center core."""

from __future__ import annotations

import ast
import configparser
import logging
import re
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from . import PRODUCT_NAME_ZH
from .commands import AceCommands
from .config import FIXED_SENSOR_NAMES, parse_config
from .device import AceDevice
from .i18n import localize_exception, localize_message
from .manager import AceManager
from .persistent_state import PersistenceError, PersistentState
from .protocol import ProtocolCapabilities, create_protocol
from .transport import SerialTransport


ENCODER_PRINT_POLL_INTERVAL = 0.25
MACHINE_HOOK_OPTIONS = {
    "pre_toolchange": "pre_toolchange_macro",
    "cut": "cut_macro",
    "load_to_toolhead": "load_to_toolhead_macro",
    "unload_from_toolhead": "unload_from_toolhead_macro",
    "wipe_nozzle": "wipe_nozzle_macro",
    "post_toolchange": "post_toolchange_macro",
    "pause_on_error": "pause_on_error_macro",
}


class _ReactorSerialTransport:
    """Run blocking pyserial calls off Klipper's Reactor thread."""

    def __init__(self, transport: SerialTransport, reactor: Any, name: str) -> None:
        self._transport = transport
        self._reactor = reactor
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="ace-v3-%s" % name
        )

    @property
    def is_open(self) -> bool:
        return self._transport.is_open

    def open(self) -> None:
        self._wait(self._executor.submit(self._transport.open))

    def close(self) -> None:
        self._wait(self._executor.submit(self._transport.close))

    def request(self, payload: bytes, timeout: Optional[float] = None) -> bytes:
        return self._wait(
            self._executor.submit(self._transport.request, payload, timeout)
        )

    def request_once(self, payload: bytes, timeout: Optional[float] = None) -> bytes:
        return self._wait(
            self._executor.submit(self._transport.request_once, payload, timeout)
        )

    def _wait(self, future: Future) -> Any:
        pause = getattr(self._reactor, "pause", None)
        monotonic = getattr(self._reactor, "monotonic", None)
        if pause is None or monotonic is None:
            return future.result()
        while not future.done():
            pause(monotonic() + 0.025)
        return future.result()


class KlipperStateStore:
    """Persist product state atomically, mirroring save_variables when present."""

    _NAME = re.compile(r"^[a-z0-9_]+$")

    def __init__(
        self,
        printer: Any,
        gcode: Any,
        *,
        state_path: Optional[Any] = None,
        legacy_path: Optional[Any] = None,
    ) -> None:
        self.printer = printer
        self.gcode = gcode
        self._memory: Dict[str, Any] = {}
        self._save_variables = printer.lookup_object("save_variables", None)
        config_dir = None
        if state_path is None or legacy_path is None:
            config_dir = _printer_config_dir(printer)
        self._state = PersistentState(
            Path(state_path)
            if state_path is not None
            else config_dir / ".ace-driver-v3" / "runtime-state.json"
        )
        self._legacy_path = (
            Path(legacy_path)
            if legacy_path is not None
            else config_dir / "saved_variables.cfg"
        )

    def bind(self) -> None:
        self._save_variables = self.printer.lookup_object("save_variables", None)

    def migrate_legacy_inventory(self, device_count: int) -> bool:
        """Import V2 slot metadata once, preferring per-device inventories."""

        if self._contains("inventory"):
            return False

        values = self._legacy_variables()

        inventories = []
        found = False
        for device_index in range(max(0, min(4, int(device_count)))):
            source = (
                values.get("ace_inventory")
                if device_index == 0
                else values.get("ace_inventory_%d" % device_index)
            )
            if source is None:
                source = values.get("ace_inventory_%d" % device_index)
            slots = []
            if isinstance(source, list):
                found = True
                for raw_slot in source[:4]:
                    slots.append(_legacy_inventory_slot(raw_slot))
            inventories.append(slots)
        if not found:
            return False
        self.set("inventory", inventories)
        return True

    def get(self, name: str, default: Any = None) -> Any:
        key = "ace_v3_%s" % name
        if key in self._memory:
            return self._memory[key]
        if self._save_variables is not None:
            values = getattr(self._save_variables, "allVariables", {})
            if key in values:
                return values[key]
        try:
            return self._state.get(name, default)
        except PersistenceError:
            logging.exception("%s：无法读取运行时状态", PRODUCT_NAME_ZH)
            return default

    def set(self, name: str, value: Any) -> None:
        if not self._NAME.match(name):
            raise ValueError("ACE 状态键名称无效")
        key = "ace_v3_%s" % name
        persisted = -1 if value is None else int(value) if isinstance(value, bool) else value
        self._memory[key] = persisted
        if self._save_variables is not None:
            self.gcode.run_script_from_command(
                "SAVE_VARIABLE VARIABLE=%s VALUE=%s" % (key, repr(persisted))
            )
        try:
            self._state.set(name, persisted)
            self._state.flush()
        except PersistenceError:
            logging.exception("%s：无法持久化运行时状态", PRODUCT_NAME_ZH)

    def flush(self) -> None:
        try:
            self._state.flush()
        except PersistenceError:
            logging.exception("%s：无法写入运行时状态", PRODUCT_NAME_ZH)

    def _contains(self, name: str) -> bool:
        key = "ace_v3_%s" % name
        if key in self._memory:
            return True
        if self._save_variables is not None:
            values = getattr(self._save_variables, "allVariables", {})
            if key in values:
                return True
        try:
            self._state.get(name)
            return name in self._state.snapshot()
        except PersistenceError:
            logging.exception("%s：无法检查运行时状态", PRODUCT_NAME_ZH)
            return False

    def _legacy_variables(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        if self._save_variables is not None:
            current = getattr(self._save_variables, "allVariables", {})
            if isinstance(current, Mapping):
                values.update(current)
        if not self._legacy_path.is_file():
            return values

        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(self._legacy_path, encoding="utf-8")
            section_name = next(
                (name for name in parser.sections() if name.lower() == "variables"),
                None,
            )
            if section_name is None:
                return values
            for name, encoded in parser[section_name].items():
                if name in values or not name.startswith("ace_inventory"):
                    continue
                try:
                    values[name] = ast.literal_eval(encoded)
                except (SyntaxError, ValueError):
                    logging.warning(
                        "%s：已忽略格式错误的旧版变量 %s", PRODUCT_NAME_ZH, name
                    )
        except (OSError, UnicodeError, configparser.Error):
            logging.exception(
                "%s：无法读取旧版 saved_variables.cfg", PRODUCT_NAME_ZH
            )
        return values


class KlipperAceComponent:
    def __init__(self, config: Any) -> None:
        self.config = config
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        self.driver_config = parse_config(config)
        self._install_configured_path_sensors(config)
        self.encoder = self._install_configured_encoder(config)
        self._bind_encoder_calibration_reporter()
        self.state_store = KlipperStateStore(self.printer, self.gcode)
        self._transports: Dict[Any, Any] = {}
        self._ace2_controllers = self._build_ace2_controllers()
        self.devices = [self._build_device(item) for item in self.driver_config.devices]
        self.manager = AceManager(
            self.devices,
            shared=self.driver_config.shared,
            machine_hook=self._run_machine_hook,
            machine_hook_validator=self._validate_machine_hooks,
            extruder_preflight=self._preflight_extruder_moves,
            sensor_state=self._read_path_sensor,
            print_state=self._get_print_state,
            state_store=self.state_store,
            encoder=self.encoder,
            sleep=self._cooperative_sleep,
        )
        self.commands = AceCommands(self.manager, self.gcode)
        self.commands.register()
        self._register_path_commands()
        self._poll_timer = None
        self._encoder_print_timer = None

        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.printer.register_event_handler("klippy:disconnect", self._handle_disconnect)
        self.printer.register_event_handler("klippy:shutdown", self._handle_disconnect)
        try:
            self.printer.add_object("ace_manager", self.manager)
            for device in self.devices:
                self.printer.add_object("ace_runtime %s" % device.device_id, device)
        except Exception:
            logging.exception(
                "%s：无法注册辅助打印机对象", PRODUCT_NAME_ZH
            )

    def get_status(self, eventtime: Optional[float] = None) -> Dict[str, Any]:
        return self.manager.get_status(eventtime)

    def _install_configured_path_sensors(self, config: Any) -> None:
        logical_names = ["extruder", "toolhead", "rdm"]
        device_count = len(getattr(self.driver_config, "devices", ()))
        if device_count > 1:
            logical_names.extend(
                "ace%d_hub" % index for index in range(device_count)
            )
        fileconfig = getattr(config, "fileconfig", None)
        if fileconfig is None:
            return
        for logical_name in logical_names:
            name = self._configured_sensor_name(logical_name)
            pin = self._shared(logical_name + "_sensor_pin", None)
            if not name or not pin:
                continue
            section = "filament_switch_sensor %s" % name
            if fileconfig.has_section(section):
                continue
            fileconfig.add_section(section)
            fileconfig.set(section, "switch_pin", str(pin))
            fileconfig.set(section, "pause_on_runout", "False")
            self.printer.load_object(config, section)

    def _install_configured_encoder(self, config: Any) -> Optional[Any]:
        shared = self.driver_config.shared
        name = self._configured_sensor_name("encoder")
        pin = getattr(shared, "encoder_sensor_pin", None)
        if not name:
            return None

        section = "ace_encoder %s" % name
        fileconfig = getattr(config, "fileconfig", None)
        loaded = None
        if fileconfig is not None and pin and not fileconfig.has_section(section):
            fileconfig.add_section(section)
            fileconfig.set(section, "encoder_pin", str(pin))
            fileconfig.set(
                section,
                "encoder_resolution",
                str(getattr(shared, "encoder_resolution", 0)),
            )
            fileconfig.set(
                section,
                "detection_length",
                str(getattr(shared, "encoder_detection_length", 20)),
            )
            fileconfig.set(
                section,
                "min_tracking_ratio",
                str(getattr(shared, "encoder_min_tracking_ratio", 0.6)),
            )
            fileconfig.set(
                section, "mode", str(getattr(shared, "encoder_mode", "off"))
            )
        if fileconfig is not None and fileconfig.has_section(section):
            loaded = self.printer.load_object(config, section)
        encoder = loaded or self.printer.lookup_object(section, None)
        configure = getattr(encoder, "configure", None)
        if callable(configure):
            configure(
                resolution=getattr(shared, "encoder_resolution", 0),
                detection_length=getattr(shared, "encoder_detection_length", 20),
                min_tracking_ratio=getattr(
                    shared, "encoder_min_tracking_ratio", 0.6
                ),
                mode=getattr(shared, "encoder_mode", "off"),
            )
        return encoder

    def _bind_encoder_calibration_reporter(self) -> None:
        setter = getattr(self.encoder, "set_calibration_reporter", None)
        if callable(setter):
            setter(self._report_encoder_calibration_count)

    def _report_encoder_calibration_count(self, event: Mapping[str, Any]) -> None:
        increment = max(0, int(event.get("increment", 0)))
        calibration_counts = max(0, int(event.get("calibration_counts", 0)))
        total_counts = max(0, int(event.get("total_counts", 0)))
        self.gcode.respond_info(
            "%s：编码器校准计数，本次新增 %d，校准累计 %d，硬件累计 %d 个脉冲。"
            % (PRODUCT_NAME_ZH, increment, calibration_counts, total_counts)
        )

    def _register_path_commands(self) -> None:
        self.gcode.register_command(
            "ACE_PATH_LOAD_TO_TOOLHEAD",
            self._cmd_path_load_to_toolhead,
            desc="ACE 内部传感器引导送料步骤",
        )
        self.gcode.register_command(
            "ACE_PATH_UNLOAD_STEP",
            self._cmd_path_unload_step,
            desc="ACE 内部传感器引导回料步骤",
        )

    def _cmd_path_load_to_toolhead(self, gcmd: Any) -> None:
        self._require_internal_path_command(gcmd, "select_tool")
        if not self._path_sensor_stable("upper", True):
            raise gcmd.error("ACE 上方耗材传感器未触发。")

        if self._lower_sensor_bypassed():
            if not bool(
                self._shared("toolhead_sensor_bypass_calibrated", False)
            ):
                raise gcmd.error(
                    "ACE 下方耗材传感器旁路距离尚未确认校准。"
                )
            length = float(
                self._shared("toolhead_sensor_bypass_load_length", 25)
            )
            if length <= 0:
                raise gcmd.error(
                    "ACE 下方耗材传感器旁路送料距离尚未校准。"
                )
            step_limit = float(self._shared("toolhead_feed_fast_step", 5))
            speed = float(self._shared("toolhead_to_nozzle_speed", 8))
            moved = 0.0
            encoder_token = self._path_encoder_call(
                gcmd,
                self._start_encoder_tracking,
                "extruder_load",
                length,
            )
            try:
                while moved < length:
                    if not self._path_sensor_stable("upper", True):
                        raise gcmd.error(
                            "旁路送料期间 ACE 上方耗材传感器失去触发。"
                        )
                    step = min(step_limit, length - moved)
                    self._extruder_move(step, speed)
                    moved += step
                if not self._path_sensor_stable("upper", True):
                    raise gcmd.error(
                        "旁路送料完成后 ACE 上方耗材传感器失去触发。"
                    )
            except Exception:
                self._cancel_encoder_tracking(encoder_token)
                raise
            self._path_encoder_call(
                gcmd,
                self._finish_encoder_tracking,
                encoder_token,
                commanded_length=moved,
                command_completed=True,
            )
            gcmd.respond_info(
                "ACE 工具头耗材路径已完成送料；下方耗材传感器按配置旁路。"
            )
            return

        moved = 0.0
        maximum = float(self._shared("toolhead_sensor_max_feed_length", 200))
        nozzle_length = float(self._shared("toolhead_sensor_to_nozzle", 50))
        encoder_token = self._path_encoder_call(
            gcmd,
            self._start_encoder_tracking,
            "extruder_load",
            nozzle_length,
        )
        fast_length = min(
            maximum, float(self._shared("toolhead_feed_fast_length", 10))
        )
        try:
            while not self._path_sensor_stable("lower", True):
                if moved >= maximum:
                    raise gcmd.error(
                        "ACE 下方耗材传感器在送料 %.1f mm 内未触发。"
                        % maximum
                    )
                if not self._path_sensor_stable("upper", True):
                    raise gcmd.error("送料期间 ACE 上方耗材传感器失去触发。")
                remaining = maximum - moved
                if moved < fast_length:
                    step = min(
                        float(self._shared("toolhead_feed_fast_step", 5)),
                        fast_length - moved,
                        remaining,
                    )
                    speed = float(self._shared("toolhead_feed_fast_speed", 10))
                else:
                    step = min(
                        float(self._shared("toolhead_feed_slow_step", 1)), remaining
                    )
                    speed = float(self._shared("toolhead_feed_slow_speed", 5))
                self._extruder_move(step, speed)
                moved += step

            self._extruder_move(
                nozzle_length,
                float(self._shared("toolhead_to_nozzle_speed", 8)),
            )
            moved += nozzle_length
            if not self._path_sensor_stable(
                "upper", True
            ) or not self._path_sensor_stable("lower", True):
                raise gcmd.error("送料到喷嘴后 ACE 耗材传感器状态发生变化。")
        except Exception:
            self._cancel_encoder_tracking(encoder_token)
            raise
        self._path_encoder_call(
            gcmd,
            self._finish_encoder_tracking,
            encoder_token,
            commanded_length=moved,
            command_completed=True,
        )
        gcmd.respond_info("ACE 工具头耗材路径已完成送料并通过传感器验证。")

    def _cmd_path_unload_step(self, gcmd: Any) -> None:
        self._require_internal_path_command(gcmd, "unload")
        distance = -float(self._shared("toolhead_unload_step_length", 50))
        encoder_token = self._path_encoder_call(
            gcmd,
            self._start_encoder_tracking,
            "extruder_unload",
            abs(distance),
        )
        try:
            self._extruder_move(
                distance,
                float(self._shared("toolhead_unload_speed", 10)),
            )
        except Exception:
            self._cancel_encoder_tracking(encoder_token)
            raise
        self._path_encoder_call(
            gcmd,
            self._finish_encoder_tracking,
            encoder_token,
            commanded_length=abs(distance),
            command_completed=True,
        )

    def _path_encoder_call(
        self, gcmd: Any, operation: Any, *args: Any, **kwargs: Any
    ) -> Any:
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            mode = str(self._shared("encoder_mode", "off")).strip().lower()
            if mode != "protect":
                raise
            raise gcmd.error(
                "%s：%s" % (PRODUCT_NAME_ZH, localize_exception(exc))
            ) from exc

    def _start_encoder_tracking(
        self, action: str, commanded_length: float
    ) -> Optional[Any]:
        mode = str(self._shared("encoder_mode", "off")).strip().lower()
        if mode == "protect":
            self._validate_encoder_tracking_length(commanded_length)
        encoder = getattr(self, "encoder", None)
        if encoder is None or mode == "off":
            return None
        status_getter = getattr(encoder, "get_status", None)
        status = status_getter() if callable(status_getter) else {}
        if mode == "protect" and not bool(status.get("armed")):
            raise RuntimeError(
                "ACE 共享编码器保护尚未就绪，禁止挤出机移动。"
            )
        starter = getattr(encoder, "begin_motion", None)
        if not callable(starter):
            if mode == "protect":
                raise RuntimeError(
                    "ACE 共享编码器无法跟踪挤出机移动。"
                )
            return None
        try:
            return starter(
                action,
                "extruder",
                abs(float(commanded_length)),
                validation="tracking",
            )
        except Exception:
            if mode == "protect":
                raise
            logging.exception(
                "%s：无法开始挤出机编码器跟踪", PRODUCT_NAME_ZH
            )
            return None

    def _cancel_encoder_tracking(self, token: Optional[Any]) -> None:
        encoder = getattr(self, "encoder", None)
        if token is None or encoder is None:
            return
        cancel = getattr(encoder, "cancel_motion", None)
        if callable(cancel):
            try:
                cancel(token)
            except Exception:
                logging.exception(
                    "%s：无法取消挤出机编码器跟踪", PRODUCT_NAME_ZH
                )

    def _finish_encoder_tracking(
        self,
        token: Optional[Any],
        *,
        commanded_length: float,
        command_completed: bool,
    ) -> Optional[Dict[str, Any]]:
        mode = str(self._shared("encoder_mode", "off")).strip().lower()
        if mode == "protect":
            self._validate_encoder_tracking_length(commanded_length)
        encoder = getattr(self, "encoder", None)
        if token is None or encoder is None:
            return None
        settle_time = getattr(encoder, "get_settle_time", None)
        if callable(settle_time):
            self._cooperative_sleep(
                max(0.0, min(0.5, float(settle_time())))
            )
        finisher = getattr(encoder, "finish_motion", None)
        if not callable(finisher):
            if mode == "protect":
                raise RuntimeError(
                    "ACE 共享编码器无法完成挤出机移动跟踪。"
                )
            return None
        try:
            event = finisher(
                token,
                command_completed=command_completed,
                commanded_length=abs(float(commanded_length)),
            )
        except Exception:
            if mode == "protect":
                raise
            logging.exception(
                "%s：无法完成挤出机编码器跟踪", PRODUCT_NAME_ZH
            )
            return None
        result = dict(event or {})
        fault = result.get("fault")
        if fault and mode == "protect":
            message = fault.get("message") if isinstance(fault, Mapping) else str(fault)
            code = fault.get("code") if isinstance(fault, Mapping) else None
            raise RuntimeError(localize_message(message, code=code))
        return result

    def _validate_encoder_tracking_length(self, commanded_length: float) -> None:
        commanded_length = abs(float(commanded_length))
        detection_length = float(self._shared("encoder_detection_length", 20))
        if commanded_length < detection_length:
            raise RuntimeError(
                "ACE 共享编码器保护要求挤出机保证移动至少 %.1f mm；"
                "当前路径只能保证移动 %.1f mm。"
                % (detection_length, commanded_length)
            )

    def _require_internal_path_command(self, gcmd: Any, operation: str) -> None:
        transaction = getattr(self.manager, "_transaction", None) or {}
        action = str(transaction.get("action") or "")
        accepted = {operation}
        if operation == "unload":
            accepted.add("select_tool")
        if not self.manager.path_busy or action not in accepted:
            raise gcmd.error("此 ACE 路径命令只能在换料流程内部运行。")

    def _extruder_move(self, distance: float, speed: float) -> None:
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is None:
            raise RuntimeError("ACE 工具头路径控制需要 Klipper toolhead 对象。")
        gcode_move = self.printer.lookup_object("gcode_move", None)
        if gcode_move is None:
            raise RuntimeError("ACE 工具头路径控制需要 Klipper gcode_move 对象。")
        reset = getattr(gcode_move, "reset_last_position", None)
        last_position = getattr(gcode_move, "last_position", None)
        base_position = getattr(gcode_move, "base_position", None)
        if (
            not callable(reset)
            or last_position is None
            or base_position is None
            or len(last_position) < 4
            or len(base_position) < 4
        ):
            raise RuntimeError("ACE 无法同步 Klipper G-code 的 E 轴位置。")
        previous_last_e = float(last_position[3])
        previous_base_e = float(base_position[3])
        try:
            base_position[3] = previous_base_e
        except (IndexError, TypeError):
            raise RuntimeError("ACE 无法更新 Klipper G-code 的 E 轴位置。")

        self._preflight_extruder_moves((distance,))
        position = list(toolhead.get_position())
        position[3] += float(distance)
        try:
            toolhead.move(position, float(speed))
            wait_moves = getattr(toolhead, "wait_moves", None)
            if callable(wait_moves):
                wait_moves()
        finally:
            try:
                # Match RESTORE_GCODE_STATE's E-offset update after direct motion.
                reset()
                current_last_e = float(gcode_move.last_position[3])
                gcode_move.base_position[3] = (
                    previous_base_e + current_last_e - previous_last_e
                )
            except Exception as exc:
                raise RuntimeError(
                    "ACE 同步 Klipper G-code 的 E 轴位置失败。"
                ) from exc
        self._cooperative_sleep(0.02)

    def _preflight_extruder_moves(self, distances: Iterable[float]) -> None:
        planned = tuple(float(distance) for distance in distances)
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is None:
            raise RuntimeError("ACE 挤出预检需要 Klipper toolhead 对象。")
        get_extruder = getattr(toolhead, "get_extruder", None)
        if not callable(get_extruder):
            raise RuntimeError("ACE 挤出预检需要已启用的挤出机。")
        extruder = get_extruder()
        if extruder is None:
            raise RuntimeError("ACE 挤出预检需要已启用的挤出机。")
        get_heater = getattr(extruder, "get_heater", None)
        if not callable(get_heater):
            raise RuntimeError("ACE 无法读取当前挤出机的加热器状态。")
        heater = get_heater()
        if not bool(getattr(heater, "can_extrude", False)):
            raise RuntimeError(
                "ACE 挤出预检失败：当前挤出机温度未达到可挤出条件。"
            )
        maximum = getattr(extruder, "max_e_dist", None)
        if maximum is None:
            raise RuntimeError(
                "ACE 无法读取当前挤出机的 max_extrude_only_distance。"
            )
        maximum = float(maximum)
        for distance in planned:
            if abs(distance) > maximum:
                raise RuntimeError(
                    "ACE 挤出移动 %.3f mm 超过 max_extrude_only_distance 限值 "
                    "%.3f mm。" % (distance, maximum)
                )

    def _path_sensor_stable(self, logical_name: str, expected: bool) -> bool:
        counts = {
            "upper": int(self._shared("extruder_sensor_debounce_count", 2)),
            "lower": int(self._shared("toolhead_sensor_debounce_count", 2)),
            "rdm": int(self._shared("rdm_sensor_debounce_count", 3)),
        }
        count = counts.get(
            logical_name, int(self._shared("ace_hub_sensor_debounce_count", 3))
        )
        for sample in range(max(1, count)):
            value = self._read_path_sensor(logical_name)
            if value is None or value is not bool(expected):
                return False
            if sample + 1 < count:
                self._cooperative_sleep(0.01)
        return True

    def _read_path_sensor(self, logical_name: str) -> Optional[bool]:
        sensor_logical_name = {
            "upper": "extruder",
            "lower": "toolhead",
            "rdm": "rdm",
        }.get(logical_name, logical_name)
        name = self._configured_sensor_name(sensor_logical_name)
        if not name:
            return None
        sensor = self.printer.lookup_object("filament_switch_sensor %s" % name, None)
        if sensor is None:
            raise RuntimeError("ACE 耗材传感器 '%s' 尚未注册。" % name)
        helper = getattr(sensor, "runout_helper", None)
        if helper is not None and hasattr(helper, "filament_present"):
            return bool(helper.filament_present)
        status = sensor.get_status(self.reactor.monotonic())
        if "filament_detected" not in status:
            raise RuntimeError("ACE 耗材传感器 '%s' 没有可读取的检测状态。" % name)
        return bool(status["filament_detected"])

    def _build_device(self, device_config: Any) -> AceDevice:
        if device_config.model == "auto":
            return AceDevice(device_config, _UnresolvedProtocol(), _UnavailableTransport())
        protocol_kwargs: Dict[str, Any] = {
            "device_uid": getattr(device_config, "device_uid", None),
        }
        if device_config.model == "ace2":
            from .protocol_ace2 import Ace2BusRouter

            bus_id = str(device_config.bus_id)
            controller = self._ace2_controllers.get(bus_id)
            router = controller.router if controller is not None else Ace2BusRouter()
            protocol_kwargs.update(router=router, device_id=None)
            transport_key = ("ace2", bus_id)
        else:
            transport_key = ("ace1", device_config.device_id)
        protocol = create_protocol(device_config.model, **protocol_kwargs)
        transport = self._transports.get(transport_key)
        if transport is None:
            transport = _ReactorSerialTransport(
                SerialTransport(
                    port=device_config.serial,
                    baudrate=getattr(device_config, "baud", 115200),
                    timeout=float(self._shared("serial_timeout", 2.0)),
                    retries=int(self._shared("serial_retries", 2)),
                    wire_mode=device_config.model,
                ),
                self.reactor,
                device_config.device_id,
            )
            self._transports[transport_key] = transport
        return AceDevice(device_config, protocol, transport)

    def _handle_ready(self) -> None:
        self.state_store.bind()
        self.state_store.migrate_legacy_inventory(len(self.devices))
        self.manager.restore_state()
        self._initialize_ace2_buses()
        self.manager.start()
        self.manager.reconcile_path_state()
        interval = float(self._shared("status_interval", 2.0))
        self._poll_timer = self.reactor.register_timer(
            self._poll, self.reactor.monotonic() + interval
        )
        if (
            self.encoder is not None
            and str(self._shared("encoder_print_mode", "off")).strip().lower()
            != "off"
        ):
            self._encoder_print_timer = self.reactor.register_timer(
                self._poll_encoder_print_monitor,
                self.reactor.monotonic() + ENCODER_PRINT_POLL_INTERVAL,
            )

    def _handle_disconnect(self) -> None:
        if self._poll_timer is not None:
            try:
                self.reactor.unregister_timer(self._poll_timer)
            except Exception:
                pass
            self._poll_timer = None
        if self._encoder_print_timer is not None:
            try:
                self.reactor.unregister_timer(self._encoder_print_timer)
            except Exception:
                pass
            self._encoder_print_timer = None
        self.manager.update_encoder_print_monitor(None, print_state="standby")
        self.manager.stop()
        self.state_store.flush()

    def _poll(self, eventtime: float) -> float:
        try:
            self.manager.refresh()
        except Exception:
            logging.exception("%s：后台状态刷新失败", PRODUCT_NAME_ZH)
        return self.reactor.monotonic() + float(self._shared("status_interval", 2.0))

    def _poll_encoder_print_monitor(self, eventtime: float) -> float:
        try:
            print_state = self._get_print_state()
            position = (
                self._get_extruder_physical_position(eventtime)
                if print_state.strip().lower() == "printing"
                else None
            )
            self.manager.update_encoder_print_monitor(
                position, print_state=print_state
            )
        except Exception:
            logging.exception(
                "%s：编码器打印监测轮询失败", PRODUCT_NAME_ZH
            )
        return self.reactor.monotonic() + ENCODER_PRINT_POLL_INTERVAL

    def _get_extruder_physical_position(
        self, eventtime: float
    ) -> Optional[float]:
        mcu = self.printer.lookup_object("mcu", None)
        estimate_print_time = getattr(mcu, "estimated_print_time", None)
        if not callable(estimate_print_time):
            return None

        extruder = None
        toolhead = self.printer.lookup_object("toolhead", None)
        get_extruder = getattr(toolhead, "get_extruder", None)
        if callable(get_extruder):
            try:
                extruder = get_extruder()
            except Exception:
                extruder = None
        find_past_position = getattr(extruder, "find_past_position", None)
        if not callable(find_past_position):
            extruder = self.printer.lookup_object("extruder", None)
            find_past_position = getattr(extruder, "find_past_position", None)
        if not callable(find_past_position):
            return None
        try:
            print_time = estimate_print_time(float(eventtime))
            return float(find_past_position(print_time))
        except Exception:
            return None

    def _cooperative_sleep(self, seconds: float) -> None:
        deadline = self.reactor.monotonic() + max(0.0, float(seconds))
        pause = getattr(self.reactor, "pause", None)
        if pause is None:
            import time

            time.sleep(max(0.0, float(seconds)))
            return
        while self.reactor.monotonic() < deadline:
            pause(min(deadline, self.reactor.monotonic() + 0.05))

    def _get_print_state(self) -> str:
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is None:
            return "unknown"
        try:
            return str(print_stats.get_status(self.reactor.monotonic()).get("state", "unknown"))
        except Exception:
            return "unknown"

    def _run_machine_hook(self, name: str, params: Mapping[str, Any]) -> None:
        machine = self.driver_config.machine
        key = MACHINE_HOOK_OPTIONS[name]
        macro = machine.get(key) if isinstance(machine, Mapping) else getattr(machine, key, None)
        if not macro:
            if self._machine_hook_required(name):
                extra = (
                    "；V3 不支持耗材尖端成型，必须配置切刀宏"
                    if name == "cut"
                    else ""
                )
                raise RuntimeError(
                    "ACE 必需机器宏 '%s' 未配置：[ace_machine] %s 没有绑定宏%s。"
                    % (name, key, extra)
                )
            return
        arguments = []
        for item_key, item_value in params.items():
            label = item_key.upper()
            value = -1 if item_value is None else int(item_value)
            arguments.append("%s=%s" % (label, value))
        self.gcode.run_script_from_command("%s %s" % (macro, " ".join(arguments)))

    def _validate_machine_hooks(self, names: Any) -> None:
        issues = []
        lookup = getattr(self.gcode, "lookup_command", None)
        for name in names:
            macro = self._machine_macro(name)
            key = MACHINE_HOOK_OPTIONS[name]
            required = self._machine_hook_required(name)
            if not macro:
                if required:
                    issues.append(
                        "%s 为必需项，但 [ace_machine] %s 没有绑定宏"
                        % (name, key)
                    )
                continue
            if lookup is not None and lookup(str(macro).upper(), None) is None:
                issues.append(
                    "%s（[ace_machine] %s 指向的 %s 尚未注册）"
                    % (name, key, macro)
                )
        if issues:
            raise RuntimeError(
                "ACE 机器宏配置不完整：%s。" % "；".join(issues)
            )

    def _machine_hook_required(self, name: str) -> bool:
        mode = str(self._shared("toolchange_mode", "manual")).strip().lower()
        if mode == "automatic":
            return name in MACHINE_HOOK_OPTIONS
        if name in {"load_to_toolhead", "unload_from_toolhead"}:
            return bool(self._shared("require_path_hooks", True))
        if name == "cut":
            return bool(self._shared("require_cut_hook", True))
        return name == "pause_on_error"

    def _machine_macro(self, name: str) -> Optional[str]:
        machine = self.driver_config.machine
        key = MACHINE_HOOK_OPTIONS[name]
        return machine.get(key) if isinstance(machine, Mapping) else getattr(machine, key, None)

    def _configured_sensor_name(self, logical_name: str) -> Optional[str]:
        option = logical_name + "_sensor_name"
        configured = self._shared(option, None)
        if configured:
            return str(configured).strip() or None
        if not self._shared(logical_name + "_sensor_pin", None):
            return None
        return FIXED_SENSOR_NAMES.get(option)

    def _lower_sensor_bypassed(self) -> bool:
        return bool(self._shared("toolhead_sensor_bypass", True))

    def _shared(self, name: str, default: Any) -> Any:
        shared = getattr(self.driver_config, "shared", {})
        if isinstance(shared, Mapping):
            return shared.get(name, default)
        return getattr(shared, name, default)

    def _build_ace2_controllers(self) -> Dict[str, Any]:
        from .protocol_ace2 import Ace2BusController, normalize_uid

        grouped: Dict[str, list] = {}
        for item in self.driver_config.devices:
            if item.enabled and item.model == "ace2":
                uid = normalize_uid(item.device_uid)
                if uid is not None:
                    grouped.setdefault(str(item.bus_id), []).append(uid)
        return {
            bus_id: Ace2BusController(uids)
            for bus_id, uids in grouped.items()
            if uids
        }

    def _initialize_ace2_buses(self) -> None:
        from .protocol_ace2 import normalize_uid

        for bus_id, controller in self._ace2_controllers.items():
            transport = self._transports.get(("ace2", bus_id))
            if transport is None:
                continue
            configured = {
                normalize_uid(item.device_uid): item.device_id
                for item in self.driver_config.devices
                if item.enabled and item.model == "ace2" and str(item.bus_id) == bus_id
                and normalize_uid(item.device_uid) is not None
            }
            assigned = set()
            try:
                transport.open()
                for _attempt in range(max(1, len(configured) * 3)):
                    discovery = controller.decode_discovery_response(
                        transport.request(controller.encode_discover())
                    )
                    uid = normalize_uid(discovery.get("result", {}).get("uid"))
                    if uid in assigned:
                        continue
                    controller.decode_assignment_response(
                        transport.request_once(controller.encode_assignment(uid))
                    )
                    assigned.add(uid)
                    if assigned == set(configured):
                        break
                if assigned != set(configured):
                    missing = sorted(set(configured) - assigned)
                    raise RuntimeError("未发现配置中的 ACE2 UID：%s" % missing)
                by_id = {device.device_id: device for device in self.devices}
                for uid, device_id in configured.items():
                    by_id[device_id].bind_protocol(controller.protocol_for(uid))
            except Exception:
                logging.exception(
                    "%s：ACE2 总线 %s 身份初始化失败",
                    PRODUCT_NAME_ZH,
                    bus_id,
                )


def load_config(config: Any) -> KlipperAceComponent:
    return KlipperAceComponent(config)


def _printer_config_dir(printer: Any) -> Path:
    get_start_args = getattr(printer, "get_start_args", None)
    if callable(get_start_args):
        try:
            start_args = get_start_args()
        except Exception:
            start_args = {}
        if isinstance(start_args, Mapping):
            config_file = start_args.get("config_file")
            if config_file:
                return Path(str(config_file)).expanduser().absolute().parent
    raise RuntimeError("%s：无法确定 Klipper 配置目录" % PRODUCT_NAME_ZH)


def _legacy_inventory_slot(value: Any) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    slot: Dict[str, Any] = {}
    if "material" in value:
        slot["material"] = str(value.get("material") or "").strip()
    if "color" in value:
        color = value.get("color")
        if isinstance(color, (list, tuple)) and len(color) >= 3:
            try:
                channels = [max(0, min(255, int(channel))) for channel in color[:3]]
                slot["color"] = "#%02X%02X%02X" % tuple(channels)
            except (TypeError, ValueError):
                pass
        elif isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color.strip()):
            slot["color"] = color.strip().upper()
    temperature = value.get("temperature", value.get("temp"))
    if temperature is not None:
        try:
            slot["temperature"] = max(0, int(temperature))
        except (TypeError, ValueError):
            pass
    if "rfid" in value:
        slot["rfid"] = value.get("rfid")
    if "status" in value:
        slot["status"] = str(value.get("status") or "unknown").strip().lower()
    return slot


class _UnresolvedProtocol:
    name = "unresolved"
    capabilities = ProtocolCapabilities(status=False, info=False, inventory=False)

    def encode_request(self, _method: str, _params: Any = None) -> bytes:
        raise RuntimeError("ACE 的 model=auto 无法安全识别，请明确配置设备型号。")

    def decode_response(self, _payload: bytes) -> Dict[str, Any]:
        raise RuntimeError("ACE 的 model=auto 无法安全识别，请明确配置设备型号。")

    def normalize_status(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        return dict(payload)


class _UnavailableTransport:
    is_open = False

    def open(self) -> None:
        raise RuntimeError("ACE 设备型号尚未识别，无法打开通信连接。")

    def close(self) -> None:
        return None

    def request(self, _payload: bytes) -> bytes:
        raise RuntimeError("ACE 设备型号尚未识别，无法发送通信请求。")
