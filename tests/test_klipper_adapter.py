from types import SimpleNamespace

import pytest

from ace_driver.config import MachineConfig, SharedConfig, parse_config
from ace_driver.klipper import KlipperAceComponent, KlipperStateStore


def component(machine=None, shared=None):
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = SimpleNamespace(
        machine=machine or MachineConfig(), shared=shared or SharedConfig()
    )
    value.gcode = SimpleNamespace(run_script_from_command=lambda _command: None)
    return value


def parsed_config_with_sensor_values(device_count=1, **values):
    sections = {
        "ace": {"driver_version": 3, **values},
        "ace_hardware": {
            "driver_version": 3,
            "device_count": device_count,
            "topology_mode": "configured",
        },
        "ace_machine": {},
    }
    for index in range(device_count):
        sections["ace_device ace%d" % index] = {
            "model": "ace1",
            "transport": "serial",
            "serial": "/dev/serial/by-id/ace%d" % index,
            "enabled": True,
            "physical_actions_enabled": False,
        }
    return parse_config(sections)


class MotionToolhead:
    def __init__(self, *, can_extrude=True, max_e_dist=50.0, move_error=None):
        self.position = [10.0, 20.0, 30.0, 40.0]
        self.moves = []
        self.move_error = move_error
        self.extruder = SimpleNamespace(
            max_e_dist=max_e_dist,
            get_heater=lambda: SimpleNamespace(can_extrude=can_extrude),
        )

    def get_position(self):
        return list(self.position)

    def get_extruder(self):
        return self.extruder

    def move(self, position, speed):
        self.moves.append((list(position), speed))
        self.position = list(position)
        if self.move_error is not None:
            raise self.move_error

    def wait_moves(self):
        return None


class MotionGcodeMove:
    def __init__(self, toolhead, *, absolute_extrude):
        self.toolhead = toolhead
        self.absolute_extrude = absolute_extrude
        self.extrude_factor = 1.25
        self.last_position = list(toolhead.position)
        self.base_position = [0.0, 0.0, 0.0, 15.0]
        self.reset_count = 0

    def reset_last_position(self):
        self.reset_count += 1
        self.last_position = self.toolhead.get_position()


def motion_component(
    *, absolute_extrude=True, can_extrude=True, max_e_dist=50.0, move_error=None
):
    value = component()
    toolhead = MotionToolhead(
        can_extrude=can_extrude,
        max_e_dist=max_e_dist,
        move_error=move_error,
    )
    gcode_move = MotionGcodeMove(
        toolhead, absolute_extrude=absolute_extrude
    )
    objects = {"toolhead": toolhead, "gcode_move": gcode_move}
    value.printer = SimpleNamespace(
        lookup_object=lambda name, default=None: objects.get(name, default)
    )
    value._cooperative_sleep = lambda _seconds: None
    return value, toolhead, gcode_move


@pytest.mark.parametrize(
    "absolute_extrude", [pytest.param(True, id="M82"), pytest.param(False, id="M83")]
)
def test_direct_extruder_move_preserves_logical_e_and_mode(absolute_extrude):
    value, toolhead, gcode_move = motion_component(
        absolute_extrude=absolute_extrude
    )
    logical_e_before = (
        gcode_move.last_position[3] - gcode_move.base_position[3]
    ) / gcode_move.extrude_factor

    value._extruder_move(7.0, 8.0)

    logical_e_after = (
        gcode_move.last_position[3] - gcode_move.base_position[3]
    ) / gcode_move.extrude_factor
    assert toolhead.position[3] == pytest.approx(47.0)
    assert gcode_move.last_position[3] == pytest.approx(47.0)
    assert gcode_move.base_position[3] == pytest.approx(22.0)
    assert logical_e_after == pytest.approx(logical_e_before)
    assert gcode_move.absolute_extrude is absolute_extrude
    assert gcode_move.reset_count == 1


def test_direct_extruder_move_synchronizes_e_when_queued_move_raises():
    value, toolhead, gcode_move = motion_component(
        move_error=RuntimeError("simulated queued move failure")
    )
    logical_e_before = (
        gcode_move.last_position[3] - gcode_move.base_position[3]
    ) / gcode_move.extrude_factor

    with pytest.raises(RuntimeError, match="simulated queued move failure"):
        value._extruder_move(-6.0, 10.0)

    logical_e_after = (
        gcode_move.last_position[3] - gcode_move.base_position[3]
    ) / gcode_move.extrude_factor
    assert toolhead.position[3] == pytest.approx(34.0)
    assert gcode_move.last_position[3] == pytest.approx(34.0)
    assert logical_e_after == pytest.approx(logical_e_before)
    assert gcode_move.reset_count == 1


def test_cold_extruder_fails_before_direct_toolhead_move():
    value, toolhead, gcode_move = motion_component(can_extrude=False)

    with pytest.raises(RuntimeError, match="温度未达到可挤出条件"):
        value._extruder_move(5.0, 8.0)

    assert toolhead.moves == []
    assert gcode_move.reset_count == 0


def test_extrusion_preflight_rejects_any_single_move_over_klipper_limit():
    value, toolhead, _gcode_move = motion_component(max_e_dist=50.0)

    with pytest.raises(RuntimeError, match="-50.001 mm 超过"):
        value._preflight_extruder_moves((5.0, 50.0, -50.001))

    assert toolhead.moves == []


def test_lower_sensor_bypass_uses_calibrated_steps_without_probing_lower():
    value = component(
        shared=SharedConfig(
            toolhead_sensor_bypass=True,
            toolhead_sensor_bypass_calibrated=True,
            toolhead_sensor_bypass_load_length=12,
            toolhead_feed_fast_step=5,
            toolhead_to_nozzle_speed=8,
            extruder_sensor_debounce_count=1,
        )
    )
    value.manager = SimpleNamespace(
        _transaction={"action": "select_tool"}, path_busy=True
    )
    probes = []
    moves = []
    responses = []

    def stable(name, expected):
        probes.append((name, expected))
        if name == "lower":
            raise AssertionError("bypassed lower sensor was probed")
        return True

    value._path_sensor_stable = stable
    value._extruder_move = lambda distance, speed: moves.append((distance, speed))
    gcmd = SimpleNamespace(
        error=lambda message: RuntimeError(message),
        respond_info=responses.append,
    )

    value._cmd_path_load_to_toolhead(gcmd)

    assert moves == [(5.0, 8.0), (5.0, 8.0), (2.0, 8.0)]
    assert all(name == "upper" for name, _expected in probes)
    assert responses == [
        "ACE 工具头耗材路径已完成送料；下方耗材传感器按配置旁路。"
    ]


def test_lower_sensor_bypass_rejects_default_sample_before_extruder_motion():
    value = component(
        shared=SharedConfig(
            toolhead_sensor_bypass=True,
            toolhead_sensor_bypass_calibrated=False,
            toolhead_sensor_bypass_load_length=25,
        )
    )
    value.manager = SimpleNamespace(
        _transaction={"action": "select_tool"}, path_busy=True
    )
    value._path_sensor_stable = lambda name, expected: True
    moves = []
    value._extruder_move = lambda distance, speed: moves.append((distance, speed))
    gcmd = SimpleNamespace(error=lambda message: RuntimeError(message))

    with pytest.raises(RuntimeError, match="尚未确认校准"):
        value._cmd_path_load_to_toolhead(gcmd)

    assert moves == []


def test_lower_sensor_bypass_uses_extruder_tracking_and_protect_rejects_slip():
    tokens = []

    class TrackingEncoder:
        @staticmethod
        def get_status():
            return {"armed": True}

        @staticmethod
        def begin_motion(action, device_id, commanded_length, *, validation):
            token = {
                "action": action,
                "device_id": device_id,
                "commanded_length": commanded_length,
                "validation": validation,
            }
            tokens.append(token)
            return token

        @staticmethod
        def finish_motion(token, *, command_completed, commanded_length):
            return {
                **token,
                "command_completed": command_completed,
                "commanded_length": commanded_length,
                "fault": {
                    "code": "encoder_tracking_low",
                    "message": "encoder movement was below the tracking ratio",
                },
            }

    value = component(
        shared=SharedConfig(
            toolhead_sensor_bypass=True,
            toolhead_sensor_bypass_calibrated=True,
            toolhead_sensor_bypass_load_length=25,
            toolhead_feed_fast_step=5,
            encoder_mode="protect",
        )
    )
    value.encoder = TrackingEncoder()
    value.manager = SimpleNamespace(
        _transaction={"action": "select_tool"}, path_busy=True
    )
    value._path_sensor_stable = lambda name, expected: name == "upper" and expected
    value._extruder_move = lambda _distance, _speed: None
    gcmd = SimpleNamespace(
        error=lambda message: RuntimeError(message),
        respond_info=lambda _message: None,
    )

    with pytest.raises(RuntimeError, match="移动比例低于"):
        value._cmd_path_load_to_toolhead(gcmd)

    assert tokens == [
        {
            "action": "extruder_load",
            "device_id": "extruder",
            "commanded_length": 25.0,
            "validation": "tracking",
        }
    ]


@pytest.mark.parametrize("command_name", ["load", "unload"])
@pytest.mark.parametrize("phase", ["start", "finish"])
def test_protect_encoder_errors_become_path_gcode_errors(command_name, phase):
    class PathCommandError(Exception):
        pass

    original = ValueError("%s encoder %s failed" % (command_name, phase))
    events = []

    class FailingEncoder:
        @staticmethod
        def get_status():
            return {"armed": True}

        @staticmethod
        def begin_motion(action, device_id, commanded_length, *, validation):
            events.append(("start", action, device_id, commanded_length, validation))
            if phase == "start":
                raise original
            return "tracking-token"

        @staticmethod
        def finish_motion(token, *, command_completed, commanded_length):
            events.append(("finish", token, command_completed, commanded_length))
            if phase == "finish":
                raise original
            return {}

    value = component(
        shared=SharedConfig(
            toolhead_sensor_bypass=True,
            toolhead_sensor_bypass_calibrated=True,
            toolhead_sensor_bypass_load_length=5,
            toolhead_feed_fast_step=5,
            encoder_detection_length=1,
            encoder_mode="protect",
        )
    )
    action = "select_tool" if command_name == "load" else "unload"
    value.manager = SimpleNamespace(
        _transaction={"action": action}, path_busy=True
    )
    value.encoder = FailingEncoder()
    value._path_sensor_stable = lambda name, expected: name == "upper" and expected
    value._extruder_move = lambda _distance, _speed: None
    errors = []

    def command_error(message):
        errors.append(message)
        return PathCommandError(message)

    gcmd = SimpleNamespace(error=command_error, respond_info=lambda _message: None)
    command = (
        value._cmd_path_load_to_toolhead
        if command_name == "load"
        else value._cmd_path_unload_step
    )

    with pytest.raises(PathCommandError, match="参数无效") as caught:
        command(gcmd)

    assert errors == ["ACE Pro 管理中心：参数无效，请检查本次操作填写的内容。"]
    assert caught.value.__cause__ is original
    assert events[0][0] == "start"
    assert [event[0] for event in events] == (
        ["start"] if phase == "start" else ["start", "finish"]
    )


@pytest.mark.parametrize("phase", ["start", "finish"])
def test_monitor_encoder_errors_do_not_block_path_command(phase):
    class FailingEncoder:
        @staticmethod
        def get_status():
            return {"armed": False}

        @staticmethod
        def begin_motion(
            _action, _device_id, _commanded_length, *, validation
        ):
            assert validation == "tracking"
            if phase == "start":
                raise ValueError("monitor encoder start failed")
            return "tracking-token"

        @staticmethod
        def finish_motion(_token, *, command_completed, commanded_length):
            assert command_completed is True
            assert commanded_length == 5
            if phase == "finish":
                raise ValueError("monitor encoder finish failed")
            return {}

    value = component(
        shared=SharedConfig(
            toolhead_sensor_bypass=True,
            toolhead_sensor_bypass_calibrated=True,
            toolhead_sensor_bypass_load_length=5,
            toolhead_feed_fast_step=5,
            encoder_mode="monitor",
        )
    )
    value.manager = SimpleNamespace(
        _transaction={"action": "select_tool"}, path_busy=True
    )
    value.encoder = FailingEncoder()
    value._path_sensor_stable = lambda name, expected: name == "upper" and expected
    value._extruder_move = lambda _distance, _speed: None
    responses = []
    gcmd = SimpleNamespace(
        error=lambda message: AssertionError(message),
        respond_info=responses.append,
    )

    value._cmd_path_load_to_toolhead(gcmd)

    assert responses == [
        "ACE 工具头耗材路径已完成送料；下方耗材传感器按配置旁路。"
    ]


def test_non_bypass_protect_rejects_short_guaranteed_distance_before_motion():
    class PathCommandError(Exception):
        pass

    value = component(
        shared=SharedConfig(
            toolhead_sensor_bypass=False,
            toolhead_sensor_max_feed_length=200,
            toolhead_sensor_to_nozzle=5,
            encoder_detection_length=20,
            encoder_mode="protect",
        )
    )
    value.manager = SimpleNamespace(
        _transaction={"action": "select_tool"}, path_busy=True
    )
    value.encoder = SimpleNamespace()
    probes = []
    moves = []
    value._path_sensor_stable = lambda name, expected: (
        probes.append((name, expected)) or True
    )
    value._extruder_move = lambda distance, speed: moves.append((distance, speed))
    errors = []

    def command_error(message):
        errors.append(message)
        return PathCommandError(message)

    gcmd = SimpleNamespace(error=command_error, respond_info=lambda _message: None)

    with pytest.raises(
        PathCommandError,
        match="至少 20.0 mm.*只能保证移动 5.0 mm",
    ):
        value._cmd_path_load_to_toolhead(gcmd)

    assert probes == [("upper", True)]
    assert moves == []
    assert errors == [
        "ACE Pro 管理中心：ACE 共享编码器保护要求挤出机保证移动至少 20.0 mm；"
        "当前路径只能保证移动 5.0 mm。"
    ]


def test_finish_encoder_tracking_defensively_rejects_short_distance():
    finish_calls = []
    value = component(
        shared=SharedConfig(
            encoder_detection_length=20,
            encoder_mode="protect",
        )
    )
    value.encoder = SimpleNamespace(
        finish_motion=lambda *args, **kwargs: finish_calls.append((args, kwargs))
    )

    with pytest.raises(
        RuntimeError,
        match="至少 20.0 mm.*只能保证移动 5.0 mm",
    ):
        value._finish_encoder_tracking(
            "tracking-token",
            commanded_length=5,
            command_completed=True,
        )

    assert finish_calls == []


def test_encoder_calibration_reporter_writes_chinese_console_counts():
    reporters = []
    responses = []
    value = component()
    value.encoder = SimpleNamespace(
        set_calibration_reporter=reporters.append
    )
    value.gcode = SimpleNamespace(respond_info=responses.append)

    value._bind_encoder_calibration_reporter()
    reporters[0](
        {"increment": 7, "calibration_counts": 42, "total_counts": 158}
    )

    assert responses == [
        "ACE Pro 管理中心：编码器校准计数，本次新增 7，校准累计 42，"
        "硬件累计 158 个脉冲。"
    ]


def test_print_monitor_uses_mcu_time_and_extruder_physical_history():
    calls = []
    extruder = SimpleNamespace(
        find_past_position=lambda print_time: (
            calls.append(("position", print_time)) or 123.5
        )
    )
    objects = {
        "mcu": SimpleNamespace(
            estimated_print_time=lambda eventtime: (
                calls.append(("time", eventtime)) or 42.25
            )
        ),
        "toolhead": SimpleNamespace(get_extruder=lambda: extruder),
    }
    value = component()
    value.printer = SimpleNamespace(
        lookup_object=lambda name, default=None: objects.get(name, default)
    )

    position = value._get_extruder_physical_position(10.0)

    assert position == pytest.approx(123.5)
    assert calls == [("time", 10.0), ("position", 42.25)]


def test_print_monitor_poll_forwards_physical_position_and_print_state():
    updates = []
    value = component()
    value.manager = SimpleNamespace(
        update_encoder_print_monitor=lambda position, **values: updates.append(
            (position, values)
        )
    )
    value.reactor = SimpleNamespace(monotonic=lambda: 50.0)
    value._get_print_state = lambda: "printing"
    value._get_extruder_physical_position = lambda eventtime: eventtime + 1.0

    next_poll = value._poll_encoder_print_monitor(10.0)

    assert updates == [(11.0, {"print_state": "printing"})]
    assert next_poll == pytest.approx(50.25)


def test_required_path_hook_fails_closed_when_macro_is_missing():
    with pytest.raises(RuntimeError, match="必需机器宏.*没有绑定宏"):
        component(machine=MachineConfig(load_to_toolhead_macro=None))._run_machine_hook(
            "load_to_toolhead", {"tool": 0, "device": 0, "slot": 0}
        )


def test_path_hook_can_be_explicitly_disabled_for_bench_protocol_tests():
    component(
        machine=MachineConfig(load_to_toolhead_macro=None),
        shared=SharedConfig(require_path_hooks=False),
    )._run_machine_hook(
        "load_to_toolhead", {"tool": 0, "device": 0, "slot": 0}
    )


def test_manual_mode_can_load_with_commented_wipe_implementation():
    component(machine=MachineConfig(wipe_nozzle_macro=None))._run_machine_hook(
        "wipe_nozzle", {"from": 0, "to": 1}
    )


def test_configured_wipe_hook_receives_tool_context():
    commands = []
    value = component(machine=MachineConfig(wipe_nozzle_macro="_ACE_WIPE_NOZZLE"))
    value.gcode.run_script_from_command = commands.append

    value._run_machine_hook("wipe_nozzle", {"from": 0, "to": 5})

    assert commands == ["_ACE_WIPE_NOZZLE FROM=0 TO=5"]


def test_pause_on_error_hook_is_required_for_automatic_toolchanges():
    with pytest.raises(RuntimeError, match="配置不完整.*没有绑定宏"):
        component(machine=MachineConfig(pause_on_error_macro=None))._validate_machine_hooks(
            ("pause_on_error",)
        )


def test_configured_but_unregistered_machine_macro_is_rejected():
    value = component(
        machine=MachineConfig(load_to_toolhead_macro="ACE_LOAD_TO_TOOLHEAD")
    )
    value.gcode.lookup_command = lambda _name, default=None: default
    with pytest.raises(RuntimeError, match="尚未注册"):
        value._validate_machine_hooks(("load_to_toolhead",))


def test_configured_sensor_pins_create_non_pausing_switch_objects():
    class FileConfig:
        def __init__(self):
            self.sections = {}

        def has_section(self, name):
            return name in self.sections

        def add_section(self, name):
            self.sections[name] = {}

        def set(self, section, key, value):
            self.sections[section][key] = value

    loaded = []
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = SimpleNamespace(
        shared=SharedConfig(
            extruder_sensor_pin="^TGL36:PA2",
            toolhead_sensor_pin="^TGL36:PA5",
            rdm_sensor_name="parking_sensor",
            rdm_sensor_pin="^PC0",
            ace0_hub_sensor_name="ace0_branch_sensor",
            ace0_hub_sensor_pin="^PC1",
            ace1_hub_sensor_name="ace1_branch_sensor",
            ace1_hub_sensor_pin="^PC2",
        ),
        devices=(SimpleNamespace(), SimpleNamespace()),
    )
    value.printer = SimpleNamespace(
        load_object=lambda _config, section: loaded.append(section)
    )
    config = SimpleNamespace(fileconfig=FileConfig())

    value._install_configured_path_sensors(config)

    assert loaded == [
        "filament_switch_sensor extruder_sensor",
        "filament_switch_sensor toolhead_sensor",
        "filament_switch_sensor parking_sensor",
        "filament_switch_sensor ace0_branch_sensor",
        "filament_switch_sensor ace1_branch_sensor",
    ]
    for section in loaded:
        assert config.fileconfig.sections[section]["pause_on_runout"] == "False"


def test_pin_only_path_sensors_create_fixed_internal_objects():
    class FileConfig:
        def __init__(self):
            self.sections = {}

        def has_section(self, name):
            return name in self.sections

        def add_section(self, name):
            self.sections[name] = {}

        def set(self, section, key, value):
            self.sections[section][key] = value

    loaded = []
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = parsed_config_with_sensor_values(
        device_count=2,
        extruder_sensor_pin="^PA0",
        toolhead_sensor_pin="^PA1",
        rdm_sensor_pin="^PA2",
        ace0_hub_sensor_pin="^PA3",
    )
    value.printer = SimpleNamespace(
        load_object=lambda _config, section: loaded.append(section)
    )
    config = SimpleNamespace(fileconfig=FileConfig())

    value._install_configured_path_sensors(config)

    assert loaded == [
        "filament_switch_sensor extruder_sensor",
        "filament_switch_sensor toolhead_sensor",
        "filament_switch_sensor rdm_sensor",
        "filament_switch_sensor ace0_hub_sensor",
    ]
    assert {
        section: values["switch_pin"]
        for section, values in config.fileconfig.sections.items()
    } == {
        "filament_switch_sensor extruder_sensor": "^PA0",
        "filament_switch_sensor toolhead_sensor": "^PA1",
        "filament_switch_sensor rdm_sensor": "^PA2",
        "filament_switch_sensor ace0_hub_sensor": "^PA3",
    }


def test_single_device_does_not_create_first_stage_hub_sensor():
    class FileConfig:
        def __init__(self):
            self.sections = {}

        def has_section(self, name):
            return name in self.sections

        def add_section(self, name):
            self.sections[name] = {}

        def set(self, section, key, value):
            self.sections[section][key] = value

    loaded = []
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = parsed_config_with_sensor_values(
        rdm_sensor_pin="^PA2",
        ace0_hub_sensor_pin="^PA3",
    )
    value.printer = SimpleNamespace(
        load_object=lambda _config, section: loaded.append(section)
    )
    config = SimpleNamespace(fileconfig=FileConfig())

    value._install_configured_path_sensors(config)

    assert loaded == ["filament_switch_sensor rdm_sensor"]


def test_empty_sensor_pins_create_no_runtime_objects():
    class FileConfig:
        def __init__(self):
            self.sections = {}

        def has_section(self, name):
            return name in self.sections

        def add_section(self, name):
            self.sections[name] = {}

        def set(self, section, key, value):
            self.sections[section][key] = value

    loaded = []
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = parsed_config_with_sensor_values()
    value.printer = SimpleNamespace(
        load_object=lambda _config, section: loaded.append(section),
        lookup_object=lambda _section, default=None: default,
    )
    config = SimpleNamespace(fileconfig=FileConfig())

    value._install_configured_path_sensors(config)
    encoder = value._install_configured_encoder(config)

    assert loaded == []
    assert config.fileconfig.sections == {}
    assert encoder is None


def test_configured_encoder_pin_creates_and_configures_shared_encoder_object():
    class FileConfig:
        def __init__(self):
            self.sections = {}

        def has_section(self, name):
            return name in self.sections

        def add_section(self, name):
            self.sections[name] = {}

        def set(self, section, key, value):
            self.sections[section][key] = value

    configured = []
    encoder = SimpleNamespace(
        configure=lambda **values: configured.append(values)
    )
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = SimpleNamespace(
        shared=SharedConfig(
            encoder_sensor_name="shared_motion",
            encoder_sensor_pin="^PC3",
            encoder_resolution=0.5,
            encoder_detection_length=25,
            encoder_min_tracking_ratio=0.7,
            encoder_mode="monitor",
        )
    )
    value.printer = SimpleNamespace(
        load_object=lambda _config, _section: encoder,
        lookup_object=lambda _section, default=None: default,
    )
    config = SimpleNamespace(fileconfig=FileConfig())

    result = value._install_configured_encoder(config)

    section = config.fileconfig.sections["ace_encoder shared_motion"]
    assert result is encoder
    assert section == {
        "encoder_pin": "^PC3",
        "encoder_resolution": "0.5",
        "detection_length": "25",
        "min_tracking_ratio": "0.7",
        "mode": "monitor",
    }
    assert configured == [
        {
            "resolution": 0.5,
            "detection_length": 25,
            "min_tracking_ratio": 0.7,
            "mode": "monitor",
        }
    ]


def test_pin_only_encoder_uses_fixed_shared_encoder_name():
    class FileConfig:
        def __init__(self):
            self.sections = {}

        def has_section(self, name):
            return name in self.sections

        def add_section(self, name):
            self.sections[name] = {}

        def set(self, section, key, value):
            self.sections[section][key] = value

    encoder = SimpleNamespace(configure=lambda **_values: None)
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = parsed_config_with_sensor_values(
        encoder_sensor_pin="^PA10",
        encoder_resolution="0.5",
        encoder_detection_length="25",
        encoder_mode="monitor",
    )
    value.printer = SimpleNamespace(
        load_object=lambda _config, _section: encoder,
        lookup_object=lambda _section, default=None: default,
    )
    config = SimpleNamespace(fileconfig=FileConfig())

    assert value._install_configured_encoder(config) is encoder
    assert "ace_encoder shared_encoder" in config.fileconfig.sections


def test_missing_encoder_configuration_is_optional():
    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value.driver_config = SimpleNamespace(shared=SharedConfig())

    assert value._install_configured_encoder(SimpleNamespace()) is None


def test_v2_inventory_is_migrated_once_with_current_v2_values_preferred(tmp_path):
    save_variables = SimpleNamespace(
        allVariables={
            "ace_inventory": [
                {
                    "status": "ready",
                    "material": "ABSCF",
                    "color": [0, 0, 0],
                    "temp": 260,
                }
            ],
            "ace_inventory_0": [
                {
                    "status": "ready",
                    "material": "ABS",
                    "color": [0, 255, 238],
                    "temp": 260,
                    "rfid": False,
                }
            ],
            "ace_inventory_1": [
                {
                    "status": "ready",
                    "material": "PETG",
                    "color": [23, 20, 173],
                    "temp": 235,
                }
            ],
        }
    )
    commands = []
    printer = SimpleNamespace(
        lookup_object=lambda name, default=None: (
            save_variables if name == "save_variables" else default
        )
    )
    gcode = SimpleNamespace(run_script_from_command=commands.append)
    store = KlipperStateStore(
        printer,
        gcode,
        state_path=tmp_path / "runtime-state.json",
        legacy_path=tmp_path / "saved_variables.cfg",
    )

    assert store.migrate_legacy_inventory(2) is True
    inventory = store.get("inventory")
    assert inventory[0][0] == {
        "material": "ABSCF",
        "color": "#000000",
        "temperature": 260,
        "status": "ready",
    }
    assert inventory[1][0]["color"] == "#1714AD"
    assert commands[0].startswith(
        "SAVE_VARIABLE VARIABLE=ace_v3_inventory VALUE="
    )
    assert store.migrate_legacy_inventory(2) is False
    assert len(commands) == 1


def test_existing_v3_inventory_blocks_legacy_migration(tmp_path):
    current = [[{"material": "ASA", "color": "#123456"}]]
    save_variables = SimpleNamespace(
        allVariables={
            "ace_v3_inventory": current,
            "ace_inventory_0": [
                {"material": "PLA", "color": [255, 255, 255]}
            ],
        }
    )
    commands = []
    printer = SimpleNamespace(
        lookup_object=lambda name, default=None: (
            save_variables if name == "save_variables" else default
        )
    )
    store = KlipperStateStore(
        printer,
        SimpleNamespace(run_script_from_command=commands.append),
        state_path=tmp_path / "runtime-state.json",
        legacy_path=tmp_path / "saved_variables.cfg",
    )

    assert store.migrate_legacy_inventory(1) is False
    assert store.get("inventory") == current
    assert commands == []


def test_inventory_migrates_from_legacy_file_without_save_variables(tmp_path):
    legacy_path = tmp_path / "saved_variables.cfg"
    legacy_path.write_text(
        """[Variables]
ace_inventory = [{'material': 'ABSCF', 'color': [0, 0, 0], 'temp': 260}, {'material': 'ABS', 'color': [0, 0, 0], 'temp': 260}, {'material': 'PETG', 'color': [0, 30, 255], 'temp': 250}, {'material': 'ABS', 'color': [0, 0, 0], 'temp': 265}]
ace_inventory_0 = [{'material': 'PLA', 'color': [255, 255, 255], 'temp': 210}]
""",
        encoding="utf-8",
    )
    state_path = tmp_path / ".ace-driver-v3" / "runtime-state.json"
    commands = []
    printer = SimpleNamespace(
        lookup_object=lambda _name, default=None: default
    )
    gcode = SimpleNamespace(run_script_from_command=commands.append)

    store = KlipperStateStore(
        printer, gcode, state_path=state_path, legacy_path=legacy_path
    )
    assert store.migrate_legacy_inventory(1) is True
    inventory = store.get("inventory")
    assert inventory[0] == [
        {"material": "ABSCF", "color": "#000000", "temperature": 260},
        {"material": "ABS", "color": "#000000", "temperature": 260},
        {"material": "PETG", "color": "#001EFF", "temperature": 250},
        {"material": "ABS", "color": "#000000", "temperature": 265},
    ]
    assert state_path.is_file()
    assert commands == []

    restored = KlipperStateStore(
        printer, gcode, state_path=state_path, legacy_path=legacy_path
    )
    assert restored.migrate_legacy_inventory(1) is False
    assert restored.get("inventory") == inventory
    assert commands == []


def test_default_state_path_uses_klipper_config_directory(tmp_path):
    printer = SimpleNamespace(
        get_start_args=lambda: {"config_file": str(tmp_path / "printer.cfg")},
        lookup_object=lambda _name, default=None: default,
    )
    gcode = SimpleNamespace(run_script_from_command=lambda _command: None)

    store = KlipperStateStore(printer, gcode)
    store.set("inventory", [[{"material": "PETG", "color": "#001EFF"}]])

    state_path = tmp_path / ".ace-driver-v3" / "runtime-state.json"
    assert state_path.is_file()
    restored = KlipperStateStore(printer, gcode)
    assert restored.get("inventory")[0][0]["color"] == "#001EFF"


def test_ace2_bus_initialization_binds_only_configured_uids():
    uids = [(1, 2, 3), (4, 5, 6)]

    class Controller:
        def __init__(self):
            self.index = 0

        def encode_discover(self):
            return b"discover"

        def decode_discovery_response(self, _payload):
            uid = uids[self.index]
            self.index += 1
            return {"result": {"uid": uid}}

        def encode_assignment(self, uid):
            return b"assign:" + bytes(uid)

        def decode_assignment_response(self, _payload):
            return {"ok": True}

        def protocol_for(self, uid):
            return ("bound", uid)

    class Transport:
        def open(self):
            return None

        def request(self, payload):
            return payload

        def request_once(self, payload):
            return payload

    class Device:
        def __init__(self, device_id):
            self.device_id = device_id
            self.bound = None

        def bind_protocol(self, protocol):
            self.bound = protocol

    value = KlipperAceComponent.__new__(KlipperAceComponent)
    value._ace2_controllers = {"bus0": Controller()}
    value._transports = {("ace2", "bus0"): Transport()}
    value.driver_config = SimpleNamespace(
        devices=[
            SimpleNamespace(enabled=True, model="ace2", bus_id="bus0", device_uid="1:2:3", device_id="ace0"),
            SimpleNamespace(enabled=True, model="ace2", bus_id="bus0", device_uid="4:5:6", device_id="ace1"),
        ]
    )
    value.devices = [Device("ace0"), Device("ace1")]
    value._initialize_ace2_buses()
    assert value.devices[0].bound == ("bound", (1, 2, 3))
    assert value.devices[1].bound == ("bound", (4, 5, 6))
