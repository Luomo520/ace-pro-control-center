"""Tests for the Ace Pro Control Center Moonraker API boundary."""

from __future__ import annotations

import copy
import unittest

from moonraker.ace_status import AceStatus, load_component


def contains_chinese(value):
    return any("\u3400" <= char <= "\u9fff" for char in str(value))


class FakeRequest:
    def __init__(self, args=None, request_id="request-1"):
        self.args = args or {}
        self.request_id = request_id

    def get_args(self):
        return self.args

    def get_request_id(self):
        return self.request_id


class FakeKlippyApis:
    def __init__(self, query):
        self.query = query
        self.queries = []
        self.commands = []
        self.error = None

    async def query_objects(self, objects):
        self.queries.append(objects)
        if self.error:
            raise self.error
        return copy.deepcopy(self.query)

    async def run_gcode(self, command):
        self.commands.append(command)
        if self.error:
            raise self.error
        return "ok"


class FakeServer:
    def __init__(self, klippy):
        self.klippy = klippy
        self.endpoints = []

    def lookup_component(self, name):
        if name != "klippy_apis":
            raise KeyError(name)
        return self.klippy

    def register_endpoint(self, path, methods, callback):
        self.endpoints.append((path, methods, callback))


class FakeConfig:
    def __init__(self, server):
        self.server = server

    def get_server(self):
        return self.server


def driver_query(print_state="standby"):
    all_actions = {
        "select_tool": True,
        "unload": True,
        "feed": True,
        "retract": True,
        "enable_feed_assist": True,
        "disable_feed_assist": True,
        "start_drying": True,
        "stop_drying": True,
        "set_slot": True,
        "set_endless_spool": True,
        "calibrate": True,
        "recover": True,
    }
    return {
        "ace": {
            "current_tool": "T0",
            "path_locked": False,
            "toolchange_mode": "automatic",
            "toolchange_ready": True,
            "toolchange_blocked_reason": None,
            "toolchange_notice": None,
            "toolchange_notices": [],
            "path": {
                "busy": False,
                "state": "nozzle",
                "encoders": {
                    "shared": {
                        "configured": True,
                        "available": True,
                        "calibration_active": False,
                    },
                },
            },
            "feed_assist": {
                "enabled": False,
                "tool": None,
                "device_id": None,
                "slot": None,
            },
            "devices": {
                "ace0": {
                    "device_id": "ace0",
                    "model": "ace1",
                    "connected": True,
                    "physical_actions_enabled": True,
                    "state": "ready",
                    "capabilities": copy.deepcopy(all_actions),
                    "slots": [
                        {"index": index, "status": "ready"}
                        for index in range(4)
                    ],
                },
                "ace1": {
                    "device_id": "ace1",
                    "model": "ace2",
                    "connected": True,
                    "physical_actions_enabled": False,
                    "state": "ready",
                    "capabilities": copy.deepcopy(all_actions),
                    "slots": [
                        {"index": index, "status": "unknown"}
                        for index in range(4)
                    ],
                },
            },
            "capabilities": {"actions": copy.deepcopy(all_actions)},
        },
        "print_stats": {"state": print_state},
    }


class MoonrakerApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.klippy = FakeKlippyApis(driver_query())
        self.server = FakeServer(self.klippy)
        self.config = FakeConfig(self.server)
        self.component = AceStatus(self.config)

    def assert_user_error_is_chinese(self, response):
        self.assertFalse(response["ok"])
        error = response["error"]
        for field in ("message", "reason", "next_action"):
            self.assertIn(field, error)
            self.assertTrue(
                contains_chinese(error[field]),
                "%s must contain Chinese user text: %r" % (field, error[field]),
            )

    def assert_unavailable_reasons_are_chinese(self, actions):
        for action, capability in actions.items():
            if capability.get("available"):
                continue
            self.assertTrue(
                contains_chinese(capability.get("reason")),
                "%s has a non-Chinese reason: %r"
                % (action, capability.get("reason")),
            )

    async def action(self, action, params=None, confirm=False, **extra):
        payload = {
            "action": action,
            "params": params or {},
            "confirm": confirm,
            "client": "test-suite",
        }
        payload.update(extra)
        response = await self.component.handle_action_request(FakeRequest(payload))
        if not response.get("ok"):
            self.assert_user_error_is_chinese(response)
        return response

    def prepare_encoder_calibration_path(self):
        ace = self.klippy.query["ace"]
        ace["current_tool"] = None
        ace["path"]["state"] = "empty"
        ace["feed_assist"] = {
            "enabled": False,
            "tool": None,
            "device_id": None,
            "slot": None,
        }

    def test_load_component_registers_real_moonraker_endpoints(self):
        component = load_component(self.config)
        self.assertIsInstance(component, AceStatus)
        registered = {(path, tuple(methods)) for path, methods, _ in self.server.endpoints}
        self.assertIn(("/server/ace/status", ("GET",)), registered)
        self.assertIn(("/server/ace/capabilities", ("GET",)), registered)
        self.assertIn(("/server/ace/action", ("POST",)), registered)

    async def test_status_reads_cached_query_objects(self):
        response = await self.component.handle_status_request(FakeRequest())
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["print_state"], "standby")
        self.assertEqual(response["result"]["system"]["print_state"], "standby")
        self.assertEqual(response["result"]["toolchange_mode"], "automatic")
        self.assertTrue(response["result"]["toolchange_ready"])
        self.assertIsNone(response["result"]["toolchange_blocked_reason"])
        self.assertIsNone(response["result"]["toolchange_notice"])
        self.assertEqual(response["result"]["toolchange_notices"], [])
        self.assertEqual(response["result"]["devices"][0]["id"], "ace0")
        self.assertEqual(
            self.klippy.queries,
            [{"ace": None, "print_stats": ["state"]}],
        )
        self.assertEqual(self.klippy.commands, [])

    async def test_status_preserves_every_unseen_toolchange_notice(self):
        notices = [
            {
                "sequence": 41,
                "code": "toolchange_not_ready",
                "command": "T1",
                "message": "T1 was ignored.",
            },
            {
                "sequence": 42,
                "code": "toolchange_not_ready",
                "command": "TR",
                "message": "TR was ignored.",
            },
        ]
        ace = self.klippy.query["ace"]
        ace["toolchange_mode"] = "manual"
        ace["toolchange_ready"] = True
        ace["toolchange_blocked_reason"] = "manual_mode"
        ace["toolchange_notice"] = copy.deepcopy(notices[-1])
        ace["toolchange_notices"] = copy.deepcopy(notices)

        response = await self.component.handle_status_request(FakeRequest())

        self.assertTrue(response["ok"])
        status = response["result"]
        self.assertEqual(status["toolchange_mode"], "manual")
        self.assertFalse(status["toolchange_ready"])
        self.assertEqual(status["toolchange_blocked_reason"], "manual_mode")
        self.assertEqual(status["toolchange_notice"]["command"], "TR")
        self.assertTrue(contains_chinese(status["toolchange_notice"]["message"]))
        self.assertTrue(
            all(
                contains_chinese(item["message"])
                for item in status["toolchange_notices"]
            )
        )
        self.assertEqual(
            [item["sequence"] for item in status["toolchange_notices"]],
            [41, 42],
        )
        self.assertNotIn("error", response)

    async def test_latest_only_notice_is_adapted_for_queue_clients(self):
        notice = {
            "sequence": 7,
            "code": "toolchange_not_ready",
            "command": "t3",
            "message": "T3 was ignored.",
        }
        ace = self.klippy.query["ace"]
        ace["toolchange_notice"] = notice
        ace.pop("toolchange_notices")

        response = await self.component.handle_status_request(FakeRequest())

        normalized = dict(
            notice,
            command="T3",
            message="已忽略 T3。ACE 自动换料尚未配置，当前仅可使用辅助送料。",
        )
        self.assertEqual(response["result"]["toolchange_notice"], normalized)
        self.assertEqual(response["result"]["toolchange_notices"], [normalized])

    async def test_legacy_core_without_toolchange_fields_remains_automatic(self):
        ace = self.klippy.query["ace"]
        for field in (
            "toolchange_mode",
            "toolchange_ready",
            "toolchange_blocked_reason",
            "toolchange_notice",
            "toolchange_notices",
        ):
            ace.pop(field)

        status = await self.component.handle_status_request(FakeRequest())
        action = await self.action("select_tool", {"tool": "T1"}, confirm=True)

        self.assertEqual(status["result"]["toolchange_mode"], "automatic")
        self.assertTrue(status["result"]["toolchange_ready"])
        self.assertIsNone(status["result"]["toolchange_notice"])
        self.assertEqual(status["result"]["toolchange_notices"], [])
        self.assertTrue(action["ok"])

    async def test_invalid_explicit_toolchange_contract_fails_closed(self):
        ace = self.klippy.query["ace"]
        ace["toolchange_mode"] = None
        ace["toolchange_ready"] = "yes"

        status = await self.component.handle_status_request(FakeRequest())
        action = await self.action("select_tool", {"tool": "T0"}, confirm=True)

        self.assertEqual(status["result"]["toolchange_mode"], "manual")
        self.assertFalse(status["result"]["toolchange_ready"])
        self.assertFalse(action["ok"])
        self.assertEqual(action["error"]["code"], "toolchange_unavailable")

    async def test_wrapped_klippy_status_response_is_supported(self):
        query = {"status": driver_query()}
        component = AceStatus(
            self.config,
            status_provider=lambda: query,
            action_runner=lambda command: "unused",
        )
        response = await component.handle_status_request(FakeRequest())
        self.assertTrue(response["ok"])
        self.assertEqual(response["result"]["devices"][0]["id"], "ace0")

    async def test_status_failure_is_structured(self):
        self.klippy.error = RuntimeError("disconnected secret")
        response = await self.component.handle_status_request(FakeRequest())
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "status_unavailable")
        self.assertTrue(response["retryable"])
        self.assertNotIn("secret", str(response))
        self.assert_user_error_is_chinese(response)

    async def test_capability_failure_is_structured_and_chinese(self):
        self.klippy.error = RuntimeError("disconnected secret")

        response = await self.component.handle_capabilities_request(FakeRequest())

        self.assertEqual(response["error"]["code"], "status_unavailable")
        self.assertNotIn("secret", str(response))
        self.assert_user_error_is_chinese(response)

    async def test_select_tool_uses_fixed_command(self):
        response = await self.action("select_tool", {"tool": "T3"}, confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(self.klippy.commands, ["ACE_CHANGE_TOOL TOOL=T3"])
        self.assertEqual(response["result"]["target"]["device"], "ace0")
        self.assertEqual(response["result"]["target"]["slot"], 3)

    async def test_unload_uses_tool_tr(self):
        response = await self.action("unload", confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(self.klippy.commands, ["ACE_CHANGE_TOOL TOOL=TR"])

    async def test_manual_mode_disables_only_automatic_toolchange_actions(self):
        ace = self.klippy.query["ace"]
        ace["toolchange_mode"] = "manual"
        ace["toolchange_ready"] = False
        ace["toolchange_blocked_reason"] = "manual_mode"

        status_response = await self.component.handle_status_request(FakeRequest())
        status = status_response["result"]
        capabilities_response = await self.component.handle_capabilities_request(
            FakeRequest()
        )
        api_capabilities = capabilities_response["result"]
        root_actions = status["capabilities"]["actions"]
        device_actions = status["devices"][0]["capabilities"]["actions"]
        for action in ("select_tool", "unload", "set_endless_spool"):
            self.assertFalse(root_actions[action]["available"])
            self.assertFalse(device_actions[action]["available"])
            self.assertEqual(
                root_actions[action]["reason"],
                "当前处于手动模式，ACE 自动换料未启用。",
            )
        for action in (
            "feed",
            "retract",
            "set_slot",
            "start_drying",
            "enable_feed_assist",
            "disable_feed_assist",
        ):
            self.assertTrue(device_actions[action]["available"])
        self.assertEqual(api_capabilities["toolchange_mode"], "manual")
        self.assertFalse(api_capabilities["toolchange_ready"])
        self.assertFalse(api_capabilities["actions"]["select_tool"]["available"])
        self.assertTrue(
            api_capabilities["actions"]["enable_feed_assist"]["available"]
        )

        blocked = await self.action(
            "select_tool", {"tool": "T1"}, confirm=True
        )
        manual_feed = await self.action(
            "feed",
            {"device": "ace0", "slot": 0, "length": 10},
            confirm=True,
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error"]["code"], "toolchange_unavailable")
        self.assertTrue(manual_feed["ok"])
        self.assertEqual(self.klippy.commands, ["ACE_FEED TOOL=T0 LENGTH=10 SPEED=80"])

    async def test_not_ready_blocks_unload_and_endless_spool_enable(self):
        ace = self.klippy.query["ace"]
        ace["toolchange_mode"] = "automatic"
        ace["toolchange_ready"] = False
        ace["toolchange_blocked_reason"] = "machine_macros_not_configured"

        unload = await self.action("unload", confirm=True)
        enable = await self.action("set_endless_spool", {"enabled": True})
        disable = await self.action("set_endless_spool", {"enabled": False})

        self.assertFalse(unload["ok"])
        self.assertEqual(unload["error"]["code"], "toolchange_unavailable")
        self.assertFalse(enable["ok"])
        self.assertEqual(enable["error"]["code"], "toolchange_unavailable")
        self.assertTrue(disable["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_SET_ENDLESS_SPOOL ENABLE=0"],
        )

    async def test_confirmation_is_required(self):
        response = await self.action("select_tool", {"tool": "T0"})
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "confirmation_required")
        self.assertEqual(self.klippy.commands, [])

    async def test_ace2_physical_action_is_always_rejected(self):
        response = await self.action("select_tool", {"tool": "T4"}, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "ace2_read_only")
        self.assertEqual(self.klippy.commands, [])

    async def test_physical_actions_enabled_is_enforced(self):
        self.klippy.query["ace"]["devices"]["ace0"]["physical_actions_enabled"] = False
        response = await self.action("select_tool", {"tool": "T0"}, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "physical_actions_disabled")

    async def test_device_connection_is_enforced(self):
        self.klippy.query["ace"]["devices"]["ace0"]["connected"] = False
        response = await self.action("feed", {
            "device": "ace0", "slot": 0, "length": 100, "speed": 80
        }, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "device_offline")
        self.assertTrue(response["retryable"])

    async def test_capability_is_required(self):
        self.klippy.query["ace"]["capabilities"] = {}
        self.klippy.query["ace"]["devices"]["ace0"]["capabilities"] = {}
        response = await self.action("feed", {
            "device": "ace0", "slot": 0, "length": 100, "speed": 80
        }, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "capability_unavailable")

    async def test_printing_blocks_manual_tool_change(self):
        self.klippy.query["print_stats"]["state"] = "printing"
        response = await self.action("select_tool", {"tool": "T0"}, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "print_state_blocked")
        self.assertEqual(self.klippy.commands, [])

    async def test_refresh_is_allowed_while_printing(self):
        self.klippy.query["print_stats"]["state"] = "printing"
        response = await self.action("refresh", {"device": "ace0"})
        self.assertTrue(response["ok"])
        self.assertEqual(self.klippy.commands, ["ACE_REFRESH DEVICE=ace0"])

    async def test_material_endless_spool_mode_reaches_klipper(self):
        response = await self.action(
            "set_endless_spool", {"enabled": True, "match_mode": "material"}
        )
        self.assertTrue(response["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_SET_ENDLESS_SPOOL ENABLE=1 MATCH_MODE=material"],
        )

    async def test_shared_path_lock_blocks_conflicting_action(self):
        self.klippy.query["ace"]["path_locked"] = True
        response = await self.action("feed", {
            "device": "ace0", "slot": 0, "length": 100, "speed": 80
        }, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "path_busy")

    async def test_shared_encoder_calibration_uses_fixed_commands_without_device_gate(self):
        self.prepare_encoder_calibration_path()
        for device in self.klippy.query["ace"]["devices"].values():
            device["physical_actions_enabled"] = False
            device["connected"] = False

        start = await self.action("encoder_calibration_start")
        shared = self.klippy.query["ace"]["path"]["encoders"]["shared"]
        shared["calibration_active"] = True
        finish = await self.action(
            "encoder_calibration_finish", {"length": 123.5}
        )
        shared["available"] = False
        cancel = await self.action("encoder_calibration_cancel")

        self.assertTrue(start["ok"])
        self.assertTrue(finish["ok"])
        self.assertTrue(cancel["ok"])
        self.assertIsNone(start["result"]["target"]["device"])
        self.assertEqual(
            self.klippy.commands,
            [
                "ACE_ENCODER_CALIBRATE START=1",
                "ACE_ENCODER_CALIBRATE LENGTH=123.5",
                "ACE_ENCODER_CALIBRATE CANCEL=1",
            ],
        )

    async def test_shared_encoder_calibration_request_validation_is_strict(self):
        responses = [
            await self.action("encoder_calibration_finish"),
            await self.action(
                "encoder_calibration_start", {"device": "ace0"}
            ),
            await self.action(
                "encoder_calibration_cancel", {"length": 100}
            ),
            await self.action(
                "encoder_calibration_start", {}, gcode="G28"
            ),
        ]
        for length in (0, 0.009, 2000.01, True, "100"):
            responses.append(
                await self.action(
                    "encoder_calibration_finish", {"length": length}
                )
            )

        self.assertEqual(responses[0]["error"]["code"], "missing_parameter")
        self.assertEqual(responses[1]["error"]["code"], "unknown_parameter")
        self.assertEqual(responses[2]["error"]["code"], "unknown_parameter")
        self.assertEqual(responses[3]["error"]["code"], "unknown_parameter")
        for response in responses[4:]:
            self.assertEqual(response["error"]["code"], "invalid_parameter")
        self.assertEqual(self.klippy.queries, [])
        self.assertEqual(self.klippy.commands, [])

    async def test_encoder_calibration_finish_accepts_length_boundaries(self):
        self.prepare_encoder_calibration_path()
        self.klippy.query["ace"]["path"]["encoders"]["shared"][
            "calibration_active"
        ] = True

        minimum = await self.action(
            "encoder_calibration_finish", {"length": 0.01}
        )
        maximum = await self.action(
            "encoder_calibration_finish", {"length": 2000}
        )

        self.assertTrue(minimum["ok"])
        self.assertTrue(maximum["ok"])
        self.assertEqual(
            self.klippy.commands,
            [
                "ACE_ENCODER_CALIBRATE LENGTH=0.01",
                "ACE_ENCODER_CALIBRATE LENGTH=2000",
            ],
        )

    async def test_shared_encoder_calibration_is_blocked_while_printing(self):
        self.klippy.query["print_stats"]["state"] = "printing"
        start = await self.action("encoder_calibration_start")
        self.klippy.query["ace"]["path"]["encoders"]["shared"][
            "calibration_active"
        ] = True
        finish = await self.action(
            "encoder_calibration_finish", {"length": 100}
        )
        cancel = await self.action("encoder_calibration_cancel")

        for response in (start, finish, cancel):
            self.assertFalse(response["ok"])
            self.assertEqual(response["error"]["code"], "print_state_blocked")
        self.assertEqual(self.klippy.commands, [])

    async def test_encoder_calibration_cancel_can_release_a_busy_path(self):
        path = self.klippy.query["ace"]["path"]
        path["busy"] = True
        start = await self.action("encoder_calibration_start")
        path["encoders"]["shared"]["calibration_active"] = True
        path["encoders"]["shared"]["available"] = False
        finish = await self.action(
            "encoder_calibration_finish", {"length": 100}
        )
        cancel = await self.action("encoder_calibration_cancel")

        self.assertEqual(start["error"]["code"], "path_busy")
        self.assertEqual(finish["error"]["code"], "path_busy")
        self.assertTrue(cancel["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_ENCODER_CALIBRATE CANCEL=1"],
        )

    async def test_shared_encoder_capabilities_follow_calibration_state(self):
        self.prepare_encoder_calibration_path()
        inactive = await self.component.handle_capabilities_request(FakeRequest())
        inactive_actions = inactive["result"]["actions"]

        self.assertTrue(inactive_actions["encoder_calibration_start"]["available"])
        for action in (
            "encoder_calibration_finish",
            "encoder_calibration_cancel",
        ):
            self.assertFalse(inactive_actions[action]["available"])
            self.assertIn("尚未开始", inactive_actions[action]["reason"])
        finish_capability = inactive_actions["encoder_calibration_finish"]
        self.assertEqual(finish_capability["required_params"], ["length"])
        self.assertFalse(finish_capability["physical"])
        self.assertFalse(finish_capability["allowed_when_printing"])
        self.assertFalse(finish_capability["confirmation_required"])

        status = await self.component.handle_status_request(FakeRequest())
        status_actions = status["result"]["capabilities"]["actions"]
        self.assertTrue(status_actions["encoder_calibration_start"]["available"])
        self.assertNotIn(
            "encoder_calibration_start",
            status["result"]["devices"][0]["capabilities"]["actions"],
        )

        shared = self.klippy.query["ace"]["path"]["encoders"]["shared"]
        shared["calibration_active"] = True
        active = await self.component.handle_capabilities_request(FakeRequest())
        active_actions = active["result"]["actions"]
        self.assertFalse(active_actions["encoder_calibration_start"]["available"])
        self.assertIn(
            "正在进行",
            active_actions["encoder_calibration_start"]["reason"],
        )
        self.assertTrue(active_actions["encoder_calibration_finish"]["available"])
        self.assertTrue(active_actions["encoder_calibration_cancel"]["available"])

        shared["available"] = False
        unavailable = await self.component.handle_capabilities_request(FakeRequest())
        unavailable_actions = unavailable["result"]["actions"]
        self.assertFalse(
            unavailable_actions["encoder_calibration_finish"]["available"]
        )
        self.assertIn(
            "当前不可用",
            unavailable_actions["encoder_calibration_finish"]["reason"],
        )
        self.assertTrue(
            unavailable_actions["encoder_calibration_cancel"]["available"]
        )

    async def test_encoder_calibration_start_requires_an_empty_unowned_path(self):
        loaded = await self.component.handle_capabilities_request(FakeRequest())
        loaded_action = loaded["result"]["actions"]["encoder_calibration_start"]
        self.assertFalse(loaded_action["available"])
        self.assertIn("卸载当前工具通道", loaded_action["reason"])

        ace = self.klippy.query["ace"]
        ace["current_tool"] = None
        ace["path"]["state"] = "loading"
        occupied = await self.component.handle_capabilities_request(FakeRequest())
        occupied_action = occupied["result"]["actions"]["encoder_calibration_start"]
        self.assertFalse(occupied_action["available"])
        self.assertIn("耗材路径为空", occupied_action["reason"])

        ace["path"]["state"] = "empty"
        ace["feed_assist"]["enabled"] = True
        assisted = await self.component.handle_capabilities_request(FakeRequest())
        assisted_action = assisted["result"]["actions"]["encoder_calibration_start"]
        self.assertFalse(assisted_action["available"])
        self.assertIn("关闭辅助送料", assisted_action["reason"])

        ace["feed_assist"]["enabled"] = False
        ready = await self.component.handle_capabilities_request(FakeRequest())
        self.assertTrue(
            ready["result"]["actions"]["encoder_calibration_start"]["available"]
        )

    async def test_encoder_calibration_action_rejections_match_shared_state(self):
        self.prepare_encoder_calibration_path()
        shared = self.klippy.query["ace"]["path"]["encoders"]["shared"]
        shared["available"] = False

        start = await self.action("encoder_calibration_start")
        shared["calibration_active"] = True
        duplicate_start = await self.action("encoder_calibration_start")
        unavailable_finish = await self.action(
            "encoder_calibration_finish", {"length": 100}
        )
        cancel = await self.action("encoder_calibration_cancel")

        shared["calibration_active"] = False
        inactive_finish = await self.action(
            "encoder_calibration_finish", {"length": 100}
        )
        inactive_cancel = await self.action("encoder_calibration_cancel")
        shared["configured"] = False
        unconfigured_start = await self.action("encoder_calibration_start")

        self.assertTrue(start["ok"])
        self.assertIn("正在进行", duplicate_start["error"]["message"])
        self.assertIn("当前不可用", unavailable_finish["error"]["message"])
        self.assertTrue(cancel["ok"])
        self.assertIn("尚未开始", inactive_finish["error"]["message"])
        self.assertIn("尚未开始", inactive_cancel["error"]["message"])
        self.assertIn("未配置", unconfigured_start["error"]["message"])
        for response in (
            duplicate_start,
            unavailable_finish,
            inactive_finish,
            inactive_cancel,
            unconfigured_start,
        ):
            self.assertEqual(response["error"]["code"], "capability_unavailable")
        self.assertEqual(
            self.klippy.commands,
            [
                "ACE_ENCODER_CALIBRATE START=1",
                "ACE_ENCODER_CALIBRATE CANCEL=1",
            ],
        )

    async def test_unconfigured_and_legacy_status_disable_encoder_calibration(self):
        shared = self.klippy.query["ace"]["path"]["encoders"]["shared"]
        shared["configured"] = False
        unconfigured = await self.component.handle_capabilities_request(FakeRequest())

        for action in (
            "encoder_calibration_start",
            "encoder_calibration_finish",
            "encoder_calibration_cancel",
        ):
            capability = unconfigured["result"]["actions"][action]
            self.assertFalse(capability["available"])
            self.assertIn("未配置", capability["reason"])

        self.klippy.query["ace"].pop("path")
        legacy_status = await self.component.handle_status_request(FakeRequest())
        legacy_capabilities = await self.component.handle_capabilities_request(
            FakeRequest()
        )

        self.assertTrue(legacy_status["ok"])
        self.assertTrue(legacy_capabilities["ok"])
        for response in (legacy_status, legacy_capabilities):
            if response is legacy_status:
                actions = response["result"]["capabilities"]["actions"]
            else:
                actions = response["result"]["actions"]
            for action in (
                "encoder_calibration_start",
                "encoder_calibration_finish",
                "encoder_calibration_cancel",
                ):
                self.assertFalse(actions[action]["available"])
                self.assertIn("未配置", actions[action]["reason"])

    async def test_generic_calibrate_action_contract_is_unchanged(self):
        success = await self.action(
            "calibrate",
            {"device": "ace0", "mode": "probe"},
            confirm=True,
        )
        self.klippy.query["ace"]["devices"]["ace0"][
            "physical_actions_enabled"
        ] = False
        blocked = await self.action(
            "calibrate",
            {"device": "ace0", "mode": "probe"},
            confirm=True,
        )

        self.assertTrue(success["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_CALIBRATE DEVICE=ace0 MODE=probe"],
        )
        self.assertEqual(blocked["error"]["code"], "physical_actions_disabled")

    async def test_feed_parameters_have_fixed_translation(self):
        response = await self.action("feed", {
            "device": "ace0", "slot": 2, "length": 120.5, "speed": 75
        }, confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_FEED TOOL=T2 LENGTH=120.5 SPEED=75"],
        )

    async def test_feed_assist_device_slot_forwards_resolved_target(self):
        response = await self.action(
            "enable_feed_assist", {"device": "ace0", "slot": 2}, confirm=True
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            response["result"]["target"],
            {"device": "ace0", "tool": "T2", "slot": 2},
        )
        self.assertEqual(
            self.klippy.commands,
            ["ACE_ENABLE_FEED_ASSIST DEVICE=ace0 TOOL=T2 SLOT=2 CONFIRM=1"],
        )

    async def test_feed_assist_accepts_tool_and_legacy_index_aliases(self):
        by_tool = await self.action(
            "enable_feed_assist", {"tool_id": "T1"}, confirm=True
        )
        by_index = await self.action(
            "disable_feed_assist", {"device_id": "ace0", "index": 1}
        )

        self.assertTrue(by_tool["ok"])
        self.assertTrue(by_index["ok"])
        self.assertEqual(
            self.klippy.commands,
            [
                "ACE_ENABLE_FEED_ASSIST DEVICE=ace0 TOOL=T1 SLOT=1 CONFIRM=1",
                "ACE_DISABLE_FEED_ASSIST DEVICE=ace0 TOOL=T1 SLOT=1",
            ],
        )

    async def test_feed_assist_rejects_missing_or_conflicting_target(self):
        missing = await self.action("enable_feed_assist", {"device": "ace0"})
        conflict = await self.action(
            "enable_feed_assist",
            {"device": "ace0", "tool": "T1", "slot": 2},
        )

        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "missing_parameter")
        self.assertFalse(conflict["ok"])
        self.assertEqual(conflict["error"]["code"], "target_mismatch")
        self.assertEqual(self.klippy.commands, [])

    async def test_feed_assist_obeys_device_and_protocol_capability_gates(self):
        self.klippy.query["ace"]["devices"]["ace0"][
            "physical_actions_enabled"
        ] = False
        disabled = await self.action(
            "enable_feed_assist", {"device": "ace0", "slot": 0}, confirm=True
        )
        self.assertEqual(disabled["error"]["code"], "physical_actions_disabled")

        self.klippy.query["ace"]["devices"]["ace0"][
            "physical_actions_enabled"
        ] = True
        self.klippy.query["ace"]["capabilities"]["actions"].pop(
            "enable_feed_assist"
        )
        self.klippy.query["ace"]["devices"]["ace0"]["capabilities"].pop(
            "enable_feed_assist"
        )
        self.klippy.query["ace"]["devices"]["ace0"]["capabilities"].pop(
            "disable_feed_assist"
        )
        unavailable = await self.action(
            "enable_feed_assist", {"device": "ace0", "slot": 0}, confirm=True
        )
        self.assertEqual(unavailable["error"]["code"], "capability_unavailable")
        self.assertEqual(self.klippy.commands, [])

    async def test_feed_assist_is_unavailable_for_ace2(self):
        status = await self.component.handle_status_request(FakeRequest())
        response = await self.action(
            "enable_feed_assist", {"tool": "T4"}, confirm=True
        )

        capability = status["result"]["devices"][1]["capabilities"]["actions"][
            "enable_feed_assist"
        ]
        self.assertFalse(capability["available"])
        self.assertIn("ACE2", capability["reason"])
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "ace2_read_only")
        self.assertEqual(self.klippy.commands, [])

    async def test_feed_assist_print_state_policy_matches_risk_direction(self):
        self.klippy.query["print_stats"]["state"] = "printing"
        enable = await self.action(
            "enable_feed_assist", {"device": "ace0", "slot": 0}, confirm=True
        )
        disable = await self.action(
            "disable_feed_assist", {"device": "ace0", "slot": 0}
        )

        self.assertTrue(enable["ok"])
        self.assertTrue(disable["ok"])
        self.assertEqual(
            self.klippy.commands,
            [
                "ACE_ENABLE_FEED_ASSIST DEVICE=ace0 TOOL=T0 SLOT=0 CONFIRM=1",
                "ACE_DISABLE_FEED_ASSIST DEVICE=ace0 TOOL=T0 SLOT=0",
            ],
        )

    async def test_disable_feed_assist_can_release_a_busy_path(self):
        self.klippy.query["ace"]["path_locked"] = True

        response = await self.action(
            "disable_feed_assist", {"device": "ace0", "slot": 0}
        )

        self.assertTrue(response["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_DISABLE_FEED_ASSIST DEVICE=ace0 TOOL=T0 SLOT=0"],
        )

    async def test_frontend_parameter_names_are_normalized(self):
        response = await self.action("start_drying", {
            "device_id": "ace0", "temperature": 45, "duration_minutes": 240
        }, confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_START_DRYING DEVICE=ace0 TEMP=45 DURATION=240"],
        )

    async def test_feed_without_slot_uses_current_loaded_tool(self):
        response = await self.action("feed", {
            "device_id": "ace0", "length": 20
        }, confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(self.klippy.commands, ["ACE_FEED TOOL=T0 LENGTH=20 SPEED=80"])

    async def test_feed_without_resolvable_tool_is_rejected(self):
        self.klippy.query["ace"]["current_tool"] = None
        response = await self.action("feed", {
            "device_id": "ace0", "length": 20
        }, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "target_unavailable")

    async def test_list_device_status_and_protocol_capabilities_are_supported(self):
        self.klippy.query["ace"]["devices"] = list(
            self.klippy.query["ace"]["devices"].values()
        )
        self.klippy.query["ace"]["capabilities"] = {}
        ace0 = self.klippy.query["ace"]["devices"][0]
        ace0["capabilities"] = {
            "physical_actions": True,
            "feed": True,
            "retract": True,
            "drying": True,
            "inventory": True,
            "status": True,
        }
        status = await self.component.handle_status_request(FakeRequest())
        actions = status["result"]["devices"][0]["capabilities"]["actions"]
        self.assertTrue(actions["select_tool"]["available"])
        self.assertTrue(actions["set_slot"]["available"])
        self.assertTrue(actions["start_drying"]["available"])

        response = await self.action("select_tool", {"tool": "T0"}, confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(self.klippy.commands, ["ACE_CHANGE_TOOL TOOL=T0"])

    async def test_nested_path_busy_state_is_enforced(self):
        self.klippy.query["ace"]["path"] = {"busy": True}
        response = await self.action("select_tool", {"tool": "T0"}, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "path_busy")

    async def test_frontend_path_lock_state_is_enforced(self):
        self.klippy.query["ace"]["path_lock"] = {"locked": True}
        response = await self.action("select_tool", {"tool": "T0"}, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "path_busy")

    async def test_dryer_uses_klipper_temp_parameter(self):
        response = await self.action("start_drying", {
            "device": "ace0", "temperature": 55, "duration": 120
        }, confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_START_DRYING DEVICE=ace0 TEMP=55 DURATION=120"],
        )

    async def test_recovery_maps_to_reconnect_boundary(self):
        response = await self.action("recover", {"device": "ace0"}, confirm=True)
        self.assertTrue(response["ok"])
        self.assertEqual(self.klippy.commands, ["ACE_RECONNECT DEVICE=ace0"])

    async def test_recovery_is_rejected_while_path_transaction_is_busy(self):
        self.klippy.query["ace"]["path"] = {"busy": True}
        response = await self.action("recover", {"device": "ace0"}, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "path_busy")
        self.assertEqual(self.klippy.commands, [])

    async def test_diagnose_reads_cache_without_gcode(self):
        response = await self.action("diagnose", {"device": "ace0", "slot": 2})
        self.assertTrue(response["ok"])
        diagnostic = response["result"]["diagnostic"]
        self.assertEqual(diagnostic["device"], "ace0")
        self.assertEqual(diagnostic["slot_status"]["index"], 2)
        self.assertEqual(self.klippy.commands, [])

    async def test_unknown_and_raw_gcode_fields_are_rejected(self):
        response = await self.action(
            "refresh", {}, gcode="G28", command="ACE_CHANGE_TOOL TOOL=T0"
        )
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "unknown_parameter")
        self.assertEqual(self.klippy.queries, [])
        self.assertEqual(self.klippy.commands, [])

    async def test_newline_in_inventory_text_cannot_inject_gcode(self):
        response = await self.action("set_slot", {
            "device": "ace0", "slot": 0, "material": "PLA\nG28"
        })
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_parameter")
        self.assertEqual(self.klippy.commands, [])

    async def test_slot_inventory_can_be_cleared_through_the_whitelist(self):
        response = await self.action("set_slot", {
            "device": "ace0",
            "slot": 2,
            "material": "UNKNOWN",
            "color": "#808080",
            "temperature": 0,
            "status": "empty",
        })
        self.assertTrue(response["ok"])
        self.assertEqual(
            self.klippy.commands,
            ["ACE_SET_SLOT DEVICE=ace0 SLOT=2 MATERIAL=UNKNOWN COLOR=#808080 TEMP=0 STATUS=empty"],
        )

    async def test_unknown_slot_status_is_rejected(self):
        response = await self.action("set_slot", {
            "device": "ace0", "slot": 0, "status": "removed"
        })
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_parameter")
        self.assertEqual(self.klippy.commands, [])

    async def test_invalid_tool_and_range_are_rejected(self):
        response = await self.action("select_tool", {"tool": "T16"}, confirm=True)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "invalid_tool")
        response = await self.action("feed", {
            "device": "ace0", "slot": 4, "length": 1, "speed": 1
        }, confirm=True)
        self.assertEqual(response["error"]["code"], "invalid_parameter")

    async def test_action_runner_failure_is_structured(self):
        async def fail(command):
            raise RuntimeError("driver internal details")

        component = AceStatus(
            self.config,
            status_provider=lambda: driver_query(),
            action_runner=fail,
        )
        response = await component.handle_action_request(FakeRequest({
            "action": "select_tool",
            "params": {"tool": "T0"},
            "confirm": True,
            "client": "test-suite",
        }))
        self.assertFalse(response["ok"])
        self.assertEqual(response["state"], "failed")
        self.assertEqual(response["error"]["code"], "execution_failed")
        self.assertNotIn("internal details", str(response))
        self.assert_user_error_is_chinese(response)

    async def test_capabilities_describe_ace2_as_read_only(self):
        response = await self.component.handle_capabilities_request(FakeRequest())
        self.assertTrue(response["ok"])
        actions = response["result"]["actions"]
        self.assert_unavailable_reasons_are_chinese(actions)
        self.assertTrue(actions["select_tool"]["physical"])
        self.assertTrue(actions["select_tool"]["confirmation_required"])
        self.assertTrue(actions["enable_feed_assist"]["available"])
        self.assertTrue(actions["enable_feed_assist"]["allowed_when_printing"])
        self.assertTrue(actions["enable_feed_assist"]["confirmation_required"])
        self.assertTrue(actions["disable_feed_assist"]["allowed_when_printing"])
        self.assertEqual(response["result"]["toolchange_mode"], "automatic")
        self.assertTrue(response["result"]["toolchange_ready"])
        self.assertEqual(response["result"]["device_limit"], 4)

        status = await self.component.handle_status_request(FakeRequest())
        for device in status["result"]["devices"]:
            self.assert_unavailable_reasons_are_chinese(
                device["capabilities"]["actions"]
            )

    async def test_status_feed_assist_confirmation_matches_api_contract(self):
        self.klippy.query["ace"]["devices"]["ace0"]["capabilities"] = {
            "physical_actions": True,
            "feed_assist": True,
        }

        response = await self.component.handle_status_request(FakeRequest())
        capability = response["result"]["devices"][0]["capabilities"]["actions"][
            "enable_feed_assist"
        ]

        self.assertTrue(capability["requires_confirmation"])
        self.assertTrue(capability["confirmation_required"])

    async def test_sync_injected_boundaries_are_supported(self):
        commands = []
        component = AceStatus(
            self.config,
            status_provider=lambda: driver_query(),
            action_runner=lambda command: commands.append(command) or "ok",
        )
        response = await component.handle_action_request(FakeRequest({
            "action": "select_tool",
            "params": {"tool": "T1"},
            "confirm": True,
            "client": "test-suite",
        }))
        self.assertTrue(response["ok"])
        self.assertEqual(commands, ["ACE_CHANGE_TOOL TOOL=T1"])


if __name__ == "__main__":
    unittest.main()
