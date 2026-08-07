from __future__ import annotations

from types import SimpleNamespace

import pytest

from ace_driver import __version__
from ace_driver.config import (
    TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX,
    SharedConfig,
)
from ace_driver.device import AceDevice
from ace_driver.errors import AceBusyError, AceCapabilityError, AceSafetyError
from ace_driver.manager import AceManager, parse_tool, tool_target


def contains_chinese(value):
    return any("\u3400" <= char <= "\u9fff" for char in str(value))


CALIBRATED_BYPASS_SHARED = {
    "toolhead_sensor_bypass": True,
    "toolhead_sensor_bypass_calibrated": True,
    "toolhead_sensor_bypass_load_length": 25,
}

MULTI_ACE_SHARED = {
    **CALIBRATED_BYPASS_SHARED,
    "ace0_hub_retract_length": 20,
    "ace1_hub_retract_length": 20,
    "ace2_hub_retract_length": 20,
    "ace3_hub_retract_length": 20,
}


class FakeProtocol:
    name = "fake"
    capabilities = {
        "select_tool",
        "unload",
        "feed",
        "retract",
        "enable_feed_assist",
        "disable_feed_assist",
        "start_drying",
        "stop_drying",
    }

    def encode_request(self, method, params):
        return (method, params)

    def decode_response(self, value):
        return value

    def normalize_status(self, _value):
        return {"state": "ready", "slots": [{"status": "ready"}] * 4}


class FakeTransport:
    def __init__(self):
        self.opened = False
        self.requests = []

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def request(self, value):
        self.requests.append(value)
        if value[0] == "get_status":
            return {"ok": True, "result": {"slots": [{"status": "ready"}] * 4}}
        return {"ok": True, "result": {"accepted": True, "completed": True}}


class SensorTransport(FakeTransport):
    def __init__(self, sensors, *, device_id="ace0", asynchronous=True):
        super().__init__()
        self.sensors = sensors
        self.device_id = device_id
        self.asynchronous = asynchronous

    def request(self, value):
        response = super().request(value)
        if value[0] == "feed":
            self.sensors["upper"] = True
            self.sensors["rdm"] = True
            self.sensors[self.device_id + "_hub"] = True
            if self.asynchronous:
                response["result"].pop("completed", None)
        elif value[0] == "retract" and self.sensors.get("upper"):
            self.sensors["upper"] = False
            self.sensors["lower"] = False
            self.sensors["rdm"] = False
            self.sensors[self.device_id + "_hub"] = False
        return response


class FakeEncoder:
    def __init__(
        self,
        *,
        mode="monitor",
        available=True,
        resolution=1.0,
        fault=None,
    ):
        self.mode = mode
        self.available = available
        self.resolution = resolution
        self.finish_fault = fault
        self.status_fault = None
        self.motions = []
        self.cancelled = []
        self.clear_count = 0
        self.calibration_started = False
        self.cancel_count = 0
        self.counts = 10

    def get_status(self):
        return {
            "configured": True,
            "available": self.available,
            "mode": self.mode,
            "calibrated": self.resolution > 0,
            "resolution": self.resolution if self.resolution > 0 else None,
            "detection_length": 20.0,
            "counts": self.counts,
            "position": self.counts * self.resolution if self.resolution > 0 else None,
            "tracking_ratio": None,
            "calibration_active": self.calibration_started,
            "last_event": None,
            "fault": self.status_fault,
        }

    def set_resolution(self, resolution):
        self.resolution = float(resolution)

    def begin_motion(
        self, action, device_id, commanded_length, *, validation="movement"
    ):
        token = {
            "action": action,
            "device_id": device_id,
            "commanded_length": commanded_length,
            "validation": validation,
        }
        self.motions.append(token)
        return token

    def finish_motion(self, token, *, command_completed=True):
        self.status_fault = self.finish_fault
        return {
            "mode": self.mode,
            "action": token["action"],
            "device_id": token["device_id"],
            "commanded_length": token["commanded_length"],
            "command_completed": command_completed,
            "validation": token["validation"],
            "fault": self.finish_fault,
        }

    def cancel_motion(self, token):
        self.cancelled.append(token)

    def clear_fault(self):
        self.finish_fault = None
        self.status_fault = None
        self.clear_count += 1

    def start_calibration(self):
        self.calibration_started = True
        return {"started": True, "start_counts": 10}

    def finish_calibration(self, measured_length):
        self.calibration_started = False
        self.resolution = float(measured_length) / 100.0
        return {
            "calibrated": True,
            "measured_length": float(measured_length),
            "pulses": 100,
            "resolution": self.resolution,
        }

    def cancel_calibration(self):
        was_active = self.calibration_started
        self.calibration_started = False
        self.cancel_count += 1
        return {"cancelled": was_active, "calibration_active": False}


class MemoryStateStore:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, name, default=None):
        return self.values.get(name, default)

    def set(self, name, value):
        self.values[name] = value


def make_device(index=0, model="ace1", enabled=True, rfid_enabled=True):
    config = SimpleNamespace(
        device_id="ace%d" % index,
        model=model,
        serial="fake%d" % index,
        enabled=enabled,
        rfid_enabled=rfid_enabled,
        physical_actions_enabled=True,
        bus_id=None,
        device_uid=None,
    )
    device = AceDevice(config, FakeProtocol(), FakeTransport())
    if enabled:
        if model == "ace2":
            device.identity_verified = True
        device.open()
        device.refresh()
    return device


def make_sensor_device(sensors, index=0, *, asynchronous=True):
    config = SimpleNamespace(
        device_id="ace%d" % index,
        model="ace1",
        serial="fake%d" % index,
        enabled=True,
        rfid_enabled=True,
        physical_actions_enabled=True,
        bus_id=None,
        device_uid=None,
    )
    device = AceDevice(
        config,
        FakeProtocol(),
        SensorTransport(
            sensors,
            device_id=config.device_id,
            asynchronous=asynchronous,
        ),
    )
    device.open()
    device.refresh()
    return device


def make_immediate_sensor_devices(count):
    sensors = {"upper": False, "lower": False, "rdm": False}
    devices = [
        make_sensor_device(sensors, index, asynchronous=False)
        for index in range(count)
    ]
    return devices, sensors


def test_device_status_accepts_klipper_eventtime():
    device = make_device()
    assert device.get_status(123.5)["device_id"] == "ace0"


def test_manager_status_exposes_public_product_version():
    status = AceManager([make_device()]).get_status()

    assert __version__ == "V2.5ahpha"
    assert status["driver_version"] == __version__


@pytest.mark.parametrize("rfid_enabled", [True, False])
def test_device_status_propagates_rfid_setting(rfid_enabled):
    device = make_device(rfid_enabled=rfid_enabled)

    assert device.get_status()["rfid_enabled"] is rfid_enabled


def test_disabled_rfid_does_not_overwrite_manual_inventory():
    device = make_device(rfid_enabled=False)
    device.set_slot_inventory(
        0,
        {
            "material": "ABS",
            "color": "#00FFEE",
            "temperature": 260,
            "status": "ready",
        },
    )
    device.protocol.normalize_status = lambda _value: {
        "state": "ready",
        "slots": [
            {
                "index": 0,
                "status": "feeding",
                "material": "PLA",
                "color": "#FF0000",
                "temperature": 215,
                "rfid": 2,
                "sku": "hardware-sku",
                "spool_id": "hardware-spool",
            }
        ],
    }

    device.refresh()

    slot = device.get_status()["slots"][0]
    assert slot["status"] == "feeding"
    assert slot["material"] == "ABS"
    assert slot["color"] == "#00FFEE"
    assert slot["temperature"] == 260
    assert slot["rfid"] == 0
    assert "sku" not in slot
    assert "spool_id" not in slot


def test_failed_rfid_placeholder_does_not_replace_saved_inventory_metadata():
    device = make_device()
    device.set_slot_inventory(
        0,
        {
            "material": "ABS",
            "color": [0, 255, 238],
            "temp": 260,
            "status": "ready",
        },
    )
    device.protocol.normalize_status = lambda _value: {
        "state": "ready",
        "slots": [
            {
                "index": 0,
                "status": "ready",
                "material": "",
                "color": "#000000",
                "rfid": 1,
                "sku": "",
            }
        ],
    }

    device.refresh()

    slot = device.get_status()["slots"][0]
    assert slot["material"] == "ABS"
    assert slot["color"] == "#00FFEE"
    assert slot["temperature"] == 260
    assert slot["rfid"] == 1


def test_identified_black_rfid_filament_can_replace_saved_color():
    device = make_device()
    device.set_slot_inventory(
        0, {"material": "PLA", "color": "#FF0000", "temperature": 210}
    )
    device.protocol.normalize_status = lambda _value: {
        "state": "ready",
        "slots": [
            {
                "index": 0,
                "status": "ready",
                "material": "ABS",
                "color": "#000000",
                "rfid": 2,
            }
        ],
    }

    device.refresh()

    slot = device.get_status()["slots"][0]
    assert slot["material"] == "ABS"
    assert slot["color"] == "#000000"
    assert slot["rfid"] == 2


def test_tool_parser_and_mapping_are_stable():
    assert parse_tool("T5", 2) == 5
    assert parse_tool("TR", 2) is None
    assert tool_target(5) == (1, 1)
    with pytest.raises(ValueError):
        parse_tool("T8", 2)


def test_cross_device_change_is_serial_and_updates_after_success():
    (first, second), sensors = make_immediate_sensor_devices(2)
    manager = AceManager(
        [first, second], shared=MULTI_ACE_SHARED, sensor_state=sensors.get
    )
    assert manager.change_tool("T1", confirmed=True)["current_tool"] == "T1"
    assert manager.change_tool("T5", confirmed=True)["current_tool"] == "T5"
    assert manager.current_tool == 5
    assert [item[0] for item in first.transport.requests][-2:] == [
        "disable_feed_assist",
        "retract",
    ]
    assert [item[0] for item in second.transport.requests][-2:] == [
        "feed",
        "enable_feed_assist",
    ]


def test_ace2_physical_action_is_rejected_by_manager_and_device():
    ace2 = make_device(0, "ace2")
    manager = AceManager([ace2])
    with pytest.raises(AceSafetyError) as exc_info:
        manager.change_tool("T0", confirmed=True)
    assert exc_info.value.code == "toolchange_not_ready"
    assert exc_info.value.details["blocked_reason"] == "physical_actions_disabled"
    with pytest.raises(AceCapabilityError):
        ace2.feed(0, 10, 5)


def test_status_has_global_tools_and_single_current_tool():
    devices, sensors = make_immediate_sensor_devices(2)
    manager = AceManager(
        devices, shared=MULTI_ACE_SHARED, sensor_state=sensors.get
    )
    manager.change_tool("T4", confirmed=True)
    status = manager.get_status()
    assert status["current_tool"] == "T4"
    assert status["devices"][1]["slots"][0]["tool"] == "T4"
    assert status["devices"][1]["slots"][0]["loaded"] is True
    assert status["devices"][0]["slots"][0]["loaded"] is False


def test_manual_mode_ignores_every_tool_command_and_records_each_notice():
    devices = [make_device(index) for index in range(4)]
    hooks = []
    manager = AceManager(
        devices,
        shared=SharedConfig(),
        machine_hook=lambda name, params: hooks.append((name, dict(params))),
    )
    requests_before = [list(device.transport.requests) for device in devices]

    results = [manager.handle_tool_command("T%d" % tool) for tool in range(16)]
    results.append(manager.handle_tool_command("TR"))
    status = manager.get_status()

    assert all(result["ignored"] is True for result in results)
    assert [item["sequence"] for item in status["toolchange_notices"]] == list(
        range(1, 18)
    )
    assert [item["command"] for item in status["toolchange_notices"]] == [
        "T%d" % tool for tool in range(16)
    ] + ["TR"]
    assert status["toolchange_notice"]["command"] == "TR"
    assert status["toolchange_ready"] is False
    assert status["toolchange_blocked_reason"] == "manual_mode"
    assert manager.current_tool is None
    assert manager.path_state == "empty"
    assert manager.path_busy is False
    assert hooks == []
    assert [device.transport.requests for device in devices] == requests_before


def test_single_device_manual_mode_ignores_t15_without_range_parsing():
    device = make_device(0)
    hooks = []
    manager = AceManager(
        [device],
        shared=SharedConfig(),
        machine_hook=lambda name, params: hooks.append((name, dict(params))),
    )
    requests_before = list(device.transport.requests)

    result = manager.handle_tool_command("T15")

    assert result["ignored"] is True
    assert result["changed"] is False
    assert result["command"] == "T15"
    assert result["reason"] == "manual_mode"
    assert result["notice"]["command"] == "T15"
    assert manager.current_tool is None
    assert manager.path_state == "empty"
    assert hooks == []
    assert device.transport.requests == requests_before


def test_manual_mode_rejects_explicit_change_tool_command():
    manager = AceManager([make_device(0)], shared=SharedConfig())

    with pytest.raises(AceSafetyError, match="自动换料尚未就绪"):
        manager.change_tool("T0", confirmed=True)


def test_manual_mode_does_not_probe_unconfigured_path_sensors():
    probes = []

    def unavailable(name):
        probes.append(name)
        raise RuntimeError("sensor object is unavailable")

    manager = AceManager(
        [make_device(0)], shared=SharedConfig(), sensor_state=unavailable
    )

    assert manager.get_toolchange_readiness()["blocked_reason"] == "manual_mode"
    assert manager.handle_tool_command("T0")["ignored"] is True
    assert probes == []


def test_automatic_mode_is_not_ready_without_upper_path_sensor():
    device = make_device(0)
    manager = AceManager(
        [device],
        shared={"toolchange_mode": "automatic"},
        sensor_state=lambda _name: None,
    )
    requests_before = list(device.transport.requests)

    readiness = manager.get_toolchange_readiness()
    result = manager.handle_tool_command("T0")

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "path_sensors_incomplete"
    assert result["ignored"] is True
    assert device.transport.requests == requests_before


def test_automatic_mode_is_not_ready_without_a_sensor_state_provider():
    manager = AceManager(
        [make_device(0)],
        shared={"toolchange_mode": "automatic"},
        sensor_state=None,
    )

    readiness = manager.get_toolchange_readiness()

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "path_sensors_incomplete"
    assert "上方耗材传感器" in readiness["blocked_detail"]


def test_lower_sensor_bypass_requires_distance_but_keeps_raw_detection_status():
    sensors = {"upper": False, "lower": True, "rdm": None}
    manager = AceManager(
        [make_device(0)],
        shared={
            "toolchange_mode": "automatic",
            "toolhead_sensor_pin": "^toolboard:PA5",
            "toolhead_sensor_bypass": True,
            "toolhead_sensor_bypass_load_length": 0,
        },
        sensor_state=sensors.get,
    )

    readiness = manager.get_toolchange_readiness()
    path = manager.get_status()["path"]

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "lower_sensor_bypass_uncalibrated"
    assert path["sensors"]["lower"] is True
    assert path["sensor_policy"]["lower"] == {
        "bypassed": True,
        "control_enabled": False,
        "monitor_only": True,
        "calibrated": False,
        "configured": True,
        "bypass_load_length": 0.0,
    }
    assert path["sensor_policy"]["upper"] == {
        "control_endpoint": True,
        "feed_timeout": 30.0,
    }


def test_lower_sensor_bypass_readiness_never_probes_lower_input():
    probes = []

    def sensor_state(name):
        probes.append(name)
        if name == "lower":
            raise RuntimeError("unstable lower sensor")
        return False if name == "upper" else None

    manager = AceManager(
        [make_device(0)],
        shared={
            "toolchange_mode": "automatic",
            "toolhead_sensor_bypass": True,
            "toolhead_sensor_bypass_calibrated": True,
            "toolhead_sensor_bypass_load_length": TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX,
        },
        sensor_state=sensor_state,
    )

    assert manager.get_toolchange_readiness()["ready"] is True
    assert "lower" not in probes


def test_default_bypass_sample_distance_is_not_treated_as_calibrated():
    manager = AceManager(
        [make_device(0)],
        shared={
            "toolchange_mode": "automatic",
            "toolhead_sensor_bypass": True,
            "toolhead_sensor_bypass_load_length": 25,
            "toolhead_sensor_bypass_calibrated": False,
        },
        sensor_state=lambda name: False if name == "upper" else None,
    )

    readiness = manager.get_toolchange_readiness()

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "lower_sensor_bypass_uncalibrated"
    assert "toolhead_sensor_bypass_calibrated: True" in readiness["blocked_detail"]


@pytest.mark.parametrize(
    "length",
    [TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX + 0.001, float("inf"), float("nan")],
)
def test_lower_sensor_bypass_readiness_rejects_unsafe_length_before_sensor_probe(
    length,
):
    probes = []
    manager = AceManager(
        [make_device(0)],
        shared={
            "toolchange_mode": "automatic",
            "toolhead_sensor_bypass": True,
            "toolhead_sensor_bypass_calibrated": True,
            "toolhead_sensor_bypass_load_length": length,
        },
        sensor_state=lambda name: probes.append(name) or False,
    )

    readiness = manager.get_toolchange_readiness()

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "lower_sensor_bypass_uncalibrated"
    assert "250.0 mm" in readiness["blocked_detail"]
    assert probes == []


def test_multi_ace_automatic_mode_requires_total_hub_sensor():
    manager = AceManager(
        [make_device(0), make_device(1)],
        shared={"toolchange_mode": "automatic"},
        sensor_state=lambda name: False if name in {"upper", "lower"} else None,
    )

    readiness = manager.get_toolchange_readiness()

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "total_hub_sensor_missing"


def test_multi_ace_automatic_mode_requires_per_device_branch_calibration():
    manager = AceManager(
        [make_device(0), make_device(1)],
        shared={"toolchange_mode": "automatic"},
        sensor_state=lambda name: False if name in {"upper", "lower", "rdm"} else None,
    )

    readiness = manager.get_toolchange_readiness()

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "branch_clearance_incomplete"
    assert "ace0" in readiness["blocked_detail"]
    assert "ace1" in readiness["blocked_detail"]


def test_status_exposes_current_device_hub_and_total_hub_separately():
    sensors = {
        "upper": False,
        "lower": False,
        "rdm": False,
        "ace0_hub": False,
        "ace1_hub": True,
    }
    manager = AceManager(
        [make_device(0), make_device(1)],
        shared=MULTI_ACE_SHARED,
        sensor_state=sensors.get,
    )

    path = manager.get_status()["path"]

    assert path["sensors"] == {
        "upper": False,
        "lower": False,
        "rdm": False,
        "hubs": {"ace0": False, "ace1": True},
    }
    assert path["topology"]["mode"] == "two_stage"
    assert path["topology"]["branches"]["ace0"]["calibrated"] is True


def test_single_device_status_omits_first_stage_hub_even_for_legacy_values():
    manager = AceManager(
        [make_device(0)],
        shared={
            "ace0_hub_sensor_pin": "^PA3",
            "ace0_hub_retract_length": 35,
            "ace0_hub_clear_move_length": 5,
        },
        sensor_state=lambda name: {
            "upper": False,
            "lower": False,
            "rdm": False,
            "ace0_hub": True,
        }.get(name),
    )

    path = manager.get_status()["path"]

    assert path["sensors"]["hubs"] == {}
    assert path["topology"] == {
        "mode": "single_device",
        "current_device": None,
        "route": ["rdm", "upper", "lower"],
        "branch_clearance": {},
        "branches": {},
    }


def test_status_exposes_an_unconfigured_shared_encoder_without_blocking_startup():
    manager = AceManager([make_device(0)])

    encoder = manager.get_status()["path"]["encoders"]["shared"]

    assert encoder["configured"] is False
    assert encoder["mode"] == "off"
    assert encoder["armed"] is False
    assert encoder["fault"] is None
    assert encoder["print_monitor"] == {
        "mode": "off",
        "enabled": False,
        "active": False,
        "state": "off",
        "inactive_reason": None,
        "detection_length": 20.0,
        "extrusion_since_motion": 0.0,
        "headroom": 20.0,
        "event_sequence": 0,
        "last_event": None,
        "fault": None,
    }


def test_protect_mode_blocks_automatic_toolchange_until_encoder_is_calibrated():
    encoder = FakeEncoder(mode="protect", resolution=0)
    manager = AceManager(
        [make_device(0)],
        shared={"encoder_mode": "protect"},
        encoder=encoder,
    )

    readiness = manager.get_toolchange_readiness()

    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "encoder_not_ready"


def test_saved_encoder_resolution_is_restored_and_new_calibration_is_persisted():
    store = MemoryStateStore({"encoder_resolution": 0.55})
    encoder = FakeEncoder(resolution=0)
    manager = AceManager(
        [make_device(0)],
        encoder=encoder,
        state_store=store,
    )

    assert encoder.resolution == pytest.approx(0.55)
    assert manager.start_encoder_calibration()["started"] is True
    result = manager.finish_encoder_calibration(120)

    assert result["resolution"] == pytest.approx(1.2)
    assert store.values["encoder_resolution"] == pytest.approx(1.2)


def test_manager_rejects_invalid_encoder_calibration_lengths_before_persisting():
    for value in (0.009, 2000.01, float("nan"), float("inf"), float("-inf")):
        store = MemoryStateStore()
        encoder = FakeEncoder()
        manager = AceManager([make_device(0)], encoder=encoder, state_store=store)
        manager.start_encoder_calibration()

        with pytest.raises(AceSafetyError, match="0.01 到 2000"):
            manager.finish_encoder_calibration(value)

        assert encoder.calibration_started is True
        assert "encoder_resolution" not in store.values


def test_encoder_calibration_cancel_rejects_printing_but_allows_a_busy_idle_path():
    store = MemoryStateStore({"encoder_resolution": 0.55})
    encoder = FakeEncoder(resolution=0.55)
    encoder.calibration_started = True
    print_state = {"value": "printing"}
    manager = AceManager(
        [make_device(0)],
        encoder=encoder,
        state_store=store,
        print_state=lambda: print_state["value"],
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"
    manager.feed_assist_tool = 0

    with pytest.raises(AceSafetyError, match="打印机空闲"):
        manager.cancel_encoder_calibration()
    assert encoder.calibration_started is True
    assert encoder.cancel_count == 0

    print_state["value"] = "standby"
    manager._path_lock.acquire()
    try:
        result = manager.cancel_encoder_calibration()
    finally:
        manager._path_lock.release()

    assert result == {"cancelled": True, "calibration_active": False}
    assert encoder.cancel_count == 1
    assert encoder.resolution == pytest.approx(0.55)
    assert store.values == {"encoder_resolution": 0.55}


def test_print_monitor_tracks_net_extrusion_and_ignores_retract_recovery():
    encoder = FakeEncoder(mode="off")
    manager = AceManager(
        [make_device(0)],
        shared={
            "encoder_mode": "off",
            "encoder_print_mode": "monitor",
            "encoder_print_detection_length": 20,
        },
        encoder=encoder,
        print_state=lambda: "printing",
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"

    manager.update_encoder_print_monitor(100)
    manager.update_encoder_print_monitor(112)
    manager.update_encoder_print_monitor(107)
    recovered = manager.update_encoder_print_monitor(112)
    almost = manager.update_encoder_print_monitor(119.9)
    faulted = manager.update_encoder_print_monitor(120)

    assert recovered["extrusion_since_motion"] == pytest.approx(12)
    assert almost["extrusion_since_motion"] == pytest.approx(19.9)
    assert almost["fault"] is None
    assert faulted["event_sequence"] == 1
    assert faulted["fault"]["code"] == "encoder_print_no_motion"


def test_print_monitor_latches_once_snapshots_path_and_rearms_after_a_pulse():
    sensors = {
        "upper": True,
        "lower": True,
        "rdm": None,
        "ace0_hub": None,
    }
    hooks = []
    encoder = FakeEncoder(mode="protect")
    manager = AceManager(
        [make_device(0)],
        shared={
            "encoder_mode": "protect",
            "encoder_print_mode": "monitor",
            "encoder_print_detection_length": 20,
        },
        encoder=encoder,
        sensor_state=sensors.get,
        machine_hook=lambda name, params: hooks.append((name, params)),
        print_state=lambda: "printing",
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"

    manager.update_encoder_print_monitor(0)
    first = manager.update_encoder_print_monitor(20)
    repeated = manager.update_encoder_print_monitor(40)

    assert first["fault"]["tool"] == "T0"
    assert first["fault"]["device"] == "ace0"
    assert first["fault"]["path_state"] == "nozzle"
    assert first["fault"]["print_state"] == "printing"
    assert first["fault"]["sensors"] == {
        "upper": True,
        "lower": True,
        "rdm": None,
        "hubs": {},
    }
    assert contains_chinese(first["fault"]["message"])
    assert all(
        contains_chinese(hint) for hint in first["fault"]["possible_causes"]
    )
    assert contains_chinese(first["fault"]["probable_cause"])
    assert first["fault"]["context"] == {
        "tool": "T0",
        "device": "ace0",
        "path_state": "nozzle",
        "print_state": "printing",
        "sensors": first["fault"]["sensors"],
    }
    assert repeated["event_sequence"] == 1
    assert hooks == []
    assert manager.encoder_status()["armed"] is True

    encoder.counts += 1
    rearmed = manager.update_encoder_print_monitor(41)
    second = manager.update_encoder_print_monitor(61)

    assert rearmed["fault"] is None
    assert rearmed["extrusion_since_motion"] == pytest.approx(0)
    assert second["event_sequence"] == 2
    assert manager.encoder_status()["armed"] is True


def test_print_monitor_pause_hook_fires_once_and_paused_pulse_clears_latch():
    print_state = {"value": "printing"}
    hooks = []
    encoder = FakeEncoder(mode="off")
    manager = AceManager(
        [make_device(0)],
        shared={
            "encoder_mode": "off",
            "encoder_print_mode": "pause",
            "encoder_print_detection_length": 5,
        },
        encoder=encoder,
        machine_hook=lambda name, params: hooks.append((name, params)),
        print_state=lambda: print_state["value"],
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"

    manager.update_encoder_print_monitor(0)
    manager.update_encoder_print_monitor(5)
    manager.update_encoder_print_monitor(10)

    assert [name for name, _params in hooks] == ["pause_on_error"]
    print_state["value"] = "paused"
    paused = manager.update_encoder_print_monitor(10)
    encoder.counts += 1
    recovered = manager.update_encoder_print_monitor(10)

    assert paused["active"] is False
    assert paused["state"] == "paused"
    assert recovered["fault"] is None
    assert [name for name, _params in hooks] == ["pause_on_error"]


def test_print_monitor_resets_silently_for_transactions_and_missing_encoder():
    encoder = FakeEncoder(mode="off")
    manager = AceManager(
        [make_device(0)],
        shared={
            "encoder_print_mode": "monitor",
            "encoder_print_detection_length": 20,
        },
        encoder=encoder,
        print_state=lambda: "printing",
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"
    manager.update_encoder_print_monitor(0)
    manager.update_encoder_print_monitor(15)
    manager._transaction = {"state": "running"}

    suspended = manager.update_encoder_print_monitor(40)

    assert suspended["active"] is False
    assert suspended["state"] == "suspended"
    assert suspended["extrusion_since_motion"] == pytest.approx(0)
    assert suspended["fault"] is None

    missing = AceManager(
        [make_device(0)],
        shared={"encoder_print_mode": "monitor"},
        print_state=lambda: "printing",
    )
    missing.current_tool = 0
    missing.path_state = "nozzle"
    unavailable = missing.update_encoder_print_monitor(100)
    assert unavailable["enabled"] is True
    assert unavailable["active"] is False
    assert unavailable["state"] == "unavailable"
    assert unavailable["fault"] is None


def test_print_monitor_records_a_sensor_runout_instead_of_disarming():
    sensors = {"upper": False, "lower": True, "rdm": None, "ace0_hub": None}
    encoder = FakeEncoder(mode="off")
    manager = AceManager(
        [make_device(0)],
        shared={
            "encoder_print_mode": "monitor",
            "encoder_print_detection_length": 5,
        },
        encoder=encoder,
        sensor_state=sensors.get,
        print_state=lambda: "printing",
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"

    manager.update_encoder_print_monitor(0)
    result = manager.update_encoder_print_monitor(5)

    assert result["fault"]["code"] == "encoder_print_no_motion"
    assert "用尽" in result["fault"]["probable_cause"]
    assert "断料" in result["fault"]["probable_cause"]


def test_encoder_calibration_is_rejected_while_printing_or_with_a_loaded_tool():
    printing = AceManager(
        [make_device(0)],
        encoder=FakeEncoder(),
        print_state=lambda: "printing",
    )
    with pytest.raises(AceSafetyError, match="打印机空闲"):
        printing.start_encoder_calibration()

    loaded = AceManager([make_device(0)], encoder=FakeEncoder())
    loaded.current_tool = 0
    loaded.path_state = "nozzle"
    with pytest.raises(AceSafetyError, match="卸载当前工具通道"):
        loaded.start_encoder_calibration()

    assisted = AceManager([make_device(0)], encoder=FakeEncoder())
    assisted.feed_assist_tool = 0
    with pytest.raises(AceSafetyError, match="关闭辅助送料"):
        assisted.start_encoder_calibration()


def test_active_encoder_calibration_blocks_ace_motion_and_toolchange_readiness():
    manager = AceManager([make_device(0)], encoder=FakeEncoder())
    manager.start_encoder_calibration()

    readiness = manager.get_toolchange_readiness()
    assert readiness["ready"] is False
    assert readiness["blocked_reason"] == "encoder_calibration_active"
    with pytest.raises(AceSafetyError) as exc_info:
        manager.feed(
            {"tool": "T0", "length": 25, "speed": 10},
            confirmed=True,
            source="gcode",
        )
    assert exc_info.value.code == "encoder_calibration_active"


def test_feed_assist_is_independent_of_automatic_toolchange_and_globally_unique():
    first = make_device(0)
    second = make_device(1)
    manager = AceManager([first, second], shared=SharedConfig())

    enabled = manager.enable_feed_assist(
        {"tool": "T1"}, confirmed=True, source="gcode"
    )
    switched = manager.enable_feed_assist(
        {"device": "ace1", "slot": 2}, confirmed=True, source="gcode"
    )
    status = manager.get_status()

    assert enabled["tool"] == "T1"
    assert switched["tool"] == "T6"
    assert status["feed_assist"] == {
        "enabled": True,
        "tool": "T6",
        "device_id": "ace1",
        "slot": 2,
    }
    assert status["devices"][0]["feed_assist_slot"] is None
    assert status["devices"][1]["feed_assist_slot"] == 2
    assert [request[0] for request in first.transport.requests][-2:] == [
        "enable_feed_assist",
        "disable_feed_assist",
    ]


def test_automatic_load_stops_preexisting_feed_assist_before_new_device():
    (first, second), sensors = make_immediate_sensor_devices(2)
    manager = AceManager(
        [first, second], shared=MULTI_ACE_SHARED, sensor_state=sensors.get
    )
    manager.enable_feed_assist(
        {"tool": "T1"}, confirmed=True, source="gcode"
    )
    first_start = len(first.transport.requests)
    second_start = len(second.transport.requests)

    manager.change_tool("T5", confirmed=True)

    assert [request[0] for request in first.transport.requests[first_start:]] == [
        "disable_feed_assist"
    ]
    assert [request[0] for request in second.transport.requests[second_start:]] == [
        "feed",
        "enable_feed_assist",
    ]
    assert manager.feed_assist_tool == 5


@pytest.mark.parametrize(
    ("shared", "expected"),
    [
        (SharedConfig(material_types=("TPU", "PLA")), ["TPU", "PLA"]),
        ({"material_types": ("ASA", "ABS")}, ["ASA", "ABS"]),
        ({"material_types": ["PC", "PETG"]}, ["PC", "PETG"]),
        ({"material_types": "PVA, HIPS"}, ["PVA", "HIPS"]),
    ],
)
def test_status_exports_material_types_from_dataclass_or_mapping(shared, expected):
    status = AceManager([make_device(0)], shared=shared).get_status()

    assert status["material_types"] == expected


def test_busy_path_rejects_a_second_transaction():
    manager = AceManager(
        [make_device(0)],
        shared=CALIBRATED_BYPASS_SHARED,
        sensor_state=lambda name: False,
    )
    manager._path_lock.acquire()
    try:
        with pytest.raises(AceBusyError):
            manager.change_tool("T0", confirmed=True)
    finally:
        manager._path_lock.release()


def test_failed_target_load_does_not_preserve_unloaded_tool():
    (first, second), sensors = make_immediate_sensor_devices(2)
    manager = AceManager(
        [first, second], shared=MULTI_ACE_SHARED, sensor_state=sensors.get
    )
    manager.change_tool("T0", confirmed=True)

    def fail_request(_value):
        raise RuntimeError("target jammed")

    second.transport.request = fail_request
    with pytest.raises(Exception):
        manager.change_tool("T4", confirmed=True)
    assert manager.current_tool is None
    assert manager.get_status()["path"]["last_transaction"]["state"] == "failed"


def test_endless_spool_can_select_matching_material_across_devices():
    (first, second), sensors = make_immediate_sensor_devices(2)
    first.set_slot_inventory(0, {"material": "PLA", "color": "#22AA44", "status": "ready"})
    second.set_slot_inventory(0, {"material": "PLA", "color": "#22AA44", "status": "ready"})
    manager = AceManager(
        [first, second], shared=MULTI_ACE_SHARED, sensor_state=sensors.get
    )
    manager.change_tool("T0", confirmed=True)
    manager.set_endless_spool(True)
    result = manager.handle_runout()
    assert result["changed"] is True
    assert manager.current_tool == 4
    assert first.get_status()["slots"][0]["status"] == "empty"


def test_dryer_respects_shared_temperature_limit():
    manager = AceManager([make_device(0)], shared={"max_dryer_temperature": 55})
    with pytest.raises(AceSafetyError):
        manager.start_drying(
            {"device": "ace0", "temperature": 56, "duration": 30},
            confirmed=True,
            source="gcode",
        )


def test_machine_path_hooks_wrap_device_actions_in_order():
    (device,), sensors = make_immediate_sensor_devices(1)
    calls = []
    manager = AceManager(
        [device],
        shared=CALIBRATED_BYPASS_SHARED,
        machine_hook=lambda name, params: calls.append((name, dict(params))),
        sensor_state=sensors.get,
    )
    manager.change_tool("T0", confirmed=True)
    manager.unload(confirmed=True)
    assert [name for name, _params in calls] == [
        "pre_toolchange",
        "load_to_toolhead",
        "wipe_nozzle",
        "post_toolchange",
        "pre_toolchange",
        "cut",
        "unload_from_toolhead",
        "post_toolchange",
    ]


def test_pre_toolchange_can_heat_before_extruder_preflight():
    (device,), sensors = make_immediate_sensor_devices(1)
    hot = {"value": False}
    events = []

    def hook(name, _params):
        events.append(name)
        if name == "pre_toolchange":
            hot["value"] = True
        elif name == "load_to_toolhead":
            sensors["lower"] = True

    def preflight(distances):
        assert hot["value"] is True
        events.append(("preflight", tuple(distances)))

    manager = AceManager(
        [device],
        shared={
            "toolhead_sensor_bypass": False,
            "toolhead_sensor_max_feed_length": 12,
            "toolhead_feed_fast_length": 7,
            "toolhead_feed_fast_step": 5,
            "toolhead_feed_slow_step": 2,
            "toolhead_sensor_to_nozzle": 9,
        },
        machine_hook=hook,
        extruder_preflight=preflight,
        sensor_state=sensors.get,
    )

    manager.change_tool("T0", confirmed=True)

    assert events[:2] == [
        "pre_toolchange",
        ("preflight", (5.0, 2.0, 9.0)),
    ]


def test_switch_preflights_unload_and_load_before_any_ace_request():
    device = make_device(0)
    planned = []

    def reject_oversized_move(distances):
        values = tuple(distances)
        planned.append(values)
        if max(abs(value) for value in values) > 50:
            raise RuntimeError(
                "51.000mm exceeds max_extrude_only_distance 50.000mm"
            )

    manager = AceManager(
        [device],
        shared={
            "toolhead_sensor_bypass": False,
            "toolhead_unload_step_length": 4,
            "toolhead_sensor_max_feed_length": 12,
            "toolhead_feed_fast_length": 7,
            "toolhead_feed_fast_step": 5,
            "toolhead_feed_slow_step": 2,
            "toolhead_sensor_to_nozzle": 51,
        },
        machine_hook=lambda _name, _params: None,
        extruder_preflight=reject_oversized_move,
        sensor_state=lambda name: False if name in {"upper", "lower"} else None,
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"
    requests_before = list(device.transport.requests)

    with pytest.raises(RuntimeError, match="51.000mm exceeds"):
        manager.change_tool("T1", confirmed=True)

    assert planned == [(-4.0, 5.0, 2.0, 51.0)]
    assert device.transport.requests == requests_before


def test_cold_extruder_preflight_fails_before_any_ace_request():
    device = make_device(0)
    events = []
    manager = AceManager(
        [device],
        shared=CALIBRATED_BYPASS_SHARED,
        machine_hook=lambda name, _params: events.append(name),
        extruder_preflight=lambda _distances: (_ for _ in ()).throw(
            RuntimeError("active extruder cannot extrude")
        ),
        sensor_state=lambda name: False if name == "upper" else None,
    )
    requests_before = list(device.transport.requests)

    with pytest.raises(RuntimeError, match="active extruder cannot extrude"):
        manager.change_tool("T0", confirmed=True)

    assert device.transport.requests == requests_before
    assert events == ["pre_toolchange", "pause_on_error"]


def test_sensor_closed_loop_stops_feed_and_coordinates_toolhead_unload():
    sensors = {"upper": False, "lower": False}
    device = make_sensor_device(sensors)
    calls = []

    def hook(name, params):
        calls.append((name, dict(params)))
        if name == "load_to_toolhead":
            sensors["lower"] = True
        elif name == "unload_from_toolhead":
            sensors["lower"] = False

    manager = AceManager(
        [device],
        shared={
            "toolhead_sensor_bypass": False,
            "extruder_sensor_debounce_count": 1,
            "toolhead_sensor_debounce_count": 1,
            "toolchange_load_length": 20,
            "feed_fast_speed": 20,
            "feed_slip_compensation_length": 0,
            "toolchange_retract_length": 20,
            "retract_parking_length": 5,
            "retract_fast_speed": 20,
            "retract_parking_speed": 5,
            "ace_unload_step_length": 10,
            "toolhead_unload_max_attempts": 2,
        },
        machine_hook=hook,
        sensor_state=lambda name: sensors.get(name),
    )

    manager.change_tool("T0", confirmed=True)
    assert manager.path_state == "nozzle"
    assert "stop_feed" in [request[0] for request in device.transport.requests]

    manager.unload(confirmed=True)
    assert manager.path_state == "empty"
    assert manager.current_tool is None
    assert [name for name, _params in calls].count("cut") == 1
    assert [name for name, _params in calls].count("unload_from_toolhead") == 1


def test_lower_sensor_bypass_loads_and_unloads_when_lower_never_triggers():
    sensors = {"upper": False, "lower": False}
    device = make_sensor_device(sensors)
    calls = []

    def hook(name, params):
        calls.append((name, dict(params)))

    manager = AceManager(
        [device],
        shared={
            "toolhead_sensor_bypass": True,
            "toolhead_sensor_bypass_calibrated": True,
            "toolhead_sensor_bypass_load_length": 25,
            "extruder_sensor_debounce_count": 1,
            "toolchange_load_length": 20,
            "feed_fast_speed": 20,
            "feed_slip_compensation_length": 0,
            "toolchange_retract_length": 20,
            "retract_parking_length": 5,
            "retract_fast_speed": 20,
            "retract_parking_speed": 5,
            "ace_unload_step_length": 10,
            "toolhead_unload_max_attempts": 2,
        },
        machine_hook=hook,
        sensor_state=sensors.get,
    )

    manager.change_tool("T0", confirmed=True)

    assert manager.path_state == "nozzle"
    assert manager.current_tool == 0
    assert sensors["lower"] is False

    manager.unload(confirmed=True)

    assert manager.path_state == "empty"
    assert manager.current_tool is None
    assert [name for name, _params in calls].count("cut") == 1
    assert [name for name, _params in calls].count("unload_from_toolhead") == 1


def test_upper_sensor_feed_timeout_stops_dc_motor_and_reports_evidence():
    now = [0.0]
    sensors = {"upper": False}
    device = make_device(0)
    device.feed = lambda _slot, _length, _speed: {"accepted": True}
    encoder = FakeEncoder(mode="monitor", resolution=1.0)

    def sleep(seconds):
        now[0] += float(seconds)

    manager = AceManager(
        [device],
        shared={
            "toolchange_load_length": 100,
            "feed_fast_speed": 10,
            "feed_slip_compensation_length": 100,
            "feed_slip_compensation_speed": 10,
            "upper_sensor_feed_timeout": 1,
            "sensor_trigger_grace_time": 0,
            "encoder_mode": "monitor",
        },
        sensor_state=sensors.get,
        encoder=encoder,
        clock=lambda: now[0],
        sleep=sleep,
    )

    with pytest.raises(AceSafetyError) as exc_info:
        manager._feed_to_upper_sensor(device, 0, 0)

    assert exc_info.value.code == "upper_sensor_feed_timeout"
    assert exc_info.value.details["elapsed_seconds"] == pytest.approx(1)
    assert exc_info.value.details["timeout_seconds"] == pytest.approx(1)
    assert exc_info.value.details["attempts"] == 1
    assert exc_info.value.details["reference_feed_amount"] == pytest.approx(10)
    assert exc_info.value.details["reference_feed_limit"] == pytest.approx(200)
    assert exc_info.value.details["continuation_feed_amount"] == pytest.approx(0)
    assert exc_info.value.details["upper_sensor"] is False
    assert encoder.motions[0]["validation"] == "movement"
    assert "stop_feed" in [request[0] for request in device.transport.requests]


def test_upper_sensor_feed_continues_after_reference_lengths_until_total_timeout():
    now = [0.0]
    sensors = {"upper": False}
    device = make_device(0)
    encoder = FakeEncoder(mode="monitor", resolution=1.0)

    def sleep(seconds):
        now[0] += float(seconds)

    manager = AceManager(
        [device],
        shared={
            "toolchange_load_length": 0.1,
            "feed_fast_speed": 1,
            "feed_slip_compensation_length": 0.1,
            "feed_slip_compensation_speed": 1,
            "upper_sensor_feed_timeout": 1,
            "sensor_trigger_grace_time": 0.2,
            "extruder_sensor_debounce_count": 1,
            "encoder_mode": "monitor",
        },
        sensor_state=sensors.get,
        encoder=encoder,
        clock=lambda: now[0],
        sleep=sleep,
    )

    with pytest.raises(AceSafetyError) as exc_info:
        manager._feed_to_upper_sensor(device, 0, 0)

    details = exc_info.value.details
    assert exc_info.value.code == "upper_sensor_feed_timeout"
    assert details["elapsed_seconds"] == pytest.approx(1)
    assert details["attempts"] > 2
    assert details["reference_feed_amount"] > details["reference_feed_limit"]
    assert details["continuation_feed_amount"] > 0
    assert len(encoder.motions) == details["attempts"]


def test_upper_sensor_read_failure_after_feed_always_stops_dc_motor():
    device = make_device(0)
    device.feed = lambda _slot, _length, _speed: {"accepted": True}
    reads = [False, RuntimeError("sensor read failed")]

    def sensor_state(name):
        assert name == "upper"
        value = reads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    manager = AceManager(
        [device],
        shared={"extruder_sensor_debounce_count": 1},
        sensor_state=sensor_state,
    )

    with pytest.raises(RuntimeError, match="sensor read failed"):
        manager._feed_to_upper_sensor(device, 0, 0)

    assert "stop_feed" in [request[0] for request in device.transport.requests]


def test_completed_feed_waits_for_sensor_grace_period():
    now = [0.0]
    sensors = {"upper": False}
    device = make_device(0)
    stopped = []

    def sleep(seconds):
        now[0] += float(seconds)
        if now[0] >= 0.05:
            sensors["upper"] = True

    manager = AceManager(
        [device],
        shared={
            "sensor_trigger_grace_time": 1,
            "extruder_sensor_debounce_count": 1,
        },
        sensor_state=sensors.get,
        clock=lambda: now[0],
        sleep=sleep,
    )

    reached = manager._wait_for_sensor_motion(
        device,
        {"completed": True},
        10,
        10,
        "upper",
        True,
        lambda: stopped.append(True),
        hard_deadline=2,
    )

    assert reached is True
    assert now[0] == pytest.approx(0.05)
    assert stopped == []


def test_sensor_trigger_at_hard_deadline_is_not_accepted_as_success():
    now = [0.0]
    sensors = {"upper": False}
    device = make_device(0)
    stopped = []

    def sleep(seconds):
        now[0] += float(seconds)
        if now[0] >= 0.1:
            sensors["upper"] = True

    manager = AceManager(
        [device],
        shared={
            "sensor_trigger_grace_time": 1,
            "extruder_sensor_debounce_count": 1,
        },
        sensor_state=sensors.get,
        clock=lambda: now[0],
        sleep=sleep,
    )

    reached = manager._wait_for_sensor_motion(
        device,
        {"accepted": True},
        10,
        10,
        "upper",
        True,
        lambda: stopped.append(True),
        hard_deadline=0.1,
    )

    assert reached is False
    assert stopped == [True]


def test_path_cannot_be_declared_empty_without_an_explicit_clear_upper_sensor():
    manager = AceManager(
        [make_device(0)],
        shared={"toolhead_sensor_bypass": True},
    )

    assert manager._all_path_sensors_clear(
        {"upper": None, "lower": None, "rdm": None}
    ) is False
    assert manager._all_path_sensors_clear(
        {"upper": False, "lower": None, "rdm": None}
    ) is True


def test_configured_optional_sensor_must_report_clear_before_path_is_empty():
    manager = AceManager(
        [make_device(0)],
        shared={
            "toolhead_sensor_bypass": True,
            "rdm_sensor_pin": "^PA2",
        },
    )

    assert manager._all_path_sensors_clear(
        {"upper": False, "lower": None, "rdm": None}
    ) is False
    assert manager._all_path_sensors_clear(
        {"upper": False, "lower": None, "rdm": False}
    ) is True


def test_five_sensor_topology_clears_total_hub_then_device_hub_then_parks():
    sensors = {
        "upper": False,
        "lower": False,
        "rdm": True,
        "ace0_hub": True,
        "ace1_hub": False,
    }
    first = make_device(0)
    calls = []

    def retract(slot, length, speed):
        calls.append((slot, length, speed))
        if len(calls) == 1:
            sensors["rdm"] = False
        elif len(calls) == 2:
            sensors["ace0_hub"] = False
        return {"completed": True}

    first.retract = retract
    manager = AceManager(
        [first, make_device(1)],
        shared={
            "toolchange_retract_length": 10,
            "retract_parking_length": 10,
            "retract_parking_speed": 5,
            "ace0_hub_retract_length": 20,
            "ace0_hub_clear_move_length": 5,
            "ace1_hub_retract_length": 20,
        },
        sensor_state=sensors.get,
    )

    manager._retract_to_parking_position(first, 0)

    assert [length for _slot, length, _speed in calls] == [10, 20, 5]
    assert sensors["rdm"] is False
    assert sensors["ace0_hub"] is False


def test_total_hub_only_uses_device_specific_blind_branch_distance():
    sensors = {"rdm": True}
    second = make_device(1)
    calls = []

    def retract(slot, length, speed):
        calls.append((slot, length, speed))
        if len(calls) == 1:
            sensors["rdm"] = False
        return {"completed": True}

    second.retract = retract
    manager = AceManager(
        [make_device(0), second],
        shared={
            "toolchange_retract_length": 10,
            "retract_parking_length": 10,
            "retract_parking_speed": 5,
            "ace0_hub_retract_length": 20,
            "ace1_hub_retract_length": 35,
            "ace1_hub_clear_move_length": 7,
        },
        sensor_state=sensors.get,
    )

    manager._retract_to_parking_position(second, 0)

    assert [length for _slot, length, _speed in calls] == [10, 35, 7]


def test_shared_encoder_stops_monitoring_after_total_hub_clears():
    sensors = {"rdm": True, "ace0_hub": True}
    device = make_device(0)
    encoder = FakeEncoder(mode="protect", resolution=1.0)
    calls = []

    def retract(slot, length, speed):
        calls.append((slot, length, speed))
        if len(calls) == 1:
            sensors["rdm"] = False
        elif len(calls) == 2:
            sensors["ace0_hub"] = False
        return {"completed": True}

    device.retract = retract
    manager = AceManager(
        [device, make_device(1)],
        shared={
            "encoder_mode": "protect",
            "toolchange_retract_length": 10,
            "retract_parking_length": 10,
            "retract_parking_speed": 5,
            "ace0_hub_retract_length": 20,
            "ace0_hub_clear_move_length": 5,
            "ace1_hub_retract_length": 20,
        },
        sensor_state=sensors.get,
        encoder=encoder,
    )

    manager._retract_to_parking_position(device, 0)

    assert [motion["commanded_length"] for motion in encoder.motions] == [10]
    assert [length for _slot, length, _speed in calls] == [10, 20, 5]


def test_monitor_mode_records_encoder_fault_without_interrupting_motion():
    encoder = FakeEncoder(
        mode="monitor",
        fault={"code": "encoder_no_motion", "message": "no pulses"},
    )
    manager = AceManager(
        [make_device(0)], shared={"encoder_mode": "monitor"}, encoder=encoder
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"

    manager.feed(
        {"tool": "T0", "length": 25, "speed": 10},
        confirmed=True,
        source="gcode",
    )

    assert manager.path_state == "nozzle"
    fault = manager.encoder_status()["fault"]
    assert fault["code"] == "encoder_no_motion"
    assert contains_chinese(fault["message"])
    assert "no pulses" not in fault["message"]


@pytest.mark.parametrize("sensor_state", [None, lambda _name: None])
def test_monitor_encoder_fault_does_not_drive_path_recovery(sensor_state):
    encoder = FakeEncoder(
        mode="monitor",
        fault={"code": "encoder_no_motion", "message": "no pulses"},
    )
    manager = AceManager(
        [make_device(0)],
        shared={"encoder_mode": "monitor"},
        encoder=encoder,
        sensor_state=sensor_state,
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"
    manager._encoder_runtime_fault = {
        "code": "encoder_no_motion",
        "message": "no pulses",
        "mode": "monitor",
    }
    encoder.status_fault = encoder.finish_fault

    result = manager.reconnect("ace0")

    assert manager.current_tool == 0
    assert manager.path_state == "nozzle"
    assert result["current_tool"] == "T0"
    assert result["path"]["encoders"]["shared"]["fault"] is None
    assert encoder.clear_count == 1


def test_protect_mode_encoder_fault_stops_ace_and_marks_path_unknown():
    encoder = FakeEncoder(
        mode="protect",
        fault={"code": "encoder_no_motion", "message": "no pulses"},
    )
    device = make_device(0)
    manager = AceManager(
        [device], shared={"encoder_mode": "protect"}, encoder=encoder
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"

    with pytest.raises(AceSafetyError) as exc_info:
        manager.retract(
            {"tool": "T0", "length": 25, "speed": 10},
            confirmed=True,
            source="gcode",
        )

    assert exc_info.value.code == "encoder_motion_fault"
    assert contains_chinese(str(exc_info.value))
    assert manager.path_state == "unknown"
    assert "stop_retract" in [request[0] for request in device.transport.requests]


def test_empty_target_is_rejected_before_old_tool_is_cut_or_retracted():
    (first, second), sensors = make_immediate_sensor_devices(2)
    manager = AceManager(
        [first, second], shared=MULTI_ACE_SHARED, sensor_state=sensors.get
    )
    manager.change_tool("T0", confirmed=True)
    second.set_slot_inventory(0, {"status": "empty"})
    first_requests = list(first.transport.requests)

    with pytest.raises(AceSafetyError, match="Target slot is not ready"):
        manager.change_tool("T4", confirmed=True)

    assert first.transport.requests == first_requests
    assert manager.current_tool == 0


def test_unload_sensor_conflict_fails_before_cutting_and_invokes_error_hook():
    sensors = {"upper": False, "lower": False}
    device = make_sensor_device(sensors)
    calls = []

    def hook(name, _params):
        calls.append(name)
        if name == "load_to_toolhead":
            sensors["lower"] = True

    manager = AceManager(
        [device],
        shared={
            "toolhead_sensor_bypass": False,
            "extruder_sensor_debounce_count": 1,
            "toolhead_sensor_debounce_count": 1,
            "toolchange_load_length": 20,
            "feed_fast_speed": 20,
            "feed_slip_compensation_length": 0,
        },
        machine_hook=hook,
        sensor_state=lambda name: sensors.get(name),
    )
    manager.change_tool("T0", confirmed=True)
    sensors.update(upper=False, lower=True)

    with pytest.raises(AceSafetyError, match="upper sensor is clear"):
        manager.unload(confirmed=True)

    assert "cut" not in calls
    assert calls[-1] == "pause_on_error"


def test_required_hook_preflight_happens_before_any_physical_request():
    device = make_device(0)
    requests_before = list(device.transport.requests)
    manager = AceManager(
        [device],
        machine_hook_validator=lambda _names: (_ for _ in ()).throw(
            RuntimeError("缺少路径宏")
        ),
    )
    with pytest.raises(AceSafetyError) as exc_info:
        manager.change_tool("T0", confirmed=True)
    assert exc_info.value.code == "toolchange_not_ready"
    assert exc_info.value.details["blocked_reason"] == "machine_hooks_incomplete"
    assert "缺少路径宏" in exc_info.value.details["blocked_detail"]
    assert device.transport.requests == requests_before


def test_motion_ack_waits_for_expected_duration_and_ready_status():
    device = make_device(0)
    sleeps = []
    original_request = device.transport.request

    def accepted_without_completion(value):
        result = original_request(value)
        if value[0] != "get_status":
            result["result"].pop("completed", None)
        return result

    device.transport.request = accepted_without_completion
    manager = AceManager([device], sleep=sleeps.append)
    manager.feed(
        {"tool": "T0", "length": 20, "speed": 10},
        confirmed=True,
        source="gcode",
    )
    assert sleeps == [2.1]


def test_uncertain_physical_request_blocks_actions_until_recovery():
    device = make_device(0)

    def fail_request(_value):
        raise TimeoutError("response lost")

    device.transport.request = fail_request
    with pytest.raises(Exception, match="response lost"):
        device.feed(0, 10, 5)
    status = device.get_status()
    assert status["physical_state_unknown"] is True
    assert status["error"]["code"] == "physical_state_unknown"
    with pytest.raises(AceSafetyError, match="unresolved physical action"):
        device.feed(0, 10, 5)


def test_device_boundary_defaults_physical_actions_to_disabled():
    config = SimpleNamespace(
        device_id="ace0",
        model="ace1",
        serial="fake0",
        enabled=True,
        rfid_enabled=True,
        bus_id=None,
        device_uid=None,
    )
    device = AceDevice(config, FakeProtocol(), FakeTransport())
    assert device.physical_actions_enabled is False


def test_manual_feed_rejects_a_tool_that_does_not_own_loaded_path():
    manager = AceManager([make_device(0), make_device(1)])
    manager.current_tool = 0
    manager.path_state = "nozzle"

    with pytest.raises(AceSafetyError, match="owns the shared filament path"):
        manager.feed(
            {"tool": "T4", "length": 20, "speed": 10},
            confirmed=True,
            source="gcode",
        )


def test_manual_retract_of_loaded_tool_never_leaves_stale_current_tool():
    manager = AceManager([make_device(0)])
    manager.current_tool = 0
    manager.path_state = "nozzle"

    manager.retract(
        {"tool": "T0", "length": 20, "speed": 10},
        confirmed=True,
        source="gcode",
    )

    assert manager.current_tool is None
    assert manager.path_state == "unknown"


def test_reconnect_cannot_clear_uncertain_motion_without_path_sensors():
    device = make_device(0)
    original_request = device.transport.request
    device.transport.request = lambda _value: (_ for _ in ()).throw(
        TimeoutError("response lost")
    )
    with pytest.raises(Exception, match="response lost"):
        device.feed(0, 10, 5)
    device.transport.request = original_request
    manager = AceManager([device])

    with pytest.raises(AceSafetyError, match="requires configured path sensors"):
        manager.reconnect("ace0")

    assert device.get_status()["physical_state_unknown"] is True


def test_reconnect_clears_uncertain_motion_only_after_ready_and_sensor_reconcile():
    sensors = {"upper": False, "lower": False, "rdm": False}
    device = make_sensor_device(sensors)
    original_request = device.transport.request
    device.transport.request = lambda _value: (_ for _ in ()).throw(
        TimeoutError("response lost")
    )
    with pytest.raises(Exception, match="response lost"):
        device.feed(0, 10, 5)
    device.transport.request = original_request
    manager = AceManager([device], sensor_state=sensors.get)

    manager.reconnect("ace0")

    assert device.get_status()["physical_state_unknown"] is False
    assert manager.path_state == "empty"


def test_endless_spool_does_not_hide_pause_failure_when_no_candidate_exists():
    device = make_device(0)
    for slot in range(4):
        device.set_slot_inventory(slot, {"status": "empty"})
    device.set_slot_inventory(0, {"material": "PLA", "status": "ready"})
    manager = AceManager(
        [device],
        shared=CALIBRATED_BYPASS_SHARED,
        machine_hook=lambda _name, _params: None,
        print_state=lambda: "printing",
        sensor_state=lambda name: True if name == "upper" else False,
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"
    manager.set_endless_spool(True)

    with pytest.raises(AceSafetyError, match="did not pause"):
        manager.handle_runout()


def test_endless_spool_reports_no_candidate_after_pause_is_confirmed():
    device = make_device(0)
    for slot in range(4):
        device.set_slot_inventory(slot, {"status": "empty"})
    device.set_slot_inventory(0, {"material": "PLA", "status": "ready"})
    print_state = {"value": "printing"}

    def pause(name, _params):
        if name == "pause_on_error":
            print_state["value"] = "paused"

    manager = AceManager(
        [device],
        shared=CALIBRATED_BYPASS_SHARED,
        machine_hook=pause,
        print_state=lambda: print_state["value"],
        sensor_state=lambda name: True if name == "upper" else False,
    )
    manager.current_tool = 0
    manager.path_state = "nozzle"
    manager.set_endless_spool(True)

    result = manager.handle_runout()

    assert result["changed"] is False
    assert print_state["value"] == "paused"
