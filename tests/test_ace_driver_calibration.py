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


class FakePrinter:
    def __init__(self, print_state="standby"):
        self.print_stats = FakePrintStats(print_state)

    def lookup_object(self, name, default=None):
        if name == "print_stats":
            return self.print_stats
        return default

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
    ace._calibration_preview = None
    ace._calibration_phase = "idle"
    ace._calibration_last_error = ""
    ace.calibration_speed = 25.0
    ace.calibration_chunk_length = 5.0
    ace.calibration_final_chunk_length = 2.0
    ace.toolchange_load_length = 20.0
    ace.feed_slip_compensation_length = 0.0
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
    ace.retract_fast_speed = 120.0
    ace.toolchange_retract_length = 1200.0
    ace._feed_assist_index = -1
    ace.toolhead_feed_fast_length = 10.0
    ace.toolhead_feed_fast_step = 5.0
    ace.toolhead_feed_fast_speed = 8.0
    ace.toolhead_feed_slow_step = 1.0
    ace.toolhead_feed_slow_speed = 5.0
    ace.toolhead_sensor_max_feed_length = 20.0
    ace.toolhead_sensor_to_nozzle_length = 80.0
    ace._info["slots"] = [{"status": "ready"} for _ in range(4)]

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
    ace._disable_feed_assist = lambda index, **_kwargs: ace.motion_calls.append(
        ("disable_assist", index))
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

    def test_save_rejects_record_for_different_config(self):
        ace = make_calibration_data_ace(bowden=200.0)
        ace._load_calibration_record()

        with self.assertRaises(ValueError):
            ace._save_calibration_record(make_calibration_record())


class AceCalibrationMotionTests(unittest.TestCase):
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
        self.assertEqual(preview["phase"], "retract_complete")
        self.assertEqual(
            ace.slot_positions[0], "preload_parked_estimated")
        self.assertEqual(ace.variables["ace_current_index"], -1)

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
        gcmd = FakeGcmd({"CONFIRM": 1})

        ace.cmd_ACE_CALIBRATION_SAVE(gcmd)

        record = ace.variables["ace_calibration"]
        self.assertEqual(record["format_version"], 1)
        self.assertEqual(record["parking_distance"], 12.0)
        self.assertTrue(record["valid"])
        self.assertEqual(ace._calibration_phase, "saved")


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


if __name__ == "__main__":
    unittest.main()
