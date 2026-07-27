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


if __name__ == "__main__":
    unittest.main()
