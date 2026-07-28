import importlib.util
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
SPEC = importlib.util.spec_from_file_location("ace_material_driver", MODULE_PATH)
ace_driver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ace_driver)


class FakeConfigSection:
    def __init__(self, values):
        self.values = values

    def get(self, name, default=None):
        return self.values.get(name, default)

    def getint(self, name, default=None, **_kwargs):
        value = self.values.get(name, default)
        return default if value is None else int(value)

    def getboolean(self, name, default=None):
        value = self.values.get(name, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")


class FakeSlotCommand:
    def __init__(self, values):
        self.values = values

    def get_int(self, name, default=None):
        return int(self.values.get(name, default))

    def get(self, name, default=None):
        return self.values.get(name, default)

    def error(self, message):
        return ValueError(message)


class FakeGcode:
    def __init__(self):
        self.scripts = []

    def run_script_from_command(self, script):
        self.scripts.append(script)

    def respond_info(self, _message):
        pass


class MaterialProfileTests(unittest.TestCase):
    def test_inventory_rejects_invalid_rgb_before_mutating_or_saving(self):
        ace = object.__new__(ace_driver.BunnyAce)
        original = {
            "status": "ready",
            "color": [1, 2, 3],
            "material": "PLA",
            "temp": 210,
        }
        ace.inventory = [dict(original)] + [
            {"status": "empty", "color": [0, 0, 0], "material": "", "temp": 0}
            for _ in range(3)
        ]
        ace.variables = {}
        ace.gcode = FakeGcode()

        with self.assertRaisesRegex(ValueError, "COLOR"):
            ace.cmd_ACE_SET_SLOT(FakeSlotCommand({
                "INDEX": 0,
                "COLOR": "300,2,3",
                "MATERIAL": "ABS",
                "TEMP": 260,
            }))

        self.assertEqual(ace.inventory[0], original)
        self.assertEqual(ace.gcode.scripts, [])

    def test_parses_custom_name_drying_temperature_and_material_temperature(self):
        profiles = ace_driver.parse_material_profiles(FakeConfigSection({
            "material_1_name": "Nylon Custom",
            "material_1_drying_temperature": "55",
            "material_1_temperature": "275",
            "unknown_material_drying_temperature": "45",
            "unknown_material_temperature": "0",
            "mixed_material_drying_temperature": "50",
            "show_material_warning": "True",
        }), max_dryer_temperature=65)

        self.assertEqual(profiles["NYLON CUSTOM"], {
            "name": "Nylon Custom",
            "drying_temperature": 55,
            "material_temperature": 275,
        })
        self.assertEqual(profiles["__unknown__"]["drying_temperature"], 45)
        self.assertEqual(profiles["__mixed__"]["drying_temperature"], 50)
        self.assertTrue(profiles["__meta__"]["show_material_warning"])

    def test_rejects_duplicate_names_and_temperature_above_dryer_limit(self):
        with self.assertRaises(ValueError):
            ace_driver.parse_material_profiles(FakeConfigSection({
                "material_1_name": "PLA",
                "material_1_drying_temperature": "45",
                "material_1_temperature": "210",
                "material_2_name": "pla",
                "material_2_drying_temperature": "45",
                "material_2_temperature": "210",
            }), max_dryer_temperature=65)

        with self.assertRaises(ValueError):
            ace_driver.parse_material_profiles(FakeConfigSection({
                "material_1_name": "PEEK",
                "material_1_drying_temperature": "70",
                "material_1_temperature": "360",
            }), max_dryer_temperature=65)

    def test_custom_profile_drives_auto_drying_temperature(self):
        profiles = ace_driver.parse_material_profiles(FakeConfigSection({
            "material_1_name": "Nylon Custom",
            "material_1_drying_temperature": "55",
            "material_1_temperature": "275",
        }), max_dryer_temperature=65)

        self.assertEqual(
            ace_driver.select_auto_drying_policy(
                [{"status": "ready", "material": "Nylon Custom"}],
                profiles,
            ),
            (55, "HIGH_TEMP"),
        )

    def test_unknown_profile_uses_conservative_fallback(self):
        profiles = ace_driver.parse_material_profiles(
            FakeConfigSection({
                "unknown_material_drying_temperature": "45",
                "unknown_material_temperature": "0",
            }),
            max_dryer_temperature=65,
        )

        self.assertEqual(
            ace_driver.select_auto_drying_policy(
                [{"status": "ready", "material": "NotConfigured"}],
                profiles,
            ),
            (45, "UNKNOWN"),
        )

    def test_auto_drying_message_uses_configured_temperature(self):
        self.assertIn("47°C", ace_driver.build_auto_drying_message("UNKNOWN", 47))
        self.assertIn("52°C", ace_driver.build_auto_drying_message("PLA_MIXED", 52))

    def test_endless_spool_requires_matching_material_when_enabled(self):
        ace = object.__new__(ace_driver.BunnyAce)
        ace.endless_spool_require_same_material = True
        ace.inventory = [
            {"status": "ready", "material": "PLA"},
            {"status": "ready", "material": "ABS"},
            {"status": "ready", "material": "pla"},
            {"status": "empty", "material": ""},
        ]
        ace._info = {
            "slots": [{"status": "ready"} for _ in range(4)],
        }

        self.assertEqual(ace._find_next_available_slot(0), 2)

    def test_endless_spool_pauses_when_current_material_is_unknown(self):
        ace = object.__new__(ace_driver.BunnyAce)
        ace.endless_spool_require_same_material = True
        ace.inventory = [
            {"status": "ready", "material": ""},
            {"status": "ready", "material": "ABS"},
            {"status": "empty", "material": ""},
            {"status": "empty", "material": ""},
        ]
        ace._info = {
            "slots": [{"status": "ready"} for _ in range(4)],
        }

        self.assertEqual(ace._find_next_available_slot(0), -1)


if __name__ == "__main__":
    unittest.main()
