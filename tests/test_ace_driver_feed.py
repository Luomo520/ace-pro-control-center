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
SPEC = importlib.util.spec_from_file_location("ace_driver", MODULE_PATH)
ace_driver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ace_driver)


class FakeGcode:
    def __init__(self):
        self.messages = []

    def respond_info(self, message):
        self.messages.append(message)


def make_ace(intermittent):
    ace = object.__new__(ace_driver.BunnyAce)
    ace.intermittent_feed = intermittent
    ace.feed_approach_length = 100.0
    ace.feed_fast_chunk_length = 1000.0
    ace.feed_approach_speed = 25.0
    ace.feed_slip_compensation_length = 400.0
    ace.feed_slip_compensation_chunk = 50.0
    ace.feed_slip_compensation_speed = 25.0
    ace.ace_motion_chunk_length = 100.0
    ace.extruder_sensor_timeout = 15.0
    ace._active_ace_motion = None
    ace._abort_requested = False
    ace.gcode = FakeGcode()
    ace._sensor_present = lambda _name: False
    ace._set_toolchange_phase = lambda *_args, **_kwargs: None
    ace.wait_ace_ready = lambda: None
    ace.dwell = lambda delay: None
    return ace


class AceContinuousFeedTests(unittest.TestCase):
    def test_configured_serial_path_is_used_without_autodiscovery(self):
        ace = object.__new__(ace_driver.BunnyAce)
        ace.serial_name = "/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00"
        ace.find_com_port = lambda _name: self.fail(
            "configured serial path must not trigger autodiscovery")

        self.assertEqual(
            ace._resolve_serial_port(),
            "/dev/serial/by-id/usb-ANYCUBIC_ACE_1-if00",
        )

    def test_auto_serial_path_uses_discovery(self):
        ace = object.__new__(ace_driver.BunnyAce)
        ace.serial_name = "auto"
        ace.find_com_port = lambda name: "/dev/ttyACM7" if name == "ACE" else None

        self.assertEqual(ace._resolve_serial_port(), "/dev/ttyACM7")

    def test_stop_ready_timeout_covers_slow_motion_duration(self):
        ace = make_ace(intermittent=False)
        ace.ace_stop_ready_timeout = 25.0

        self.assertEqual(ace._motion_stop_ready_timeout(400, 25), 25.0)
        self.assertEqual(ace._motion_stop_ready_timeout(2000, 25), 83.0)

    def test_sensor_stop_waits_with_dynamic_ready_timeout(self):
        ace = make_ace(intermittent=False)
        ace.ace_stop_ready_timeout = 25.0
        ace.ace_request_timeout = 5.0
        ace._connected = True
        ace._toolchange_context = {}
        ace._connection_generation = 1
        token = {
            "response": {"code": 0},
            "lost": False,
            "sent_time": 0.0,
        }
        stop_token = object()
        waits = []
        ace.send_request = lambda **_kwargs: token
        ace._sensor_present = lambda _name: True
        ace._queue_stop_feed = lambda _index: stop_token
        ace._stop_feed = lambda index, token=None: {"code": 0}

        def wait_for_request(_token, timeout=None, poll_callback=None):
            poll_callback()
            return True

        ace._wait_for_request = wait_for_request
        ace.wait_ace_ready = lambda timeout=None: waits.append(timeout)

        result = ace._run_ace_motion(
            "feed_filament", 3, 400, 25,
            stop_sensor="extruder_sensor")

        self.assertTrue(result["stopped_by_sensor"])
        self.assertEqual(waits, [25.0])

    def test_retract_sensor_clear_uses_stop_unwind_after_debounce(self):
        ace = make_ace(intermittent=False)
        ace.ace_stop_ready_timeout = 25.0
        ace.ace_request_timeout = 5.0
        ace._connected = True
        ace._toolchange_context = {}
        ace._connection_generation = 1
        token = {
            "response": {"code": 0},
            "lost": False,
            "sent_time": 0.0,
        }
        stop_token = {"response": {"code": 0}, "lost": False}
        queued = []
        stopped = []
        sensor_reads = iter([True, False, False, False])
        ace.send_request = lambda **_kwargs: token
        ace._sensor_present = lambda _name: next(sensor_reads)
        ace._queue_stop_unwind = lambda index: (
            queued.append(index) or stop_token)
        ace._queue_stop_feed = lambda _index: self.fail(
            "retract must not queue stop_feed_filament")
        ace._stop_unwind = lambda index, token=None: (
            stopped.append((index, token)) or {"code": 0})
        ace._stop_feed = lambda _index, token=None: self.fail(
            "retract must not call stop_feed_filament")

        def wait_for_request(_token, timeout=None, poll_callback=None):
            for _ in range(4):
                poll_callback()
            return True

        ace._wait_for_request = wait_for_request
        ace.wait_ace_ready = lambda timeout=None: None

        result = ace._run_ace_motion(
            "unwind_filament", 2, 1500, 120,
            stop_sensor="parking_sensor",
            stop_when_present=False,
            stop_debounce_count=3)

        self.assertTrue(result["stopped_by_sensor"])
        self.assertEqual(queued, [2])
        self.assertEqual(stopped, [(2, stop_token)])

    def test_already_triggered_sensor_skips_motion(self):
        ace = make_ace(intermittent=False)
        ace._sensor_present = lambda _name: True
        calls = []
        ace._feed = lambda *args, **kwargs: calls.append((args, kwargs))

        fed = ace._feed_until_sensor(
            0, "extruder_sensor", 1200, 160,
            "送料 %.1f mm 后未触发")

        self.assertEqual(fed, 0.0)
        self.assertEqual(calls, [])

    def test_continuous_mode_uses_fast_and_approach_requests(self):
        ace = make_ace(intermittent=False)
        calls = []
        sensor_states = iter([False, False, False, False, True])
        ace._sensor_present = lambda _name: next(sensor_states)

        def feed(index, length, speed, stop_sensor=None):
            calls.append((index, length, speed, stop_sensor))
            return {}

        ace._feed = feed
        ace._feed_until_sensor(
            0, "extruder_sensor", 1200, 160,
            "送料 %.1f mm 后未触发")

        self.assertEqual(
            calls,
            [
                (0, 1100.0, 160, "extruder_sensor"),
                (0, 100.0, 25.0, "extruder_sensor"),
            ],
        )

    def test_sensor_confirmation_timeout_uses_configured_value(self):
        ace = make_ace(intermittent=False)
        ace.extruder_sensor_timeout = 17.0

        self.assertEqual(ace._sensor_confirmation_timeout(), 17.0)

    def test_continuous_mode_uses_one_compensation_request(self):
        ace = make_ace(intermittent=False)
        calls = []
        sensor_states = iter([False, False, False, False, False, True])
        ace._sensor_present = lambda _name: next(sensor_states)
        results = [{}, {}, {"stopped_by_sensor": True}]

        def feed(index, length, speed, stop_sensor=None):
            calls.append((index, length, speed, stop_sensor))
            return results.pop(0)

        ace._feed = feed
        ace._feed_until_sensor(
            1, "extruder_sensor", 1200, 160,
            "送料 %.1f mm 后未触发")

        self.assertEqual(
            calls,
            [
                (1, 1100.0, 160, "extruder_sensor"),
                (1, 100.0, 25.0, "extruder_sensor"),
                (1, 400.0, 25.0, "extruder_sensor"),
            ],
        )

    def test_intermittent_mode_retains_segmented_behavior(self):
        ace = make_ace(intermittent=True)
        calls = []

        def feed(index, length, speed, stop_sensor=None):
            calls.append((index, length, speed, stop_sensor))
            return {"stopped_by_sensor": len(calls) == 3}

        ace._feed = feed
        ace._feed_until_sensor(
            2, "extruder_sensor", 1200, 160,
            "送料 %.1f mm 后未触发")

        self.assertEqual(
            [call[1] for call in calls], [1000.0, 100.0, 100.0])

    def test_intermittent_feed_stops_after_uncertain_segment(self):
        ace = make_ace(intermittent=True)
        calls = []

        def feed(index, length, speed, stop_sensor=None):
            calls.append((index, length, speed, stop_sensor))
            return {"uncertain": True}

        ace._feed = feed
        with self.assertRaises(ace_driver.AceMotionUncertainError):
            ace._feed_until_sensor(
                2, "extruder_sensor", 1200, 160,
                "送料 %.1f mm 后未触发")

        self.assertEqual(len(calls), 1)


class AceRetractModeTests(unittest.TestCase):
    def make_retract_ace(self, intermittent):
        ace = make_ace(intermittent=False)
        ace.intermittent_retract = intermittent
        ace.retract_parking_length = 200.0
        ace.retract_parking_speed = 25.0
        return ace

    def test_continuous_retract_uses_two_speed_stages(self):
        ace = self.make_retract_ace(intermittent=False)
        calls = []
        waits = []
        ace._retract = lambda index, length, speed: calls.append(
            (index, length, speed))
        ace.wait_ace_ready = lambda timeout=None: waits.append(timeout)

        ace._retract_in_chunks(3, 1200, 120, "OLD_BOWDEN_RETRACT")

        self.assertEqual(
            calls,
            [(3, 1000.0, 120), (3, 200.0, 25.0)],
        )
        self.assertEqual(waits, [None, None])

    def test_intermittent_retract_retains_100mm_chunks(self):
        ace = self.make_retract_ace(intermittent=True)
        calls = []
        ace._retract = lambda index, length, speed: calls.append(
            (index, length, speed))

        ace._retract_in_chunks(2, 1200, 120, "OLD_BOWDEN_RETRACT")

        self.assertEqual(len(calls), 12)
        self.assertEqual(calls[:10], [(2, 100.0, 120)] * 10)
        self.assertEqual(calls[10:], [(2, 100.0, 25.0)] * 2)

    def test_continuous_retract_stops_before_slow_stage_when_uncertain(self):
        ace = self.make_retract_ace(intermittent=False)
        calls = []

        def retract(index, length, speed):
            calls.append((index, length, speed))
            return {"uncertain": True}

        ace._retract = retract
        with self.assertRaises(ace_driver.AceMotionUncertainError):
            ace._retract_in_chunks(3, 1200, 120, "OLD_BOWDEN_RETRACT")

        self.assertEqual(calls, [(3, 1000.0, 120)])

    def test_intermittent_retract_stops_after_uncertain_chunk(self):
        ace = self.make_retract_ace(intermittent=True)
        calls = []

        def retract(index, length, speed):
            calls.append((index, length, speed))
            return {"uncertain": True}

        ace._retract = retract
        with self.assertRaises(ace_driver.AceMotionUncertainError):
            ace._retract_in_chunks(2, 1200, 120, "OLD_BOWDEN_RETRACT")

        self.assertEqual(calls, [(2, 100.0, 120)])

    def test_zero_parking_length_uses_one_retract_request(self):
        ace = self.make_retract_ace(intermittent=False)
        ace.retract_parking_length = 0.0
        calls = []
        ace._retract = lambda index, length, speed: calls.append(
            (index, length, speed))

        ace._retract_in_chunks(1, 1200, 120, "OLD_BOWDEN_RETRACT")

        self.assertEqual(calls, [(1, 1200.0, 120)])


if __name__ == "__main__":
    unittest.main()
