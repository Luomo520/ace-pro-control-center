import asyncio
import importlib.util
import pathlib
import unittest


MODULE_PATH = (
    pathlib.Path(__file__).parents[1]
    / "ace_status_integration"
    / "moonraker"
    / "ace_status.py"
)
SPEC = importlib.util.spec_from_file_location("ace_status_component", MODULE_PATH)
ace_status = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ace_status)


class FakeWebRequest:
    def __init__(self, args):
        self.args = args

    def get_args(self):
        return self.args


class FakeKlippyApis:
    def __init__(self):
        self.gcodes = []

    async def run_gcode(self, gcode):
        self.gcodes.append(gcode)


class AceStatusContractTests(unittest.TestCase):
    def test_normalizes_sv08_inventory_and_sensor_state(self):
        status = ace_status.normalize_status(
            {
                "connected": True,
                "status": "ready",
                "temp": 42.5,
                "feed_assist_index": 1,
                "max_dryer_temperature": 65,
                "dryer": {"status": "drying", "target_temp": 50},
                "slots": [{"status": "ready", "type": "PLA"}],
            },
            {
                "ace_current_index": 0,
                "ace_inventory": [
                    {
                        "status": "ready",
                        "material": "PLA",
                        "color": [12, 34, 56],
                        "temp": 210,
                    }
                ],
            },
            {"filament_detected": True},
            {"filament_detected": False},
        )

        self.assertEqual(status["driver"], "ACEPROSV08")
        self.assertTrue(status["connected"])
        self.assertEqual(status["current_tool"], 0)
        self.assertEqual(status["feed_assist_index"], 1)
        self.assertEqual(status["slots"][0]["color"]["hex"], "#0C2238")
        self.assertTrue(status["sensors"]["upper"]["detected"])
        self.assertFalse(status["sensors"]["lower"]["detected"])

    def test_builds_sv08_inventory_command_with_index(self):
        gcode = ace_status.build_gcode(
            {
                "command": "ACE_SET_SLOT",
                "params": {
                    "INDEX": 1,
                    "COLOR": [1, 2, 3],
                    "MATERIAL": "PETG",
                    "TEMP": 240,
                },
            }
        )
        self.assertEqual(
            gcode,
            "ACE_SET_SLOT INDEX=1 MATERIAL=PETG COLOR=1,2,3 TEMP=240",
        )

    def test_rejects_out_of_range_rgb_instead_of_clamping(self):
        for color in ([256, 2, 3], [-1, 2, 3], ["bad", 2, 3]):
            with self.subTest(color=color):
                with self.assertRaises(ace_status.AceRequestError):
                    ace_status.build_gcode(
                        {
                            "command": "ACE_SET_SLOT",
                            "params": {
                                "INDEX": 0,
                                "COLOR": color,
                                "MATERIAL": "PLA",
                                "TEMP": 210,
                            },
                        }
                    )

    def test_rejects_unknown_commands_and_unsafe_material(self):
        with self.assertRaises(ace_status.AceRequestError):
            ace_status.build_gcode({"command": "M112", "params": {}})
        with self.assertRaises(ace_status.AceRequestError):
            ace_status.build_gcode(
                {
                    "command": "ACE_SET_SLOT",
                    "params": {
                        "INDEX": 0,
                        "COLOR": [1, 2, 3],
                        "MATERIAL": "PLA\nM112",
                        "TEMP": 210,
                    },
                }
            )

    def test_blocks_motion_commands_while_printing(self):
        with self.assertRaises(ace_status.AceRequestError):
            ace_status.build_gcode(
                {
                    "command": "ACE_FEED",
                    "params": {"INDEX": 0, "LENGTH": 20, "SPEED": 10},
                },
                printing=True,
            )

    def test_post_handler_reads_moonraker_webrequest_args(self):
        component = ace_status.AceStatus.__new__(ace_status.AceStatus)
        component.klippy_apis = FakeKlippyApis()

        async def fake_status(_webrequest):
            return {
                "printing": False,
                "connected": True,
                "max_dryer_temperature": 65,
            }

        component.handle_status_request = fake_status
        result = asyncio.run(
            component.handle_command_request(
                FakeWebRequest(
                    {
                        "command": "ACE_FEED",
                        "params": {"INDEX": 2, "LENGTH": 30, "SPEED": 15},
                    }
                )
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(component.klippy_apis.gcodes, ["ACE_FEED INDEX=2 LENGTH=30 SPEED=15"])


if __name__ == "__main__":
    unittest.main()
