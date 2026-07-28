import importlib.util
import json
import pathlib
import sys
import types
import unittest


serial_module = types.ModuleType("serial")
serial_module.SerialException = type("SerialException", (Exception,), {})
serial_tools = types.ModuleType("serial.tools")
serial_list_ports = types.ModuleType("serial.tools.list_ports")
serial_list_ports.comports = lambda: []
serial_tools.list_ports = serial_list_ports
serial_module.tools = serial_tools
sys.modules.setdefault("serial", serial_module)
sys.modules.setdefault("serial.tools", serial_tools)
sys.modules.setdefault("serial.tools.list_ports", serial_list_ports)

MODULE_PATH = pathlib.Path(__file__).parents[1] / "extras" / "ace.py"
SPEC = importlib.util.spec_from_file_location("ace_calibration_driver", MODULE_PATH)
ace_driver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ace_driver)


class FakeGcode:
    def __init__(self):
        self.scripts = []
        self.messages = []

    def run_script_from_command(self, script):
        self.scripts.append(script)

    def respond_info(self, message):
        self.messages.append(message)


class FailingSaveGcode(FakeGcode):
    def run_script_from_command(self, script):
        self.scripts.append(script)
        if script.startswith("SAVE_VARIABLE VARIABLE=ace_calibration"):
            raise RuntimeError("simulated saved_variables write failure")


class FailingScriptGcode(FakeGcode):
    def __init__(self, failing_script):
        super().__init__()
        self.failing_script = failing_script

    def run_script_from_command(self, script):
        self.scripts.append(script)
        if script == self.failing_script:
            raise RuntimeError("simulated %s failure" % script)


class FakeGcmd:
    def __init__(self, values=None):
        self.values = values or {}
        self.messages = []

    def get_int(self, name, default=None, **_kwargs):
        value = self.values.get(name, default)
        if value is None:
            raise ValueError("missing %s" % name)
        return int(value)

    def respond_info(self, message):
        self.messages.append(message)

    def error(self, message):
        return RuntimeError(message)


class FakePrintStats:
    def __init__(self, state="standby"):
        self.state = state

    def get_status(self, _eventtime):
        return {"state": self.state}


class FakeReactor:
    def monotonic(self):
        return 0.0

    def pause(self, _when):
        return 0.0


class FakePrinter:
    def __init__(self, print_state="standby"):
        self.print_stats = FakePrintStats(print_state)
        self.objects = {}

    def lookup_object(self, name, default=None):
        if name == "print_stats":
            return self.print_stats
        return self.objects.get(name, default)

    def command_error(self, message):
        return RuntimeError(message)


def make_state_ace(current_index=-1, legacy_position=None, saved_positions=None):
    ace = object.__new__(ace_driver.BunnyAce)
    ace.variables = {"ace_current_index": current_index}
    if legacy_position is not None:
        ace.variables["ace_filament_pos"] = legacy_position
    if saved_positions is not None:
        ace.variables["ace_slot_positions"] = saved_positions
    ace.gcode = FakeGcode()
    return ace


def make_calibration_data_ace(record=None, bowden=190.0, margin=20.0):
    ace = make_state_ace()
    ace.bowden_tube_length = bowden
    ace.five_way_parking_margin = margin
    ace.parking_sensor_enabled = False
    ace.parking_sensor_position = "after_five_way"
    ace.parking_sensor_clear_move_length = 75.0
    ace.parking_sensor_debounce_count = 3
    ace.calibration_max_retract_length = 1500.0
    if record is not None:
        ace.variables["ace_calibration"] = json.dumps(record)
    return ace


def make_motion_ace(trigger_after_feed_calls=2):
    ace = make_calibration_data_ace(bowden=10.0, margin=2.0)
    ace._load_slot_positions()
    ace.printer = FakePrinter()
    ace.reactor = FakeReactor()
    ace._connected = True
    ace._info = {"status": "ready"}
    ace._motion_owner = None
    ace._connection_state = "connected"
    ace._toolchange_context = None
    ace._calibration_preview = None
    ace._calibration_phase = "idle"
    ace._calibration_last_error = ""
    ace.calibration_speed = 25.0
    ace.calibration_chunk_length = 5.0
    ace.calibration_final_chunk_length = 2.0
    ace.toolchange_load_length = 20.0
    ace.feed_slip_compensation_length = 0.0
    ace.feed_speed = 80
    ace.retract_speed = 80
    ace.retract_fast_speed = 120.0
    ace.retract_parking_speed = 25.0
    ace.feed_lengths = []

    def sensor_present(name):
        if name == "extruder_sensor":
            return len(ace.feed_lengths) >= trigger_after_feed_calls
        return False

    ace._sensor_present = sensor_present
    ace._feed = lambda _index, length, _speed, stop_sensor=None: (
        ace.feed_lengths.append(float(length)) or {})
    ace.wait_ace_ready = lambda timeout=None: None
    return ace


def make_retract_motion_ace(clear_after_distance=7.0):
    ace = make_motion_ace(trigger_after_feed_calls=99)
    ace._calibration_preview = {
        "phase": "feed_complete",
        "source_slot": 0,
        "feed_completed": 15.0,
        "feed_upper_bound": 20.0,
        "parking_distance": 12.0,
        "bowden_tube_length": 10.0,
        "parking_margin": 2.0,
    }
    ace._calibration_phase = "feed_complete"
    ace.slot_positions[0] = "upper_sensor"
    ace.variables["ace_current_index"] = 0
    ace.retract_lengths = []

    def sensor_present(name):
        if name == "extruder_sensor":
            return sum(ace.retract_lengths) < clear_after_distance
        return False

    ace._sensor_present = sensor_present
    ace._retract = lambda _index, length, _speed: (
        ace.retract_lengths.append(float(length)) or {})
    return ace


def make_preload_ace(confirm=1, print_state="standby", upper=False,
                     lower=False, position="unknown", current_index=-1):
    ace = make_motion_ace(trigger_after_feed_calls=99)
    ace.printer = FakePrinter(print_state)
    ace.variables["ace_current_index"] = current_index
    ace.slot_positions = ["unknown"] * 4
    if 0 <= current_index < 4:
        ace.slot_positions[current_index] = position
    ace._preload_upper = bool(upper)
    ace._preload_lower = bool(lower)
    ace.motion_calls = []
    ace.cold_extruder_steps = []
    ace.feed_fast_speed = 160.0
    ace.feed_speed = 80
    ace.retract_speed = 80
    ace.retract_fast_speed = 120.0
    ace.toolchange_retract_length = 1200.0
    ace._feed_assist_index = -1
    ace._connection_pause_owned = False
    ace.toolhead_feed_fast_length = 10.0
    ace.toolhead_feed_fast_step = 5.0
    ace.toolhead_feed_fast_speed = 8.0
    ace.toolhead_feed_slow_step = 1.0
    ace.toolhead_feed_slow_speed = 5.0
    ace.toolhead_sensor_max_feed_length = 20.0
    ace.toolhead_sensor_to_nozzle_length = 80.0
    ace._info["slots"] = [{"status": "ready"} for _ in range(4)]
    ace.inventory = [{"status": "ready"} for _ in range(4)]

    def sensor_present(name):
        if name == "extruder_sensor":
            return ace._preload_upper
        if name == "toolhead_sensor":
            return ace._preload_lower
        return False

    def feed_until_sensor(index, sensor_name, length, speed, message):
        ace.motion_calls.append(
            ("ace_feed", index, sensor_name, length, speed, message))
        ace._preload_upper = True
        return 10.0

    def cold_extruder_move(length, speed):
        ace.motion_calls.append(("cold_extruder", length, speed))
        ace.cold_extruder_steps.append(float(length))
        if len([call for call in ace.motion_calls
                if call[0] == "cold_extruder" and call[1] > 0]) >= 2:
            ace._preload_lower = True

    ace._sensor_present = sensor_present
    ace._feed_until_sensor = feed_until_sensor
    ace._enable_feed_assist = lambda index: ace.motion_calls.append(
        ("enable_assist", index))
    def disable_feed_assist(index, **_kwargs):
        ace.motion_calls.append(("disable_assist", index))
        ace._feed_assist_index = -1

    ace._disable_feed_assist = disable_feed_assist
    def retract_in_chunks(index, length, speed, phase):
        ace.motion_calls.append(
            ("ace_retract", index, float(length), speed, phase))
        ace._preload_upper = False

    ace._retract_in_chunks = retract_in_chunks
    ace._cold_extruder_move = cold_extruder_move
    ace._save_current_index = lambda index: ace.variables.__setitem__(
        "ace_current_index", index)
    gcmd = FakeGcmd({"INDEX": 0, "CONFIRM": confirm})
    return ace, gcmd


class FakeRunoutHelper:
    def __init__(self, present=False):
        self.filament_present = present


class FakeFilamentSensor:
    def __init__(self, present=False):
        self.runout_helper = FakeRunoutHelper(present)


class FakeGcodeMove:
    def __init__(self):
        self.reset_count = 0

    def reset_last_position(self):
        self.reset_count += 1


class FakeToolheadStatus:
    def get_status(self, _eventtime):
        return {"homed_axes": "xyz"}


class FakeIdleTimeout:
    def __init__(self, state="Ready"):
        self.state = state

    def get_status(self, _eventtime):
        return {"state": self.state}


def make_same_tool_ace(position="toolhead", upper=True, lower=True):
    ace, _gcmd = make_preload_ace(
        upper=upper, lower=lower, position=position, current_index=0)
    ace.printer.objects["filament_switch_sensor extruder_sensor"] = (
        FakeFilamentSensor(upper))
    ace.printer.objects["gcode_move"] = FakeGcodeMove()
    ace._check_endstop_state = lambda name: (
        ace._preload_lower if name == "toolhead_sensor"
        else ace._preload_upper)
    ace._pending_toolchange_recovery = None
    ace._pending_feed_assist_restore = -1
    ace._toolchange_context = None
    ace._toolchange_last_error = None
    ace._park_in_progress = False
    ace.endless_spool_enabled = False
    ace.endless_spool_runout_detected = False
    ace._complete_toolchange_recovery = lambda: None
    ace._cancel_toolchange_recovery = lambda: None
    ace._extruder_move = lambda length, speed: ace.motion_calls.append(
        ("heated_extruder", float(length), float(speed)))
    ace.toolhead_to_nozzle_speed = 5.0
    return ace, FakeGcmd({"TOOL": 0})


def make_cross_tool_ace():
    ace, _gcmd = make_same_tool_ace(
        position="nozzle", upper=True, lower=True)
    ace.slot_positions[1] = "preload_parked_estimated"
    ace.calibration_record = make_calibration_record(
        feed_completed=15.0,
        feed_upper_bound=20.0,
        bowden_tube_length=10.0,
        parking_margin=2.0,
        parking_distance=12.0)
    ace.retract_calls = []
    upper_sensor = ace.printer.objects[
        "filament_switch_sensor extruder_sensor"]

    def extruder_move(length, speed):
        ace.motion_calls.append(
            ("heated_extruder", float(length), float(speed)))
        if length < 0:
            upper_sensor.runout_helper.filament_present = False
            ace._preload_upper = False
            ace._preload_lower = False

    def retract(index, length, speed):
        ace.retract_calls.append(
            ("retract", index, float(length), float(speed)))
        return {}

    def retract_in_chunks(index, length, speed, phase):
        ace.retract_calls.append(
            ("park", index, float(length), float(speed), phase))

    def park_to_toolhead(index, _gcmd, _endless):
        ace.motion_calls.append(("load_target", index))
        ace._set_slot_position(index, "nozzle", persist=False)
        ace.variables["ace_filament_pos"] = "nozzle"

    ace._extruder_move = extruder_move
    ace._retract = retract
    ace._retract_in_chunks = retract_in_chunks
    ace._park_to_toolhead = park_to_toolhead
    return ace, FakeGcmd({"TOOL": 1})


def make_calibration_record(**overrides):
    record = {
        "format_version": 1,
        "valid": True,
        "feed_completed": 1200.0,
        "feed_upper_bound": 1205.0,
        "sensor_clear_distance": 10.0,
        "parking_distance": 1035.0,
        "bowden_tube_length": 190.0,
        "parking_margin": 20.0,
        "source_slot": 0,
        "measured_at": 1234567890.0,
    }
    record.update(overrides)
    return record


class AceSlotPositionTests(unittest.TestCase):
    def test_legacy_nozzle_migrates_only_to_current_slot(self):
        ace = make_state_ace(current_index=1, legacy_position="nozzle")

        ace._load_slot_positions()

        self.assertEqual(
            ace.slot_positions,
            ["unknown", "nozzle", "unknown", "unknown"],
        )

    def test_legacy_splitter_without_current_slot_does_not_guess_identity(self):
        ace = make_state_ace(current_index=-1, legacy_position="spliter")

        ace._load_slot_positions()

        self.assertEqual(ace.slot_positions, ["unknown"] * 4)

    def test_saved_positions_are_loaded_independently(self):
        saved = [
            "preload_parked_estimated",
            "unknown",
            "toolhead",
            "internal_or_unknown",
        ]
        ace = make_state_ace(saved_positions=json.dumps(saved))

        ace._load_slot_positions()

        self.assertEqual(ace.slot_positions, saved)

    def test_two_slots_can_retain_independent_positions(self):
        ace = make_state_ace()
        ace._load_slot_positions()

        ace._set_slot_position(
            0, "preload_parked_estimated", persist=False)
        ace._set_slot_position(2, "nozzle", persist=False)

        self.assertEqual(ace.slot_positions[0], "preload_parked_estimated")
        self.assertEqual(ace.slot_positions[2], "nozzle")
        self.assertEqual(ace.gcode.scripts, [])

    def test_persisted_position_update_uses_json_saved_variable(self):
        ace = make_state_ace()
        ace._load_slot_positions()

        ace._set_slot_position(3, "toolhead")

        self.assertEqual(ace.variables["ace_slot_positions"][3], "toolhead")
        self.assertEqual(len(ace.gcode.scripts), 1)
        self.assertIn(
            "SAVE_VARIABLE VARIABLE=ace_slot_positions",
            ace.gcode.scripts[0],
        )


class AceCalibrationDataTests(unittest.TestCase):
    def test_parking_sensor_position_requires_supported_value(self):
        self.assertEqual(
            ace_driver.normalize_parking_sensor_position('after_five_way'),
            'after_five_way',
        )
        with self.assertRaises(ValueError):
            ace_driver.normalize_parking_sensor_position('sideways')

    def test_parking_sensor_correction_uses_retract_direction(self):
        self.assertEqual(
            ace_driver.calculate_sensor_parking_correction(
                'after_five_way', 75),
            ('retract', 75),
        )
        self.assertEqual(
            ace_driver.calculate_sensor_parking_correction(
                'before_five_way', 40),
            ('feed', 40),
        )

    def test_feed_calibration_does_not_count_feed_request_as_distance(self):
        ace = make_motion_ace(trigger_after_feed_calls=1)
        ace.parking_sensor_enabled = True
        old_sensor_present = ace._sensor_present
        ace._sensor_present = lambda name: (
            bool(ace.feed_lengths) if name == "parking_sensor"
            else old_sensor_present(name))
        old_feed = ace._feed
        ace._feed = lambda *args, **kwargs: (
            old_feed(*args, **kwargs) or {"stopped_by_sensor": True})

        preview = ace._calibrate_feed(0)

        self.assertEqual(ace.feed_lengths, [20.0])
        self.assertEqual(preview['feed_completed'], 0.0)
        self.assertEqual(preview['feed_upper_bound'], 0.0)
        self.assertEqual(preview['mode'], 'parking_sensor')
        self.assertEqual(preview['phase'], 'feed_complete')

    def test_sensor_feed_requires_parking_sensor_to_detect_filament(self):
        ace = make_motion_ace(trigger_after_feed_calls=1)
        ace.parking_sensor_enabled = True
        ace._feed = lambda _index, length, _speed, stop_sensor=None: (
            ace.feed_lengths.append(float(length))
            or {"stopped_by_sensor": True})

        with self.assertRaisesRegex(RuntimeError, "五通传感器未检测到耗材"):
            ace._calibrate_feed(0)

        self.assertEqual(ace.feed_lengths, [20.0])
        self.assertIsNone(ace._calibration_preview)

    def test_parking_distance_uses_feed_upper_bound_bowden_and_margin(self):
        result = ace_driver.calculate_parking_distance(
            1205, 190, 20, 1600)

        self.assertEqual(result, 1035.0)

    def test_parking_distance_rejects_non_positive_result(self):
        with self.assertRaises(ValueError):
            ace_driver.calculate_parking_distance(100, 190, 20, 1600)

    def test_parking_distance_rejects_result_above_motion_limit(self):
        with self.assertRaises(ValueError):
            ace_driver.calculate_parking_distance(2000, 190, 20, 1600)

    def test_calibration_invalidates_when_bowden_changes(self):
        record = make_calibration_record(bowden_tube_length=190.0)

        self.assertFalse(
            ace_driver.calibration_is_valid(record, 200.0, 20.0, 1))

    def test_calibration_invalidates_when_margin_or_version_changes(self):
        record = make_calibration_record()

        self.assertFalse(
            ace_driver.calibration_is_valid(record, 190.0, 25.0, 1))
        self.assertFalse(
            ace_driver.calibration_is_valid(record, 190.0, 20.0, 2))

    def test_valid_calibration_record_matches_current_config(self):
        record = make_calibration_record()

        self.assertTrue(
            ace_driver.calibration_is_valid(record, 190.0, 20.0, 1))

    def test_calibration_rejects_tampered_parking_distance(self):
        record = make_calibration_record(parking_distance=999.0)

        self.assertFalse(
            ace_driver.calibration_is_valid(record, 190.0, 20.0, 1))

    def test_valid_saved_record_is_loaded(self):
        record = make_calibration_record()
        ace = make_calibration_data_ace(record=record)

        ace._load_calibration_record()

        self.assertEqual(ace.calibration_record, record)
        self.assertTrue(ace.calibration_valid)

    def test_stale_saved_record_is_kept_but_marked_invalid(self):
        record = make_calibration_record(bowden_tube_length=190.0)
        ace = make_calibration_data_ace(record=record, bowden=200.0)

        ace._load_calibration_record()

        self.assertEqual(ace.calibration_record, record)
        self.assertFalse(ace.calibration_valid)

    def test_save_calibration_record_persists_json(self):
        record = make_calibration_record()
        ace = make_calibration_data_ace()
        ace._load_calibration_record()

        ace._save_calibration_record(record)

        self.assertEqual(ace.variables["ace_calibration"], record)
        self.assertTrue(ace.calibration_valid)
        self.assertIn(
            "SAVE_VARIABLE VARIABLE=ace_calibration",
            ace.gcode.scripts[-1],
        )
        self.assertIn("True", ace.gcode.scripts[-1])
        self.assertNotIn("true", ace.gcode.scripts[-1])

    def test_save_rejects_record_for_different_config(self):
        ace = make_calibration_data_ace(bowden=200.0)
        ace._load_calibration_record()

        with self.assertRaises(ValueError):
            ace._save_calibration_record(make_calibration_record())

    def test_save_failure_does_not_mark_calibration_as_persisted(self):
        record = make_calibration_record()
        ace = make_calibration_data_ace()
        ace._load_calibration_record()
        ace.gcode = FailingSaveGcode()

        with self.assertRaisesRegex(RuntimeError, "saved_variables write failure"):
            ace._save_calibration_record(record)

        self.assertIsNone(ace.calibration_record)
        self.assertFalse(ace.calibration_valid)
        self.assertNotIn("ace_calibration", ace.variables)


class AceCalibrationMotionTests(unittest.TestCase):
    def test_combined_calibration_runs_feed_then_retract(self):
        ace = make_retract_motion_ace()
        ace._calibrate_feed = lambda index: ace._calibration_preview.update({
            "phase": "feed_complete",
            "source_slot": index,
        }) or dict(ace._calibration_preview)
        ace._calibrate_retract = lambda: ace._calibration_preview.update({
            "phase": "retract_complete",
            "bowden_tube_length": 190.0,
        }) or dict(ace._calibration_preview)
        ace._calibration_preview = {"phase": "idle", "source_slot": 0}
        ace._calibration_phase = "idle"

        result = ace._calibrate_combined(0)

        self.assertEqual(result["phase"], "retract_complete")
        self.assertEqual(result["bowden_tube_length"], 190.0)

    def test_calibrate_feed_without_confirm_only_previews(self):
        ace = make_motion_ace()
        gcmd = FakeGcmd({"INDEX": 0, "CONFIRM": 0})

        ace.cmd_ACE_CALIBRATE_FEED(gcmd)

        self.assertEqual(ace.feed_lengths, [])
        self.assertTrue(any("CONFIRM=1" in message
                            for message in gcmd.messages))

    def test_calibrate_feed_counts_completed_chunks_and_upper_bound(self):
        ace = make_motion_ace(trigger_after_feed_calls=2)

        preview = ace._calibrate_feed(0)

        self.assertEqual(ace.feed_lengths, [5.0, 5.0])
        self.assertEqual(preview["feed_completed"], 5.0)
        self.assertEqual(preview["feed_upper_bound"], 10.0)
        self.assertEqual(preview["phase"], "feed_complete")
        self.assertEqual(ace.slot_positions[0], "upper_sensor")

    def test_uncertain_feed_discards_preview_and_does_not_retry_chunk(self):
        ace = make_motion_ace(trigger_after_feed_calls=99)

        def uncertain_feed(_index, length, _speed, stop_sensor=None):
            ace.feed_lengths.append(float(length))
            return {"uncertain": True}

        ace._feed = uncertain_feed

        with self.assertRaises(RuntimeError):
            ace._calibrate_feed(0)

        self.assertEqual(ace.feed_lengths, [5.0])
        self.assertIsNone(ace._calibration_preview)
        self.assertEqual(ace.slot_positions[0], "unknown")

    def test_calibrate_retract_without_confirm_only_previews(self):
        ace = make_retract_motion_ace()
        gcmd = FakeGcmd({"CONFIRM": 0})

        ace.cmd_ACE_CALIBRATE_RETRACT(gcmd)

        self.assertEqual(ace.retract_lengths, [])
        self.assertTrue(any("CONFIRM=1" in message
                            for message in gcmd.messages))

    def test_calibrate_retract_records_sensor_clear_and_parking_distance(self):
        ace = make_retract_motion_ace(clear_after_distance=7.0)

        preview = ace._calibrate_retract()

        self.assertEqual(ace.retract_lengths, [5.0, 5.0, 2.0])
        self.assertEqual(preview["sensor_clear_completed"], 5.0)
        self.assertEqual(preview["sensor_clear_upper_bound"], 10.0)
        self.assertEqual(preview["retract_distance"], 12.0)
        self.assertEqual(preview["upper_to_parking_sensor_distance"], 0.0)
        self.assertEqual(preview["upper_to_parking_distance"], 12.0)
        self.assertEqual(preview["phase"], "retract_complete")
        self.assertEqual(
            ace.slot_positions[0], "preload_parked_estimated")
        self.assertEqual(ace.variables["ace_current_index"], -1)

    def test_sensor_guided_retract_stops_then_adds_only_75mm(self):
        ace = make_retract_motion_ace(clear_after_distance=99.0)
        ace.parking_sensor_enabled = True
        ace.parking_sensor_clear_move_length = 75.0
        ace.parking_sensor_debounce_count = 3
        ace.calibration_max_retract_length = 1500.0
        ace._parking_present = True
        calls = []

        def sensor_present(name):
            if name == "extruder_sensor":
                return ace._parking_present
            if name == "parking_sensor":
                return ace._parking_present
            return False

        def retract(_index, length, speed, **kwargs):
            calls.append((float(length), float(speed), kwargs))
            if kwargs.get("stop_sensor") == "parking_sensor":
                ace._parking_present = False
                return {"stopped_by_sensor": True}
            return {}

        ace._sensor_present = sensor_present
        ace._retract = retract

        preview = ace._calibrate_retract()

        self.assertEqual([call[0] for call in calls], [5.0, 75.0])
        self.assertEqual(calls[0][2]["stop_when_present"], False)
        self.assertEqual(calls[0][2]["stop_debounce_count"], 3)
        self.assertEqual(preview["mode"], "parking_sensor")
        self.assertEqual(preview["parking_distance"], 75.0)
        self.assertEqual(preview["parking_offset"], 75.0)
        self.assertEqual(preview["upper_to_parking_sensor_distance"], 5.0)
        self.assertEqual(preview["upper_to_parking_distance"], 80.0)
        self.assertTrue(preview["parking_sensor_cleared"])

    def test_sensor_guided_retract_rejects_uncertain_final_offset(self):
        ace = make_retract_motion_ace(clear_after_distance=99.0)
        ace.parking_sensor_enabled = True
        ace.parking_sensor_clear_move_length = 75.0
        ace.calibration_max_retract_length = 1500.0
        ace._parking_present = True

        def sensor_present(name):
            if name in ("extruder_sensor", "parking_sensor"):
                return ace._parking_present
            return False

        def retract(_index, _length, _speed, **kwargs):
            if kwargs.get("stop_sensor") == "parking_sensor":
                ace._parking_present = False
                return {"stopped_by_sensor": True}
            return {"uncertain": True}

        ace._sensor_present = sensor_present
        ace._retract = retract

        with self.assertRaisesRegex(RuntimeError, "连接状态不确定"):
            ace._calibrate_retract()

        self.assertIsNone(ace._calibration_preview)
        self.assertEqual(ace._calibration_phase, "failed")

    def test_calibration_preflight_rejects_material_at_parking_sensor(self):
        ace = make_motion_ace()
        ace.parking_sensor_enabled = True
        ace._sensor_present = lambda name: name == "parking_sensor"

        with self.assertRaisesRegex(RuntimeError, "五通传感器"):
            ace._require_calibration_preflight()

    def test_calibration_save_without_confirm_does_not_persist(self):
        ace = make_retract_motion_ace()
        ace._calibration_preview["phase"] = "retract_complete"
        ace._calibration_preview["sensor_clear_completed"] = 5.0
        ace._calibration_preview["sensor_clear_upper_bound"] = 10.0
        ace._calibration_preview["retract_distance"] = 12.0
        gcmd = FakeGcmd({"CONFIRM": 0})

        ace.cmd_ACE_CALIBRATION_SAVE(gcmd)

        self.assertNotIn("ace_calibration", ace.variables)

    def test_calibration_save_persists_completed_preview(self):
        ace = make_retract_motion_ace()
        ace._calibration_preview["phase"] = "retract_complete"
        ace._calibration_preview["sensor_clear_completed"] = 5.0
        ace._calibration_preview["sensor_clear_upper_bound"] = 10.0
        ace._calibration_preview["retract_distance"] = 12.0
        ace.retract_lengths.append(7.0)
        gcmd = FakeGcmd({"CONFIRM": 1})

        ace.cmd_ACE_CALIBRATION_SAVE(gcmd)

        record = ace.variables["ace_calibration"]
        self.assertEqual(record["format_version"], 1)
        self.assertEqual(record["parking_distance"], 12.0)
        self.assertTrue(record["valid"])
        self.assertEqual(ace._calibration_phase, "saved")

    def test_calibration_save_rejects_changed_sensor_state(self):
        ace = make_retract_motion_ace()
        ace._calibration_preview["phase"] = "retract_complete"
        ace._calibration_preview["sensor_clear_completed"] = 5.0
        ace._calibration_preview["sensor_clear_upper_bound"] = 10.0
        ace._calibration_preview["retract_distance"] = 12.0
        gcmd = FakeGcmd({"CONFIRM": 1})

        with self.assertRaisesRegex(RuntimeError, "上下传感器必须均无料"):
            ace.cmd_ACE_CALIBRATION_SAVE(gcmd)

        self.assertNotIn("ace_calibration", ace.variables)


class AcePreloadTests(unittest.TestCase):
    def test_preload_without_confirm_never_moves(self):
        ace, gcmd = make_preload_ace(confirm=0)

        ace.cmd_ACE_PRELOAD(gcmd)

        self.assertEqual(ace.motion_calls, [])
        self.assertTrue(any("CONFIRM=1" in message
                            for message in gcmd.messages))

    def test_preload_is_blocked_while_printing(self):
        ace, gcmd = make_preload_ace(print_state="printing")
        ace.slot_positions[0] = "preload_parked_estimated"

        with self.assertRaises(RuntimeError):
            ace.cmd_ACE_PRELOAD(gcmd)

        self.assertEqual(ace.motion_calls, [])
        self.assertEqual(
            ace.slot_positions[0], "preload_parked_estimated")

    def test_preload_rejects_lower_sensor_with_unknown_position(self):
        ace, gcmd = make_preload_ace(
            lower=True, position="unknown", current_index=0)

        with self.assertRaises(RuntimeError):
            ace.cmd_ACE_PRELOAD(gcmd)

        self.assertEqual(ace.motion_calls, [])

    def test_cold_preload_stops_on_lower_sensor_without_nozzle_distance(self):
        ace, gcmd = make_preload_ace()

        ace.cmd_ACE_PRELOAD(gcmd)

        self.assertEqual(ace.cold_extruder_steps, [5.0, 5.0])
        self.assertNotIn(
            ace.toolhead_sensor_to_nozzle_length,
            ace.cold_extruder_steps)
        self.assertEqual(ace.slot_positions[0], "toolhead")
        self.assertEqual(ace.variables["ace_current_index"], 0)
        scripts = "\n".join(ace.gcode.scripts)
        self.assertNotIn("_ACE_PRE_TOOLCHANGE", scripts)
        self.assertNotIn("CUT_TIP", scripts)
        self.assertNotIn("M109", scripts)
        self.assertNotIn("G28", scripts)

    def test_preload_clears_known_upper_path_before_loading_target(self):
        ace, gcmd = make_preload_ace(
            upper=True, position="upper_sensor", current_index=1)
        ace.calibration_record = make_calibration_record(
            feed_completed=15.0,
            feed_upper_bound=20.0,
            bowden_tube_length=10.0,
            parking_margin=2.0,
            parking_distance=12.0)

        ace.cmd_ACE_PRELOAD(gcmd)

        retract = next(call for call in ace.motion_calls
                       if call[0] == "ace_retract")
        self.assertEqual(retract[1:3], (1, 12.0))
        self.assertEqual(
            ace.slot_positions[1], "preload_parked_estimated")
        self.assertEqual(ace.slot_positions[0], "toolhead")
        self.assertLess(
            ace.motion_calls.index(retract),
            next(index for index, call in enumerate(ace.motion_calls)
                 if call[0] == "ace_feed"))

    def test_clear_failure_marks_old_slot_unknown_and_preserves_target(self):
        ace, gcmd = make_preload_ace(
            upper=True, position="upper_sensor", current_index=1)
        ace.slot_positions[0] = "preload_parked_estimated"

        def fail_retract(_index, _length, _speed, _phase):
            raise RuntimeError("simulated clear failure")

        ace._retract_in_chunks = fail_retract

        with self.assertRaises(RuntimeError):
            ace.cmd_ACE_PRELOAD(gcmd)

        self.assertEqual(ace.slot_positions[1], "unknown")
        self.assertEqual(
            ace.slot_positions[0], "preload_parked_estimated")


class AceToolchangePositionTests(unittest.TestCase):
    def test_unloaded_state_rejects_physical_filament_without_guessing_slot(self):
        ace, _gcmd = make_same_tool_ace(
            position="unknown", upper=True, lower=False)
        ace.variables["ace_current_index"] = -1
        gcmd = FakeGcmd({"TOOL": -1})

        with self.assertRaisesRegex(RuntimeError, "保存状态为未装载"):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertFalse(any("_ACE_PRE_TOOLCHANGE" in item
                             for item in ace.gcode.scripts))

    def test_toolchange_rejects_another_motion_owner_before_macros(self):
        ace, gcmd = make_cross_tool_ace()
        ace._motion_owner = "距离标定"

        with self.assertRaises(RuntimeError):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertFalse(any("_ACE_PRE_TOOLCHANGE" in item
                             for item in ace.gcode.scripts))

    def test_same_tool_at_toolhead_completes_heated_nozzle_load(self):
        ace, gcmd = make_same_tool_ace(position="toolhead")

        ace.cmd_ACE_CHANGE_TOOL(gcmd)

        scripts = ace.gcode.scripts
        self.assertTrue(any("_ACE_PRE_TOOLCHANGE" in item
                            for item in scripts))
        self.assertTrue(any("_ACE_POST_TOOLCHANGE" in item
                            for item in scripts))
        self.assertFalse(any("CUT_TIP" in item for item in scripts))
        self.assertIn(
            ("heated_extruder", 80.0, 5.0), ace.motion_calls)
        self.assertEqual(ace.slot_positions[0], "nozzle")

    def test_old_tool_parks_and_new_tool_loads_from_estimated_position(self):
        ace, gcmd = make_cross_tool_ace()

        ace.cmd_ACE_CHANGE_TOOL(gcmd)

        parking_call = next(call for call in ace.retract_calls
                            if call[0] == "park")
        self.assertEqual(parking_call[1:3], (0, 12.0))
        self.assertEqual(
            ace.slot_positions[0], "preload_parked_estimated")
        self.assertEqual(ace.slot_positions[1], "nozzle")
        self.assertTrue(any("CUT_TIP" in item
                            for item in ace.gcode.scripts))

    def test_toolhead_position_unloads_without_running_cutter(self):
        ace, gcmd = make_cross_tool_ace()
        ace.slot_positions[0] = "toolhead"
        ace.variables["ace_filament_pos"] = "toolhead"

        ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertFalse(any("CUT_TIP" in item
                             for item in ace.gcode.scripts))
        self.assertEqual(
            ace.slot_positions[0], "preload_parked_estimated")


class AceRuntimeSafetyTests(unittest.TestCase):
    def test_change_spool_without_confirmation_never_moves(self):
        ace, _gcmd = make_cross_tool_ace()
        gcmd = FakeGcmd({"INDEX": 0, "CONFIRM": 0})

        ace.cmd_ACE_CHANGE_SPOOL(gcmd)

        self.assertEqual(ace.retract_calls, [])
        self.assertIsNone(ace._motion_owner)
        self.assertFalse(any("CUT_TIP" in script
                             for script in ace.gcode.scripts))
        self.assertTrue(any("CONFIRM=1" in message
                            for message in gcmd.messages))

    def test_change_spool_rejects_printing_and_paused(self):
        for state in ("printing", "paused"):
            with self.subTest(state=state):
                ace, _gcmd = make_cross_tool_ace()
                ace.printer.print_stats.state = state
                gcmd = FakeGcmd({"INDEX": 0, "CONFIRM": 1})

                with self.assertRaisesRegex(RuntimeError, "打印或暂停"):
                    ace.cmd_ACE_CHANGE_SPOOL(gcmd)

                self.assertEqual(ace.retract_calls, [])
                self.assertIsNone(ace._motion_owner)
                self.assertFalse(any("CUT_TIP" in script
                                     for script in ace.gcode.scripts))

    def test_change_spool_respects_existing_motion_owner(self):
        ace, _gcmd = make_cross_tool_ace()
        ace._motion_owner = "距离标定"

        with self.assertRaises(RuntimeError):
            ace.cmd_ACE_CHANGE_SPOOL(
                FakeGcmd({"INDEX": 0, "CONFIRM": 1}))

        self.assertEqual(ace._motion_owner, "距离标定")
        self.assertEqual(ace.retract_calls, [])

    def test_change_spool_current_slot_does_not_retract_twice(self):
        ace, _gcmd = make_cross_tool_ace()

        ace.cmd_ACE_CHANGE_SPOOL(
            FakeGcmd({"INDEX": 0, "CONFIRM": 1}))

        park_calls = [call for call in ace.retract_calls
                      if call[0] == "park"]
        self.assertEqual(len(park_calls), 1)
        self.assertEqual(park_calls[0][1:3], (0, 1200.0))
        self.assertFalse(any(
            call[0] == "retract" and call[2] == ace.bowden_tube_length
            for call in ace.retract_calls))
        self.assertEqual(ace.variables["ace_current_index"], -1)
        self.assertIsNone(ace._motion_owner)

    def test_change_spool_noncurrent_slot_uses_one_bounded_retract(self):
        ace, _gcmd = make_cross_tool_ace()
        ace.retract_calls = []

        ace.cmd_ACE_CHANGE_SPOOL(
            FakeGcmd({"INDEX": 2, "CONFIRM": 1}))

        self.assertEqual(
            ace.retract_calls,
            [("retract", 2, ace.bowden_tube_length,
              float(ace.retract_speed))],
        )
        self.assertIsNone(ace._motion_owner)

    def test_change_spool_releases_motion_owner_after_failure(self):
        ace, _gcmd = make_cross_tool_ace()
        ace._retract = lambda *_args, **_kwargs: (
            (_ for _ in ()).throw(RuntimeError("simulated spool failure")))

        with self.assertRaisesRegex(RuntimeError, "spool failure"):
            ace.cmd_ACE_CHANGE_SPOOL(
                FakeGcmd({"INDEX": 2, "CONFIRM": 1}))

        self.assertIsNone(ace._motion_owner)

    def test_full_unload_without_confirmation_never_moves(self):
        ace, _gcmd = make_cross_tool_ace()
        gcmd = FakeGcmd({"INDEX": 0, "CONFIRM": 0})

        ace.cmd_ACE_FULL_UNLOAD(gcmd)

        self.assertEqual(ace.retract_calls, [])
        self.assertTrue(any("CONFIRM=1" in message
                            for message in gcmd.messages))

    def test_full_unload_returns_current_slot_to_ace(self):
        ace, _gcmd = make_cross_tool_ace()
        gcmd = FakeGcmd({"INDEX": 0, "CONFIRM": 1})

        ace.cmd_ACE_FULL_UNLOAD(gcmd)

        full_retract = next(call for call in ace.retract_calls
                            if call[0] == "park")
        self.assertEqual(full_retract[1:3], (0, 1200.0))
        self.assertEqual(ace.slot_positions[0], "internal_or_unknown")
        self.assertEqual(ace.variables["ace_current_index"], -1)

    def test_manual_feed_without_confirmation_never_moves(self):
        ace = make_motion_ace()
        gcmd = FakeGcmd({
            "INDEX": 0,
            "LENGTH": 20,
            "SPEED": 10,
            "CONFIRM": 0,
        })

        ace.cmd_ACE_FEED(gcmd)

        self.assertEqual(ace.feed_lengths, [])
        self.assertTrue(any("CONFIRM=1" in message
                            for message in gcmd.messages))

    def test_manual_retract_without_confirmation_never_moves(self):
        ace = make_motion_ace()
        ace.retract_lengths = []
        ace._retract = lambda _index, length, _speed: (
            ace.retract_lengths.append(float(length)) or {})
        gcmd = FakeGcmd({
            "INDEX": 0,
            "LENGTH": 20,
            "SPEED": 10,
            "CONFIRM": 0,
        })

        ace.cmd_ACE_RETRACT(gcmd)

        self.assertEqual(ace.retract_lengths, [])
        self.assertTrue(any("CONFIRM=1" in message
                            for message in gcmd.messages))

    def test_uncertain_parking_retract_requires_manual_recovery(self):
        ace, gcmd = make_cross_tool_ace()
        ace.printer.print_stats.state = "printing"
        ace.parking_sensor_enabled = False
        retract_attempts = []

        def uncertain_retract(index, length, speed, phase):
            retract_attempts.append((index, length, speed, phase))
            ace._set_toolchange_phase(phase + "_FAST")
            raise ace_driver.AceMotionUncertainError(
                "simulated uncertain parking retract")

        ace._retract_in_chunks = uncertain_retract

        with self.assertRaises(ace_driver.AceMotionUncertainError):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertEqual(len(retract_attempts), 1)
        self.assertIsNone(ace._pending_toolchange_recovery)
        self.assertFalse(any(
            script.startswith("ACE_CHANGE_TOOL")
            for script in ace.gcode.scripts))
        self.assertEqual(ace.gcode.scripts.count("PAUSE"), 1)
        self.assertNotIn("RESUME", ace.gcode.scripts)
        self.assertIn("OLD_BOWDEN_RETRACT_FAST", ace._toolchange_last_error)
        self.assertIn("禁止自动重放", ace._toolchange_last_error)
        self.assertEqual(ace.slot_positions[0], "unknown")
        self.assertIsNone(ace._motion_owner)

    def test_cutter_failure_pauses_and_cannot_repeat_cut(self):
        ace, gcmd = make_cross_tool_ace()
        ace.printer.print_stats.state = "printing"
        ace.gcode = FailingScriptGcode("CUT_TIP")

        with self.assertRaisesRegex(RuntimeError, "CUT_TIP failure"):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertEqual(ace.gcode.scripts.count("CUT_TIP"), 1)
        self.assertEqual(ace.slot_positions[0], "unknown")
        self.assertIsNone(ace._pending_toolchange_recovery)
        self.assertIn("CUTTING", ace._toolchange_last_error)
        self.assertIn("PAUSE", ace.gcode.scripts)
        self.assertNotIn("RESUME", ace.gcode.scripts)
        self.assertIsNone(ace._motion_owner)

        with self.assertRaisesRegex(RuntimeError, "位置不可信"):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)
        self.assertEqual(ace.gcode.scripts.count("CUT_TIP"), 1)

    def test_idle_cutter_failure_reports_without_pause(self):
        ace, gcmd = make_cross_tool_ace()
        ace.gcode = FailingScriptGcode("CUT_TIP")

        with self.assertRaisesRegex(RuntimeError, "CUT_TIP failure"):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertNotIn("PAUSE", ace.gcode.scripts)
        self.assertIsNone(ace._motion_owner)
        self.assertIn("CUTTING", ace._toolchange_last_error)

    def test_sensor_conflict_pauses_active_print_and_preserves_diagnostics(self):
        ace, gcmd = make_cross_tool_ace()
        ace.printer.print_stats.state = "printing"
        ace._preload_lower = False

        with self.assertRaisesRegex(RuntimeError, "下方传感器未触发"):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertIn("PAUSE", ace.gcode.scripts)
        self.assertNotIn("RESUME", ace.gcode.scripts)
        self.assertIn("下方传感器未触发", ace._toolchange_last_error)
        self.assertIn("失败阶段=", ace._toolchange_last_error)
        self.assertEqual(ace.slot_positions[0], "unknown")
        self.assertIsNone(ace._motion_owner)

    def test_same_tool_sensor_conflict_also_pauses_active_print(self):
        ace, gcmd = make_same_tool_ace(
            position="unknown", upper=True, lower=False)
        ace.printer.print_stats.state = "printing"

        with self.assertRaisesRegex(RuntimeError, "状态矛盾"):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertIn("PAUSE", ace.gcode.scripts)
        self.assertNotIn("RESUME", ace.gcode.scripts)
        self.assertIn(
            "PREFLIGHT_SENSOR_CONFLICT", ace._toolchange_last_error)
        self.assertEqual(ace.slot_positions[0], "unknown")
        self.assertIsNone(ace._motion_owner)

    def test_retract_failure_pauses_and_stops_feed_assist(self):
        ace, gcmd = make_cross_tool_ace()
        ace.printer.print_stats.state = "printing"

        def fail_retract(index, length, speed, phase):
            ace._set_toolchange_phase(phase + "_FAST")
            ace._feed_assist_index = 1
            raise RuntimeError("simulated ordinary retract failure")

        ace._retract_in_chunks = fail_retract

        with self.assertRaisesRegex(RuntimeError, "ordinary retract failure"):
            ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertIn(("disable_assist", 1), ace.motion_calls)
        self.assertEqual(ace._feed_assist_index, -1)
        self.assertEqual(ace._pending_feed_assist_restore, -1)
        self.assertIn("PAUSE", ace.gcode.scripts)
        self.assertNotIn("RESUME", ace.gcode.scripts)
        self.assertIn("OLD_BOWDEN_RETRACT_FAST", ace._toolchange_last_error)
        self.assertIsNone(ace._motion_owner)

    def test_feed_failure_pauses_stops_assist_and_releases_motion(self):
        ace, gcmd = make_cross_tool_ace()
        ace.printer.print_stats.state = "printing"

        def fail_target_load(tool, command, endless_spool_was_enabled):
            ace._set_toolchange_phase("ACE_FEED_TO_UPPER")
            ace._feed_assist_index = tool
            ace._abort_toolchange(
                tool, command, endless_spool_was_enabled,
                "simulated bounded feed failure")

        ace._park_to_toolhead = fail_target_load

        ace.cmd_ACE_CHANGE_TOOL(gcmd)

        self.assertIn(("disable_assist", 1), ace.motion_calls)
        self.assertEqual(ace._feed_assist_index, -1)
        self.assertEqual(ace._pending_feed_assist_restore, -1)
        self.assertIn("PAUSE", ace.gcode.scripts)
        self.assertNotIn("RESUME", ace.gcode.scripts)
        self.assertIn("ACE_FEED_TO_UPPER", ace._toolchange_last_error)
        self.assertEqual(ace.slot_positions[1], "unknown")
        self.assertIsNone(ace._motion_owner)

    def test_abort_active_feed_requests_protocol_stop(self):
        ace = make_motion_ace()
        ace._active_ace_motion = {"method": "feed_filament", "index": 2}
        ace._toolchange_context = {"phase": "ACE_FEED_TO_UPPER"}
        ace._pending_toolchange_recovery = None
        ace._cancel_toolchange_recovery = lambda: None
        ace._pending_feed_assist_restore = -1
        ace._feed_assist_index = -1
        ace._park_in_progress = True
        ace.endless_spool_in_progress = False
        ace.stop_calls = []
        ace._stop_feed = lambda index: ace.stop_calls.append(("feed", index))
        ace._stop_unwind = lambda index: ace.stop_calls.append(
            ("unwind", index))
        gcmd = FakeGcmd()

        ace.cmd_ACE_ABORT_TOOLCHANGE(gcmd)

        self.assertEqual(ace.stop_calls, [("feed", 2)])
        self.assertTrue(ace._abort_requested)

    def test_abort_active_retract_requests_protocol_stop(self):
        ace = make_motion_ace()
        ace._active_ace_motion = {"method": "unwind_filament", "index": 1}
        ace._toolchange_context = {"phase": "OLD_BOWDEN_RETRACT"}
        ace._pending_toolchange_recovery = None
        ace._cancel_toolchange_recovery = lambda: None
        ace._pending_feed_assist_restore = -1
        ace._feed_assist_index = -1
        ace._park_in_progress = True
        ace.endless_spool_in_progress = False
        ace.stop_calls = []
        ace._stop_feed = lambda index: ace.stop_calls.append(("feed", index))
        ace._stop_unwind = lambda index: ace.stop_calls.append(
            ("unwind", index))

        ace.cmd_ACE_ABORT_TOOLCHANGE(FakeGcmd())

        self.assertEqual(ace.stop_calls, [("unwind", 1)])

    def test_abort_active_motion_pauses_an_active_print(self):
        ace = make_motion_ace()
        ace.printer = FakePrinter("printing")
        ace._active_ace_motion = {"method": "feed_filament", "index": 0}
        ace._toolchange_context = {"phase": "ACE_FEED_TO_UPPER"}
        ace._pending_toolchange_recovery = None
        ace._cancel_toolchange_recovery = lambda: None
        ace._pending_feed_assist_restore = -1
        ace._feed_assist_index = -1
        ace._park_in_progress = True
        ace.endless_spool_in_progress = False
        ace._stop_feed = lambda _index: None

        ace.cmd_ACE_ABORT_TOOLCHANGE(FakeGcmd())

        self.assertIn("PAUSE", ace.gcode.scripts)

    def test_endless_spool_does_not_act_while_standby(self):
        ace = make_motion_ace()
        ace.endless_spool_enabled = True
        ace._park_in_progress = False
        ace.endless_spool_in_progress = False
        ace.variables["ace_current_index"] = 0
        ace.printer.objects["toolhead"] = FakeToolheadStatus()
        ace.printer.objects["idle_timeout"] = FakeIdleTimeout("Ready")
        ace.runout_calls = []
        ace._endless_spool_runout_handler = lambda: (
            ace.runout_calls.append("runout"))

        next_time = ace._endless_spool_monitor(10.0)

        self.assertEqual(ace.runout_calls, [])
        self.assertEqual(next_time, 10.2)


if __name__ == "__main__":
    unittest.main()
