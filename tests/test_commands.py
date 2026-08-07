import pytest

from ace_driver.commands import AceCommands


class FakeGcode:
    def __init__(self):
        self.commands = {}

    def register_command(self, name, handler, desc=None):
        self.commands[name] = handler


class FakeManager:
    devices = [object(), object()]

    def __init__(self):
        self.selected = []
        self.actions = []
        self.notice = None

    def change_tool(self, tool, **kwargs):
        self.selected.append(tool)
        return {"current_tool": tool}

    def handle_tool_command(self, tool):
        self.selected.append(tool)
        if self.notice is not None:
            return {"ignored": True, "notice": self.notice}
        return {"current_tool": tool}

    def perform_action(self, action, params=None, **kwargs):
        self.actions.append((action, params or {}, kwargs))
        return {"ok": True, "action": action}

    def encoder_status(self):
        return {"configured": True, "mode": "monitor"}

    def start_encoder_calibration(self, **options):
        self.actions.append(("encoder_calibration_start", options, {}))
        return {
            "started": True,
            "required_segments": options.get("segments", 3),
            "segment_length": options.get("segment_length", 150.0),
        }

    def finish_encoder_calibration(self, length):
        self.actions.append(("encoder_calibration_finish", {"length": length}, {}))
        return {"calibrated": True, "resolution": 0.5}

    def cancel_encoder_calibration(self):
        self.actions.append(("encoder_calibration_cancel", {}, {}))
        return {"cancelled": True}


class FakeCommand:
    def __init__(self, values=None):
        self.values = values or {}
        self.responses = []

    def get(self, name, default=None):
        return self.values.get(name, default)

    def get_int(self, name, default=None, minval=None, maxval=None):
        value = self.values.get(name, default)
        value = None if value is None else int(value)
        if value is not None and minval is not None and value < minval:
            raise ValueError(name)
        if value is not None and maxval is not None and value > maxval:
            raise ValueError(name)
        return value

    def get_float(self, name, default=None, minval=None, maxval=None):
        value = self.values.get(name, default)
        value = None if value is None else float(value)
        if value is not None and minval is not None and value < minval:
            raise ValueError(name)
        if value is not None and maxval is not None and value > maxval:
            raise ValueError(name)
        return value

    def respond_info(self, value):
        self.responses.append(value)

    def error(self, value):
        return RuntimeError(value)


def test_registers_full_t0_to_t15_range_and_tr_independent_of_device_count():
    gcode = FakeGcode()
    manager = FakeManager()
    AceCommands(manager, gcode).register()
    assert {"T0", "T7", "T15", "TR", "ACE_CHANGE_TOOL"} <= set(gcode.commands)
    assert "T16" not in gcode.commands
    gcode.commands["T15"](FakeCommand())
    assert manager.selected == [15]


def test_ignored_tool_command_responds_with_notice_without_error():
    gcode = FakeGcode()
    manager = FakeManager()
    manager.notice = {"message": "ACE 自动换料未配置，已忽略 T1。"}
    AceCommands(manager, gcode).register()
    command = FakeCommand()

    gcode.commands["T1"](command)

    assert command.responses == ["ACE 自动换料未配置，已忽略 T1。"]


def test_feed_assist_commands_forward_tool_selection():
    gcode = FakeGcode()
    manager = FakeManager()
    AceCommands(manager, gcode).register()

    gcode.commands["ACE_ENABLE_FEED_ASSIST"](FakeCommand({"TOOL": "T2"}))
    gcode.commands["ACE_ENABLE_FEED_ASSIST"](
        FakeCommand({"TOOL": "T3", "CONFIRM": 1})
    )
    gcode.commands["ACE_DISABLE_FEED_ASSIST"](FakeCommand())

    assert [item[0] for item in manager.actions] == [
        "enable_feed_assist",
        "enable_feed_assist",
        "disable_feed_assist",
    ]
    assert manager.actions[0][1] == {"tool": "T2"}
    assert manager.actions[0][2]["confirmed"] is False
    assert manager.actions[1][2]["confirmed"] is True


def test_encoder_commands_report_status_and_run_two_step_manual_calibration():
    gcode = FakeGcode()
    manager = FakeManager()
    AceCommands(manager, gcode).register()

    status = FakeCommand()
    started = FakeCommand({"START": 1})
    finished = FakeCommand({"LENGTH": 100})
    gcode.commands["ACE_ENCODER_STATUS"](status)
    gcode.commands["ACE_ENCODER_CALIBRATE"](started)
    gcode.commands["ACE_ENCODER_CALIBRATE"](finished)

    assert status.responses[0].startswith("ACE Pro 管理中心：共享编码器状态：")
    assert '"mode": "monitor"' in status.responses[0]
    assert manager.actions[-2:] == [
        ("encoder_calibration_start", {}, {}),
        ("encoder_calibration_finish", {"length": 100.0}, {}),
    ]
    assert "共 3 段，每段目标 150.000 mm" in started.responses[0]


def test_encoder_calibration_reports_segment_progress_and_accepts_start_options():
    class SegmentManager(FakeManager):
        def finish_encoder_calibration(self, length):
            self.actions.append(("encoder_calibration_finish", {"length": length}, {}))
            return {
                "calibrated": False,
                "required_segments": 4,
                "completed_segments": 1,
                "current_segment": 2,
                "segment": {
                    "index": 1,
                    "measured_length": length,
                    "pulses": 300,
                    "mm_per_pulse": 0.5,
                },
            }

    gcode = FakeGcode()
    manager = SegmentManager()
    AceCommands(manager, gcode).register()
    started = FakeCommand(
        {"START": 1, "SEGMENTS": 4, "SEGMENT_LENGTH": 175}
    )
    recorded = FakeCommand({"LENGTH": 150})

    gcode.commands["ACE_ENCODER_CALIBRATE"](started)
    gcode.commands["ACE_ENCODER_CALIBRATE"](recorded)

    assert manager.actions == [
        (
            "encoder_calibration_start",
            {"segments": 4, "segment_length": 175.0},
            {},
        ),
        ("encoder_calibration_finish", {"length": 150.0}, {}),
    ]
    assert "共 4 段，每段目标 175.000 mm" in started.responses[0]
    assert "第 1/4 段已记录" in recorded.responses[0]
    assert "请继续第 2 段" in recorded.responses[0]


def test_encoder_calibration_final_warning_is_explicit():
    class WarningManager(FakeManager):
        def finish_encoder_calibration(self, length):
            return {
                "calibrated": True,
                "quality": "warning",
                "measured_length": 450,
                "pulses": 900,
                "resolution": 0.5,
                "max_deviation_percent": 7.25,
                "warning": "测试警告",
            }

    gcode = FakeGcode()
    AceCommands(WarningManager(), gcode).register()
    finished = FakeCommand({"LENGTH": 150})

    gcode.commands["ACE_ENCODER_CALIBRATE"](finished)

    assert "警告后保存" in finished.responses[0]
    assert "段间最大偏差 7.25%" in finished.responses[0]
    assert "测试警告" in finished.responses[0]


def test_encoder_calibration_requires_exactly_one_step_parameter():
    gcode = FakeGcode()
    AceCommands(FakeManager(), gcode).register()

    with pytest.raises(RuntimeError, match="必须且只能填写一项"):
        gcode.commands["ACE_ENCODER_CALIBRATE"](FakeCommand())
    with pytest.raises(RuntimeError, match="必须且只能填写一项"):
        gcode.commands["ACE_ENCODER_CALIBRATE"](
            FakeCommand({"START": 1, "LENGTH": 100})
        )
    with pytest.raises(RuntimeError, match="只能与 START=1 同时使用"):
        gcode.commands["ACE_ENCODER_CALIBRATE"](
            FakeCommand({"LENGTH": 100, "SEGMENTS": 3})
        )


def test_encoder_calibration_length_is_finite_and_bounded():
    gcode = FakeGcode()
    manager = FakeManager()
    AceCommands(manager, gcode).register()

    for value in (0, 0.009, 2000.01, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(RuntimeError):
            gcode.commands["ACE_ENCODER_CALIBRATE"](
                FakeCommand({"LENGTH": value})
            )

    assert manager.actions == []


def test_command_error_boundary_never_exposes_unknown_english_message():
    class FailingManager(FakeManager):
        def perform_action(self, action, params=None, **kwargs):
            raise RuntimeError("raw backend failure must stay hidden")

    gcode = FakeGcode()
    AceCommands(FailingManager(), gcode).register()

    with pytest.raises(RuntimeError) as caught:
        gcode.commands["ACE_FEED"](
            FakeCommand({"TOOL": "T0", "LENGTH": 10, "SPEED": 20})
        )

    message = str(caught.value)
    assert "raw backend failure" not in message
    assert "ACE Pro 管理中心" in message
    assert "操作未完成" in message
