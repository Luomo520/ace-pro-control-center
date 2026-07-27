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

    def run_script_from_command(self, script):
        self.scripts.append(script)


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


if __name__ == "__main__":
    unittest.main()
