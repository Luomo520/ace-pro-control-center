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
SPEC = importlib.util.spec_from_file_location("ace_auto_drying_driver", MODULE_PATH)
ace_driver = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ace_driver)


def slot(material, status="ready"):
    return {"status": status, "material": material}


class FakePrintStats:
    def __init__(self, state="standby"):
        self.state = state

    def get_status(self, _eventtime):
        return {"state": self.state}


class FakePrinter:
    def __init__(self, print_stats):
        self.print_stats = print_stats

    def lookup_object(self, name, default=None):
        if name == "print_stats":
            return self.print_stats
        return default


class FakeReactor:
    NEVER = float("inf")

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


class FakeGcode:
    def __init__(self):
        self.messages = []
        self.scripts = []

    def respond_info(self, message):
        self.messages.append(message)

    def run_script_from_command(self, script):
        self.scripts.append(script)


class FakeCommand:
    def __init__(self, parameters=None):
        self.parameters = parameters or {}
        self.messages = []

    def get_command_parameters(self):
        return self.parameters

    def respond_info(self, message):
        self.messages.append(message)

    def error(self, message):
        return ValueError(message)


def make_auto_ace(enabled=True, materials=None, dryer_status="stop", connected=True):
    ace = object.__new__(ace_driver.BunnyAce)
    ace.reactor = FakeReactor()
    ace.print_stats = FakePrintStats()
    ace.printer = FakePrinter(ace.print_stats)
    ace.gcode = FakeGcode()
    ace.variables = {}
    ace.inventory = [
        {
            "status": "ready",
            "color": [0, 0, 0],
            "material": material,
            "temp": 0,
        }
        for material in (materials or [])
    ]
    while len(ace.inventory) < 4:
        ace.inventory.append(
            {"status": "empty", "color": [0, 0, 0], "material": "", "temp": 0}
        )
    ace._info = {
        "dryer": {
            "status": dryer_status,
            "target_temp": 0,
            "duration": 0,
            "remain_time": 0,
        },
        "slots": [
            {"status": "empty", "type": ""} for _index in range(4)
        ],
    }
    ace._connected = connected
    ace.auto_drying_enabled = enabled
    ace.auto_drying_active = False
    ace.auto_drying_owned_by_auto = False
    ace.auto_drying_suppressed_for_job = False
    ace.auto_drying_temperature = 0
    ace.auto_drying_reason = "EMPTY"
    ace.auto_drying_print_state = "standby"
    ace.auto_drying_last_error = ""
    ace.auto_drying_notice_id = 0
    ace.auto_drying_notice_message = ""
    ace._auto_drying_job_active = False
    ace._auto_drying_print_samples = 0
    ace._auto_drying_pending_action = None
    ace._auto_drying_temperature_ceiling = 0
    ace._auto_drying_notices_seen = set()
    ace._auto_drying_retry_count = 0
    ace._auto_drying_next_retry = 0.0
    ace._auto_drying_max_retries = 3
    ace.transport = []

    def start(temperature, _eventtime):
        ace.transport.append(("start", temperature, 1440))
        ace.auto_drying_active = True
        ace.auto_drying_owned_by_auto = True
        ace.auto_drying_temperature = temperature
        ace._auto_drying_temperature_ceiling = temperature
        ace._info["dryer"]["status"] = "drying"
        ace._info["dryer"]["target_temp"] = temperature
        return True

    def stop(_eventtime, restart_temperature=0):
        ace.transport.append(("stop",))
        ace.auto_drying_active = False
        ace.auto_drying_owned_by_auto = False
        ace._info["dryer"]["status"] = "stop"
        if restart_temperature:
            start(restart_temperature, _eventtime)
        return True

    ace._queue_auto_drying_start = start
    ace._queue_auto_drying_stop = stop
    return ace


def tick(ace, state, eventtime=None):
    ace.print_stats.state = state
    if eventtime is None:
        ace.reactor.now += 1.0
    else:
        ace.reactor.now = float(eventtime)
    return ace._auto_drying_monitor(ace.reactor.now)


def running_auto_ace(temperature=60, materials=None):
    ace = make_auto_ace(
        enabled=True,
        materials=materials or ["ABS"],
        dryer_status="drying",
    )
    ace._auto_drying_job_active = True
    ace._auto_drying_print_samples = 2
    ace.auto_drying_active = True
    ace.auto_drying_owned_by_auto = True
    ace.auto_drying_temperature = temperature
    ace._auto_drying_temperature_ceiling = temperature
    ace._info["dryer"]["target_temp"] = temperature
    ace.print_stats.state = "printing"
    return ace


class AutoDryingPolicyTests(unittest.TestCase):
    def test_selects_material_safe_temperature(self):
        cases = [
            ([slot("PLA")], (45, "PLA_ONLY")),
            ([slot("PLA"), slot("ABS")], (50, "PLA_MIXED")),
            ([slot("PLA"), slot("PETG")], (50, "PLA_MIXED")),
            (
                [slot("ABS"), slot("ABSCF"), slot("PETG"), slot("PAHTCF")],
                (60, "HIGH_TEMP"),
            ),
            ([slot("PETCF"), slot("PEEK")], (60, "HIGH_TEMP")),
            ([slot("PLA"), slot("Mystery")], (45, "UNKNOWN")),
            ([slot("")], (45, "UNKNOWN")),
            ([], (0, "EMPTY")),
        ]
        for slots, expected in cases:
            with self.subTest(slots=slots):
                self.assertEqual(
                    ace_driver.select_auto_drying_policy(slots), expected
                )

    def test_ignores_explicitly_empty_slots(self):
        self.assertEqual(
            ace_driver.select_auto_drying_policy(
                [slot("ABS", "empty"), slot("PLA")]
            ),
            (45, "PLA_ONLY"),
        )


class AutoDryingLifecycleTests(unittest.TestCase):
    def test_two_printing_samples_start_owned_drying_once(self):
        ace = make_auto_ace(enabled=True, materials=["ABS"])
        tick(ace, "printing")
        self.assertEqual(ace.transport, [])
        tick(ace, "printing")
        self.assertEqual(ace.transport, [("start", 60, 1440)])
        self.assertTrue(ace.auto_drying_owned_by_auto)

    def test_paused_keeps_drying(self):
        ace = running_auto_ace(temperature=50, materials=["PLA", "ABS"])
        tick(ace, "paused")
        self.assertEqual(ace.transport, [])
        self.assertTrue(ace.auto_drying_owned_by_auto)

    def test_terminal_states_stop_only_owned_drying(self):
        for state in ("complete", "cancelled", "error", "standby"):
            with self.subTest(state=state):
                ace = running_auto_ace(temperature=45, materials=["PLA"])
                tick(ace, state)
                self.assertEqual(ace.transport, [("stop",)])

    def test_manual_drying_is_never_owned_or_stopped(self):
        ace = make_auto_ace(
            enabled=True, materials=["ABS"], dryer_status="drying"
        )
        tick(ace, "printing")
        tick(ace, "printing")
        tick(ace, "complete")
        self.assertEqual(ace.transport, [])
        self.assertFalse(ace.auto_drying_owned_by_auto)

    def test_manual_stop_suppresses_restart_for_current_job(self):
        ace = running_auto_ace(temperature=60, materials=["ABS"])
        ace.send_request = lambda **_kwargs: None
        ace.cmd_ACE_STOP_DRYING(FakeCommand())
        ace.transport.clear()
        tick(ace, "printing")
        tick(ace, "printing")
        self.assertTrue(ace.auto_drying_suppressed_for_job)
        self.assertEqual(ace.transport, [])

    def test_inventory_change_can_lower_but_not_raise_temperature(self):
        ace = running_auto_ace(temperature=60, materials=["ABS"])
        ace.inventory[1].update(status="ready", material="Mystery")
        tick(ace, "printing")
        self.assertEqual(
            ace.transport, [("stop",), ("start", 45, 1440)]
        )
        ace.transport.clear()
        ace.inventory[1].update(status="empty", material="")
        tick(ace, "printing")
        self.assertEqual(ace.transport, [])

    def test_empty_inventory_reports_once_and_does_not_start(self):
        ace = make_auto_ace(enabled=True, materials=[])
        tick(ace, "printing")
        tick(ace, "printing")
        tick(ace, "printing")
        self.assertEqual(ace.transport, [])
        self.assertEqual(ace.auto_drying_notice_id, 1)

    def test_natural_expiry_renews_during_long_print(self):
        ace = running_auto_ace(temperature=60, materials=["ABS"])
        ace._info["dryer"]["status"] = "stop"
        tick(ace, "printing")
        self.assertEqual(ace.transport, [("start", 60, 1440)])

    def test_disconnect_retries_are_bounded_without_pausing_print(self):
        ace = make_auto_ace(
            enabled=True, materials=["ABS"], connected=False
        )
        tick(ace, "printing", 1)
        tick(ace, "printing", 2)
        tick(ace, "printing", 32)
        tick(ace, "printing", 62)
        tick(ace, "printing", 92)
        tick(ace, "printing", 122)
        self.assertEqual(ace._auto_drying_retry_count, 3)
        self.assertEqual(ace.print_stats.state, "printing")
        self.assertIn("未连接", ace.auto_drying_last_error)

    def test_enable_and_disable_persist(self):
        ace = make_auto_ace(enabled=False, materials=["PLA"])
        ace.cmd_ACE_ENABLE_AUTO_DRYING(FakeCommand())
        self.assertTrue(ace.auto_drying_enabled)
        self.assertIn(
            "SAVE_VARIABLE VARIABLE=ace_auto_drying_enabled VALUE=True",
            ace.gcode.scripts,
        )
        ace.cmd_ACE_DISABLE_AUTO_DRYING(FakeCommand())
        self.assertFalse(ace.auto_drying_enabled)
        self.assertIn(
            "SAVE_VARIABLE VARIABLE=ace_auto_drying_enabled VALUE=False",
            ace.gcode.scripts,
        )


if __name__ == "__main__":
    unittest.main()
