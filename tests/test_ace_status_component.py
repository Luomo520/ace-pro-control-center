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
    def test_capabilities_do_not_advertise_unregistered_ack(self):
        self.assertNotIn("ACE_ACK_TOOLCHANGE", ace_status.COMMAND_BUILDERS)

    def test_builds_confirmed_preload_and_calibration_commands(self):
        cases = (
            (
                "ACE_PRELOAD",
                {"INDEX": 2, "CONFIRM": 1},
                "ACE_PRELOAD INDEX=2 CONFIRM=1",
            ),
            (
                "ACE_CALIBRATE_FEED",
                {"INDEX": 1, "CONFIRM": True},
                "ACE_CALIBRATE_FEED INDEX=1 CONFIRM=1",
            ),
            (
                "ACE_CALIBRATE_RETRACT",
                {"CONFIRM": 1},
                "ACE_CALIBRATE_RETRACT CONFIRM=1",
            ),
            (
                "ACE_CALIBRATION_SAVE",
                {"CONFIRM": 1},
                "ACE_CALIBRATION_SAVE CONFIRM=1",
            ),
            (
                "ACE_FULL_UNLOAD",
                {"INDEX": 3, "CONFIRM": 1},
                "ACE_FULL_UNLOAD INDEX=3 CONFIRM=1",
            ),
        )
        for command, params, expected in cases:
            with self.subTest(command=command):
                self.assertEqual(
                    ace_status.build_gcode(
                        {"command": command, "params": params}),
                    expected,
                )

    def test_confirmed_motion_rejects_missing_confirmation(self):
        for command, params in (
            ("ACE_PRELOAD", {"INDEX": 0}),
            ("ACE_CALIBRATE_FEED", {"INDEX": 0}),
            ("ACE_CALIBRATE_RETRACT", {}),
            ("ACE_CALIBRATION_SAVE", {}),
            ("ACE_FULL_UNLOAD", {"INDEX": 0}),
            ("ACE_FEED", {"INDEX": 0, "LENGTH": 20, "SPEED": 10}),
            ("ACE_RETRACT", {"INDEX": 0, "LENGTH": 20, "SPEED": 10}),
        ):
            with self.subTest(command=command):
                with self.assertRaises(ace_status.AceRequestError):
                    ace_status.build_gcode(
                        {"command": command, "params": params})

    def test_manual_motion_includes_one_time_confirmation(self):
        self.assertEqual(
            ace_status.build_gcode({
                "command": "ACE_FEED",
                "params": {
                    "INDEX": 0,
                    "LENGTH": 20,
                    "SPEED": 10,
                    "CONFIRM": 1,
                },
            }),
            "ACE_FEED INDEX=0 LENGTH=20 SPEED=10 CONFIRM=1",
        )

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

    def test_normalizes_slot_positions_and_calibration_state(self):
        status = ace_status.normalize_status(
            {
                "connected": True,
                "slot_positions": [
                    "preload_parked_estimated",
                    "unknown",
                    "toolhead",
                    "internal_or_unknown",
                ],
                "filament_position": "toolhead",
                "motion_owner": "距离送料标定",
                "calibration": {
                    "available": True,
                    "valid": True,
                    "stale": False,
                    "phase": "feed_complete",
                    "selected_slot": 2,
                    "feed_completed": 1200,
                    "feed_upper_bound": 1205,
                    "retract_distance": 1035,
                    "parking_distance": 1035,
                    "last_error": "",
                },
            },
            {"ace_current_index": 2},
            {},
            {},
        )

        self.assertEqual(
            status["slot_positions"][0],
            "preload_parked_estimated",
        )
        self.assertEqual(status["filament_position"], "toolhead")
        self.assertEqual(status["motion_owner"], "距离送料标定")
        self.assertTrue(status["calibration"]["valid"])
        self.assertEqual(
            status["calibration"]["feed_upper_bound"], 1205)
        self.assertEqual(
            status["calibration"]["parking_distance"], 1035)

    def test_missing_calibration_is_unavailable_not_valid_zero(self):
        status = ace_status.normalize_status({}, {}, {}, {})

        self.assertFalse(status["calibration"]["available"])
        self.assertFalse(status["calibration"]["valid"])
        self.assertEqual(status["calibration"]["phase"], "unavailable")

    def test_normalizes_alternate_dryer_status_fields(self):
        status = ace_status.normalize_status(
            {
                "connected": True,
                "dryer_status": {
                    "state": "running",
                    "target_temperature": 50,
                    "duration_minutes": 240,
                    "remaining_time": 90,
                },
            },
            {},
            {},
            {},
        )

        self.assertEqual(status["dryer"]["status"], "drying")
        self.assertEqual(status["dryer"]["target_temperature"], 50)
        self.assertEqual(status["dryer"]["duration_minutes"], 240)
        self.assertEqual(status["dryer"]["remaining_minutes"], 90)

    def test_converts_dryer_seconds_reported_as_remaining_time(self):
        status = ace_status.normalize_status(
            {
                "connected": True,
                "dryer": {
                    "status": "drying",
                    "target_temp": 60,
                    "duration": 240,
                    "remain_time": 11909,
                },
            },
            {},
            {},
            {},
        )

        self.assertEqual(status["dryer"]["remaining_minutes"], 198)

    def test_normalizes_auto_drying_state(self):
        status = ace_status.normalize_status(
            {
                "connected": True,
                "auto_drying": {
                    "enabled": True,
                    "active": True,
                    "owned_by_auto": True,
                    "suppressed_for_job": False,
                    "temperature": 50,
                    "reason": "PLA_MIXED",
                    "print_state": "printing",
                    "last_error": "",
                    "notice_id": 7,
                    "notice_message": "检测到 PLA 与其他材料混装",
                },
            },
            {},
            {},
            {},
            printing=True,
        )

        self.assertTrue(status["auto_drying"]["enabled"])
        self.assertTrue(status["auto_drying"]["owned_by_auto"])
        self.assertEqual(status["auto_drying"]["temperature"], 50)
        self.assertEqual(status["auto_drying"]["reason"], "PLA_MIXED")
        self.assertEqual(status["auto_drying"]["notice_id"], 7)

    def test_auto_drying_switches_are_strict_and_available_while_printing(self):
        for command in (
            "ACE_ENABLE_AUTO_DRYING",
            "ACE_DISABLE_AUTO_DRYING",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    ace_status.build_gcode(
                        {"command": command, "params": {}},
                        printing=True,
                        connected=False,
                    ),
                    command,
                )
                with self.assertRaises(ace_status.AceRequestError):
                    ace_status.build_gcode(
                        {"command": command, "params": {"TEMP": 60}}
                    )

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
                        "params": {
                            "INDEX": 2,
                            "LENGTH": 30,
                            "SPEED": 15,
                            "CONFIRM": 1,
                        },
                    }
                )
            )
        )

        self.assertTrue(result["success"])
        self.assertEqual(
            component.klippy_apis.gcodes,
            ["ACE_FEED INDEX=2 LENGTH=30 SPEED=15 CONFIRM=1"],
        )

    def test_abort_handler_runs_real_driver_command(self):
        component = ace_status.AceStatus.__new__(ace_status.AceStatus)
        component.klippy_apis = FakeKlippyApis()

        async def fake_status(_webrequest):
            return {
                "printing": True,
                "connected": False,
                "max_dryer_temperature": 65,
            }

        component.handle_status_request = fake_status
        result = asyncio.run(
            component.handle_command_request(FakeWebRequest({
                "command": "ACE_ABORT_TOOLCHANGE",
                "params": {},
            })))

        self.assertTrue(result["success"])
        self.assertEqual(
            component.klippy_apis.gcodes,
            ["ACE_ABORT_TOOLCHANGE"],
        )


if __name__ == "__main__":
    unittest.main()
