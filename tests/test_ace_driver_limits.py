import importlib.util
import inspect
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
SPEC = importlib.util.spec_from_file_location("ace_driver_limits", MODULE_PATH)
ace_driver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ace_driver)


class FakePrinter:
    command_error = RuntimeError


def make_ace():
    ace = object.__new__(ace_driver.BunnyAce)
    ace.printer = FakePrinter()
    ace._active_ace_motion = None
    ace._abort_requested = False
    ace._toolchange_context = {
        "phase": "ACE_FEED_TO_UPPER",
        "from": -1,
        "to": 0,
    }
    ace._standalone_motion_budget = None
    ace.toolchange_feed_hard_limit = 100.0
    ace.toolchange_retract_hard_limit = 150.0
    ace.extruder_sensor_debounce_count = 3
    ace.toolhead_sensor_debounce_count = 4
    ace.parking_sensor_debounce_count = 5
    ace._run_ace_motion_request = lambda *_args, **_kwargs: {"code": 0}
    return ace


class AceConfigVersionTests(unittest.TestCase):
    def test_missing_version_uses_legacy_compatibility(self):
        self.assertEqual(ace_driver.validate_ace_config_version(None), 0)
        self.assertEqual(ace_driver.validate_ace_config_version(""), 0)

    def test_supported_version_loads_and_future_version_fails(self):
        self.assertEqual(
            ace_driver.validate_ace_config_version(
                ace_driver.ACE_CONFIG_VERSION),
            ace_driver.ACE_CONFIG_VERSION,
        )
        with self.assertRaisesRegex(ValueError, "newer than"):
            ace_driver.validate_ace_config_version(
                ace_driver.ACE_CONFIG_VERSION + 1)


class AceMotionLimitTests(unittest.TestCase):
    def test_feed_budget_is_cumulative_and_blocks_before_second_request(self):
        ace = make_ace()
        requests = []
        ace._run_ace_motion_request = lambda *args, **kwargs: (
            requests.append((args, kwargs)) or {"code": 0})

        ace._run_ace_motion("feed_filament", 0, 60, 20)
        with self.assertRaisesRegex(
                ace_driver.FilamentFeedError, "hard limit reached"):
            ace._run_ace_motion("feed_filament", 0, 50, 20)

        self.assertEqual(len(requests), 1)
        self.assertEqual(
            ace._toolchange_context["feed_requested_distance"], 60.0)
        self.assertEqual(
            ace._toolchange_context["hard_limit_phase"],
            "ACE_FEED_TO_UPPER",
        )

    def test_retract_budget_is_independent_from_feed_budget(self):
        ace = make_ace()
        ace._reserve_motion_budget("feed_filament", 90)
        ace._reserve_motion_budget("unwind_filament", 140)

        self.assertEqual(
            ace._toolchange_context["feed_requested_distance"], 90.0)
        self.assertEqual(
            ace._toolchange_context["retract_requested_distance"], 140.0)
        with self.assertRaises(ace_driver.FilamentFeedError):
            ace._reserve_motion_budget("unwind_filament", 11)

    def test_upper_sensor_uses_its_independent_stop_debounce(self):
        ace = make_ace()
        captured = {}
        ace._run_ace_motion = lambda *args, **kwargs: (
            captured.update(kwargs) or {})

        ace._feed(0, 100, 25, stop_sensor="extruder_sensor")

        self.assertEqual(captured["stop_debounce_count"], 3)

    def test_lower_sensor_uses_its_independent_stop_debounce(self):
        ace = make_ace()
        captured = {}
        ace._run_ace_motion = lambda *args, **kwargs: (
            captured.update(kwargs) or {})

        ace._feed(0, 100, 25, stop_sensor="toolhead_sensor")

        self.assertEqual(captured["stop_debounce_count"], 4)

    def test_standalone_calibration_budget_is_cumulative(self):
        ace = make_ace()
        ace._toolchange_context = None
        ace._begin_standalone_motion_budget(
            "calibration", "CALIBRATION_FEED")

        ace._reserve_motion_budget("feed_filament", 60)
        with self.assertRaisesRegex(
                ace_driver.FilamentFeedError, "hard limit reached"):
            ace._reserve_motion_budget("feed_filament", 50)

        self.assertEqual(
            ace._standalone_motion_budget["feed_requested_distance"],
            60.0,
        )

    def test_standalone_preload_budget_is_cumulative(self):
        ace = make_ace()
        ace._toolchange_context = None
        ace._begin_standalone_motion_budget("preload", "PRELOAD_CLEAR_PATH")

        ace._reserve_motion_budget("unwind_filament", 100)
        ace._standalone_motion_budget["phase"] = "PRELOAD_FEED_TO_UPPER"
        ace._reserve_motion_budget("feed_filament", 80)

        self.assertEqual(
            ace._standalone_motion_budget["retract_requested_distance"],
            100.0,
        )
        self.assertEqual(
            ace._standalone_motion_budget["feed_requested_distance"],
            80.0,
        )

    def test_recovery_pending_preserves_consumed_motion_budget(self):
        ace = make_ace()
        ace.auto_toolchange_recovery = True
        ace.auto_toolchange_recovery_max_retries = 2
        ace._pending_toolchange_recovery = None
        ace._toolchange_recovery_timer = object()
        ace.gcode = types.SimpleNamespace(respond_info=lambda _message: None)
        ace._toolchange_context.update({
            "feed_requested_distance": 70.0,
            "retract_requested_distance": 120.0,
        })

        self.assertTrue(ace._queue_toolchange_recovery(1, 0, "serial"))
        pending = ace._pending_toolchange_recovery
        self.assertEqual(pending["feed_requested_distance"], 70.0)
        self.assertEqual(pending["retract_requested_distance"], 120.0)

        source = inspect.getsource(ace_driver.BunnyAce._change_tool)
        self.assertIn(
            "(recovery_pending or {}).get(\n"
            "                    'feed_requested_distance', 0.0)",
            source,
        )
        self.assertIn(
            "(recovery_pending or {}).get(\n"
            "                    'retract_requested_distance', 0.0)",
            source,
        )

    def test_motion_limit_blocks_before_request_is_sent(self):
        ace = make_ace()
        requests = []
        ace._run_ace_motion_request = lambda *args, **kwargs: (
            requests.append((args, kwargs)) or {"code": 0})
        ace._toolchange_context["feed_requested_distance"] = 100.0

        with self.assertRaises(ace_driver.FilamentFeedError):
            ace._run_ace_motion("feed_filament", 0, 1, 20)

        self.assertEqual(requests, [])

    def test_before_five_way_retract_bound_excludes_feed_offset(self):
        source = inspect.getsource(ace_driver.BunnyAce.__init__)
        expected = (
            "if self.parking_sensor_position == 'after_five_way':\n"
            "                calibration_retract_upper_bound += float("
        )
        self.assertIn(expected, source)

    def test_each_sensor_uses_its_own_stability_count(self):
        ace = make_ace()
        samples = []
        ace._sensor_present = lambda name: samples.append(name) or True
        ace.dwell = lambda delay: None

        self.assertTrue(ace._sensor_state_stable("toolhead_sensor", True))
        self.assertEqual(samples, ["toolhead_sensor"] * 4)

    def test_driver_status_exposes_configuration_contract(self):
        source = inspect.getsource(ace_driver.BunnyAce.get_status)
        for key in (
            "ace_config_version",
            "extruder_sensor_debounce_count",
            "toolhead_sensor_debounce_count",
            "toolchange_feed_hard_limit",
            "toolchange_retract_hard_limit",
            "configuration",
        ):
            self.assertIn(key, source)


if __name__ == "__main__":
    unittest.main()
