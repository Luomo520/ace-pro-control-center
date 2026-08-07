import json

import pytest

from ace_driver.config import (
    DEFAULT_MATERIAL_TYPES,
    TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX,
    UPPER_SENSOR_FEED_TIMEOUT_MAX,
    ConfigError,
    DeviceConfig,
    DriverConfig,
    parse_config,
)


FIXED_SENSOR_NAMES = {
    "extruder_sensor_name": "extruder_sensor",
    "toolhead_sensor_name": "toolhead_sensor",
    "rdm_sensor_name": "rdm_sensor",
    "ace0_hub_sensor_name": "ace0_hub_sensor",
    "ace1_hub_sensor_name": "ace1_hub_sensor",
    "ace2_hub_sensor_name": "ace2_hub_sensor",
    "ace3_hub_sensor_name": "ace3_hub_sensor",
    "encoder_sensor_name": "shared_encoder",
}


def device(model="ace1", serial="/dev/serial/by-id/ace0", **overrides):
    values = {
        "model": model,
        "transport": "serial",
        "serial": serial,
        "enabled": True,
        "physical_actions_enabled": model == "ace1",
    }
    if model == "ace2":
        values.update({"bus_id": "bus0", "device_uid": "uid-default"})
    values.update(overrides)
    return values


def config_for(devices):
    result = {
        "ace": {"driver_version": 3},
        "ace_hardware": {
            "driver_version": 3,
            "device_count": len(devices),
            "topology_mode": "configured",
        },
        "ace_machine": {},
    }
    for index, values in enumerate(devices):
        result["ace_device ace%d" % index] = values
    return result


@pytest.mark.parametrize(
    "models",
    [
        ["ace1"],
        ["ace1", "ace1"],
        ["ace1", "ace2"],
        ["ace2", "ace2"],
        ["ace1", "ace1", "ace1", "ace1"],
    ],
)
def test_supported_counts_and_model_combinations(models):
    sections = []
    for index, model in enumerate(models):
        values = device(model, "/dev/serial/by-id/ace%d" % index)
        if model == "ace2":
            values["bus_id"] = "bus%d" % index
            values["device_uid"] = "uid%d" % index
        sections.append(values)

    parsed = parse_config(config_for(sections))

    assert isinstance(parsed, DriverConfig)
    assert all(isinstance(item, DeviceConfig) for item in parsed.devices)
    assert [item.device_id for item in parsed.devices] == [
        "ace%d" % index for index in range(len(models))
    ]
    assert [item.model for item in parsed.devices] == models
    assert parsed.tool_map.tool_count == len(models) * 4


def test_shared_and_machine_values_are_parsed():
    raw = config_for([device()])
    raw["ace"].update(
        {
            "feed_speed": "72.5",
            "endless_spool": "true",
            "rdm_sensor_name": "return_sensor",
            "ace0_hub_sensor_name": "ace0_branch_sensor",
            "ace0_hub_sensor_pin": "^PC1",
            "ace0_hub_retract_length": "275",
            "ace0_hub_clear_move_length": "35",
            "extruder_sensor_pin": "^TGL36:PA2",
            "toolhead_sensor_pin": "^TGL36:PA5",
            "toolhead_sensor_bypass": "true",
            "toolhead_sensor_bypass_calibrated": "true",
            "toolhead_sensor_bypass_load_length": "87.5",
            "feed_slip_compensation_length": "350",
            "toolhead_unload_max_attempts": "8",
            "toolchange_mode": "automatic",
            "encoder_sensor_name": "shared_motion",
            "encoder_sensor_pin": "^PC3",
            "encoder_resolution": "0.47",
            "encoder_detection_length": "25",
            "encoder_min_tracking_ratio": "0.72",
            "encoder_mode": "protect",
            "encoder_print_mode": "pause",
            "encoder_print_detection_length": "32",
            "upper_sensor_feed_timeout": "45",
        }
    )
    raw["ace_machine"] = {
        "cut_macro": "_ace_cut_filament",
        "wipe_nozzle_macro": "_ace_wipe_nozzle",
    }

    parsed = parse_config(raw)

    assert parsed.shared.feed_speed == 72.5
    assert parsed.shared.endless_spool is True
    assert parsed.shared.rdm_sensor_name == "return_sensor"
    assert parsed.shared.ace0_hub_sensor_name == "ace0_branch_sensor"
    assert parsed.shared.ace0_hub_sensor_pin == "^PC1"
    assert parsed.shared.ace0_hub_retract_length == 275
    assert parsed.shared.ace0_hub_clear_move_length == 35
    assert parsed.shared.extruder_sensor_pin == "^TGL36:PA2"
    assert parsed.shared.toolhead_sensor_pin == "^TGL36:PA5"
    assert parsed.shared.toolhead_sensor_bypass is True
    assert parsed.shared.toolhead_sensor_bypass_calibrated is True
    assert parsed.shared.toolhead_sensor_bypass_load_length == pytest.approx(87.5)
    assert parsed.shared.feed_slip_compensation_length == 350
    assert parsed.shared.toolhead_unload_max_attempts == 8
    assert parsed.shared.toolchange_mode == "automatic"
    assert parsed.shared.encoder_sensor_name == "shared_motion"
    assert parsed.shared.encoder_sensor_pin == "^PC3"
    assert parsed.shared.encoder_resolution == pytest.approx(0.47)
    assert parsed.shared.encoder_detection_length == pytest.approx(25)
    assert parsed.shared.encoder_min_tracking_ratio == pytest.approx(0.72)
    assert parsed.shared.encoder_mode == "protect"
    assert parsed.shared.encoder_print_mode == "pause"
    assert parsed.shared.encoder_print_detection_length == pytest.approx(32)
    assert parsed.shared.upper_sensor_feed_timeout == pytest.approx(45)
    assert parsed.machine.cut_macro == "_ace_cut_filament"
    assert parsed.machine.wipe_nozzle_macro == "_ace_wipe_nozzle"


def test_pin_only_sensor_configuration_uses_fixed_internal_names():
    raw = config_for([device()])
    pin_values = {
        "extruder_sensor_pin": "^PA0",
        "toolhead_sensor_pin": "^PA1",
        "rdm_sensor_pin": "^PA2",
        "ace0_hub_sensor_pin": "^PA3",
        "ace1_hub_sensor_pin": "^PA4",
        "ace2_hub_sensor_pin": "^PA5",
        "ace3_hub_sensor_pin": "^PA6",
        "encoder_sensor_pin": "^PA7",
    }
    raw["ace"].update(pin_values)

    shared = parse_config(raw).shared

    for key, expected in FIXED_SENSOR_NAMES.items():
        assert getattr(shared, key) == expected
    for key, expected in pin_values.items():
        assert getattr(shared, key) == expected


def test_empty_sensor_pins_are_silently_disabled():
    shared = parse_config(config_for([device()])).shared

    for key in FIXED_SENSOR_NAMES:
        assert getattr(shared, key) is None
    assert shared.extruder_sensor_pin is None
    assert shared.toolhead_sensor_pin is None
    assert shared.rdm_sensor_pin is None
    assert shared.encoder_sensor_pin is None
    for index in range(4):
        assert getattr(shared, "ace%d_hub_sensor_pin" % index) is None


def test_lower_sensor_defaults_to_monitor_only_and_exports_policy():
    shared = parse_config(config_for([device()])).shared

    assert shared.toolhead_sensor_bypass is True
    assert shared.toolhead_sensor_bypass_calibrated is False
    assert shared.toolhead_sensor_bypass_load_length == pytest.approx(25)
    assert shared.to_dict()["toolhead_sensor_bypass"] is True
    assert shared.to_dict()["toolhead_sensor_bypass_calibrated"] is False
    assert shared.to_dict()["toolhead_sensor_bypass_load_length"] == pytest.approx(25)


def test_upper_feed_timeout_and_encoder_tracking_ratio_defaults_are_exported():
    shared = parse_config(config_for([device()])).shared

    assert shared.upper_sensor_feed_timeout == pytest.approx(30)
    assert shared.encoder_min_tracking_ratio == pytest.approx(0.6)
    assert shared.to_dict()["upper_sensor_feed_timeout"] == pytest.approx(30)
    assert shared.to_dict()["encoder_min_tracking_ratio"] == pytest.approx(0.6)


@pytest.mark.parametrize("value", ["0.99", str(UPPER_SENSOR_FEED_TIMEOUT_MAX + 0.01)])
def test_upper_feed_timeout_rejects_values_outside_hard_limits(value):
    raw = config_for([device()])
    raw["ace"]["upper_sensor_feed_timeout"] = value

    with pytest.raises(ConfigError, match="upper_sensor_feed_timeout"):
        parse_config(raw)


@pytest.mark.parametrize("value", ["0", "1.001"])
def test_encoder_tracking_ratio_rejects_values_outside_fraction(value):
    raw = config_for([device()])
    raw["ace"]["encoder_min_tracking_ratio"] = value

    with pytest.raises(ConfigError, match="encoder_min_tracking_ratio"):
        parse_config(raw)


def test_lower_sensor_bypass_length_must_be_non_negative():
    raw = config_for([device()])
    raw["ace"]["toolhead_sensor_bypass_load_length"] = "-0.1"

    with pytest.raises(ConfigError, match="toolhead_sensor_bypass_load_length"):
        parse_config(raw)


def test_lower_sensor_bypass_length_accepts_physical_safety_limit():
    raw = config_for([device()])
    raw["ace"]["toolhead_sensor_bypass_load_length"] = str(
        TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX
    )

    assert (
        parse_config(raw).shared.toolhead_sensor_bypass_load_length
        == pytest.approx(TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX)
    )


@pytest.mark.parametrize(
    "value",
    [str(TOOLHEAD_SENSOR_BYPASS_LOAD_LENGTH_MAX + 0.001), "1e100"],
)
def test_lower_sensor_bypass_length_rejects_values_above_physical_safety_limit(
    value,
):
    raw = config_for([device()])
    raw["ace"]["toolhead_sensor_bypass_load_length"] = value

    with pytest.raises(ConfigError, match="toolhead_sensor_bypass_load_length"):
        parse_config(raw)


def test_legacy_explicit_sensor_names_remain_supported():
    raw = config_for([device()])
    legacy_names = {
        "extruder_sensor_name": "legacy_upper",
        "toolhead_sensor_name": "legacy_lower",
        "rdm_sensor_name": "legacy_total_hub",
        "ace0_hub_sensor_name": "legacy_branch",
        "encoder_sensor_name": "legacy_encoder",
    }
    raw["ace"].update(legacy_names)

    shared = parse_config(raw).shared

    for key, expected in legacy_names.items():
        assert getattr(shared, key) == expected


def test_toolchange_mode_defaults_to_manual_and_is_exported():
    parsed = parse_config(config_for([device()]))

    assert parsed.shared.toolchange_mode == "manual"
    assert parsed.shared.to_dict()["toolchange_mode"] == "manual"


def test_invalid_toolchange_mode_is_rejected():
    raw = config_for([device()])
    raw["ace"]["toolchange_mode"] = "guess"

    with pytest.raises(ConfigError, match="manual or automatic"):
        parse_config(raw)


def test_material_types_default_is_an_immutable_tuple_and_exports_as_list():
    parsed = parse_config(config_for([device()]))

    assert parsed.shared.material_types == DEFAULT_MATERIAL_TYPES
    assert isinstance(parsed.shared.material_types, tuple)
    assert parsed.shared.to_dict()["material_types"] == list(DEFAULT_MATERIAL_TYPES)
    json.dumps(parsed.shared.to_dict())


def test_material_types_preserve_configured_order_and_trim_whitespace():
    raw = config_for([device()])
    raw["ace"]["material_types"] = " TPU, PLA+, Custom-CF "

    parsed = parse_config(raw)

    assert parsed.shared.material_types == ("TPU", "PLA+", "Custom-CF")
    assert parsed.to_dict()["shared"]["material_types"] == [
        "TPU",
        "PLA+",
        "Custom-CF",
    ]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "at least 1 item"),
        ("PLA,,PETG", "item 2 must not be empty"),
        ("PLA, pla", "duplicate item 'pla'"),
        ("X" * 33, "at most 32 characters"),
        ("PLA,\tPETG", "contains control characters"),
        (",".join("M%d" % index for index in range(33)), "at most 32 items"),
        (["PLA", "PETG"], "comma-separated string"),
    ],
)
def test_invalid_material_types_are_rejected(value, message):
    raw = config_for([device()])
    raw["ace"]["material_types"] = value

    with pytest.raises(ConfigError, match=message):
        parse_config(raw)


def test_material_types_accept_exactly_32_unique_items():
    expected = tuple("M%d" % index for index in range(32))
    raw = config_for([device()])
    raw["ace"]["material_types"] = ",".join(expected)

    assert parse_config(raw).shared.material_types == expected


def test_rfid_is_enabled_by_default_and_exported():
    parsed = parse_config(config_for([device()]))

    assert parsed.devices[0].rfid_enabled is True
    assert parsed.devices[0].to_dict()["rfid_enabled"] is True


def test_rfid_can_be_explicitly_disabled():
    parsed = parse_config(config_for([device(rfid_enabled="False")]))

    assert parsed.devices[0].rfid_enabled is False
    assert parsed.to_dict()["devices"][0]["rfid_enabled"] is False


def test_rfid_setting_is_independent_for_each_device():
    parsed = parse_config(
        config_for(
            [
                device(serial="/dev/serial/by-id/ace0", rfid_enabled=True),
                device(serial="/dev/serial/by-id/ace1", rfid_enabled=False),
            ]
        )
    )

    assert [item.rfid_enabled for item in parsed.devices] == [True, False]


@pytest.mark.parametrize(
    "updates",
    [
        {
            "extruder_sensor_name": "shared_sensor",
            "toolhead_sensor_name": "shared_sensor",
        },
        {
            "extruder_sensor_name": "shared_sensor",
            "rdm_sensor_name": "SHARED_SENSOR",
        },
        {
            "extruder_sensor_name": "shared_sensor",
            "ace0_hub_sensor_name": "SHARED_SENSOR",
        },
        {
            "ace0_hub_sensor_name": "branch_sensor",
            "ace1_hub_sensor_name": " BRANCH_SENSOR ",
        },
        {
            "toolhead_sensor_name": "toolhead_sensor",
            "rdm_sensor_name": " toolhead_sensor ",
        },
    ],
)
def test_path_sensor_names_must_be_unique(updates):
    raw = config_for([device()])
    raw["ace"].update(updates)

    with pytest.raises(ConfigError, match="sensor names must be unique"):
        parse_config(raw)


@pytest.mark.parametrize(
    ("pin_key", "name_key", "fixed_name"),
    [
        ("rdm_sensor_pin", "rdm_sensor_name", "rdm_sensor"),
        ("ace0_hub_sensor_pin", "ace0_hub_sensor_name", "ace0_hub_sensor"),
        ("encoder_sensor_pin", "encoder_sensor_name", "shared_encoder"),
    ],
)
def test_pin_only_optional_sensor_gets_fixed_name(pin_key, name_key, fixed_name):
    raw = config_for([device()])
    raw["ace"].update({pin_key: "^PC1", name_key: ""})

    assert getattr(parse_config(raw).shared, name_key) == fixed_name


@pytest.mark.parametrize("mode", ["off", "monitor", "protect"])
def test_encoder_modes_are_accepted(mode):
    raw = config_for([device()])
    raw["ace"]["encoder_mode"] = mode

    assert parse_config(raw).shared.encoder_mode == mode


@pytest.mark.parametrize("mode", ["off", "monitor", "pause"])
def test_encoder_print_modes_are_accepted_and_independent(mode):
    raw = config_for([device()])
    raw["ace"].update(
        {
            "encoder_mode": "off",
            "encoder_print_mode": mode,
            "encoder_print_detection_length": "27.5",
        }
    )

    shared = parse_config(raw).shared

    assert shared.encoder_mode == "off"
    assert shared.encoder_print_mode == mode
    assert shared.encoder_print_detection_length == pytest.approx(27.5)


def test_encoder_print_monitor_defaults_are_exported():
    shared = parse_config(config_for([device()])).shared

    assert shared.encoder_print_mode == "off"
    assert shared.encoder_print_detection_length == pytest.approx(20)
    assert shared.to_dict()["encoder_print_mode"] == "off"
    assert shared.to_dict()["encoder_print_detection_length"] == pytest.approx(20)


def test_invalid_encoder_mode_and_measurements_are_rejected():
    raw = config_for([device()])
    raw["ace"]["encoder_mode"] = "automatic"
    with pytest.raises(ConfigError, match="off, monitor, or protect"):
        parse_config(raw)

    raw = config_for([device()])
    raw["ace"]["encoder_resolution"] = "-0.1"
    with pytest.raises(ConfigError, match="encoder_resolution"):
        parse_config(raw)

    raw = config_for([device()])
    raw["ace"]["encoder_detection_length"] = "0"
    with pytest.raises(ConfigError, match="encoder_detection_length"):
        parse_config(raw)

    raw = config_for([device()])
    raw["ace"]["encoder_print_mode"] = "protect"
    with pytest.raises(ConfigError, match="encoder_print_mode"):
        parse_config(raw)

    raw = config_for([device()])
    raw["ace"]["encoder_print_detection_length"] = "0"
    with pytest.raises(ConfigError, match="encoder_print_detection_length"):
        parse_config(raw)


def test_non_finite_encoder_measurements_are_rejected():
    for value in ("nan", "inf", "-inf"):
        raw = config_for([device()])
        raw["ace"]["encoder_print_detection_length"] = value
        with pytest.raises(ConfigError, match="finite number"):
            parse_config(raw)


def test_ace2_shared_bus_and_serial_are_allowed_with_distinct_uids():
    first = device(
        "ace2",
        "/dev/serial/by-id/ace2-bus",
        bus_id="shared",
        device_uid="uid-a",
    )
    second = device(
        "ace2",
        "/dev/serial/by-id/ace2-bus",
        bus_id="shared",
        device_uid="uid-b",
    )
    parsed = parse_config(config_for([first, second]))
    assert parsed.device_count == 2


def test_duplicate_ace1_serial_is_rejected():
    raw = config_for([device(), device(serial="/dev/serial/by-id/ace0")])
    with pytest.raises(ConfigError, match="cannot be shared"):
        parse_config(raw)


def test_duplicate_ace2_uid_is_rejected():
    first = device("ace2", "/dev/ace2", bus_id="bus0", device_uid="same")
    second = device("ace2", "/dev/ace2", bus_id="bus0", device_uid="same")
    with pytest.raises(ConfigError, match="duplicated"):
        parse_config(config_for([first, second]))


def test_ace2_physical_actions_are_rejected_at_config_boundary():
    raw = config_for([device("ace2", physical_actions_enabled=True)])
    with pytest.raises(ConfigError, match="read-only"):
        parse_config(raw)


def test_ace2_auto_uid_is_rejected_until_persistent_discovery_exists():
    raw = config_for([device("ace2", device_uid="auto")])
    with pytest.raises(ConfigError, match="persistent discovery"):
        parse_config(raw)


def test_noncontinuous_or_extra_device_sections_are_rejected():
    raw = config_for([device()])
    raw["ace_device ace1"] = raw.pop("ace_device ace0")
    with pytest.raises(ConfigError, match="expected"):
        parse_config(raw)

    raw = config_for([device()])
    raw["ace_device ace1"] = device(serial="/dev/ace1")
    with pytest.raises(ConfigError, match="active ace_device"):
        parse_config(raw)


class FakeSection:
    def __init__(self, name, values, sections=None):
        self._name = name
        self._values = values
        self._sections = sections or {}

    def get_name(self):
        return self._name

    def get(self, key, default=None):
        return self._values.get(key, default)

    def getsection(self, name):
        if name not in self._sections:
            raise KeyError(name)
        return self._sections[name]

    def get_prefix_sections(self, prefix):
        return [
            section
            for name, section in self._sections.items()
            if name.startswith(prefix)
        ]


def test_klipper_config_wrapper_entry_point():
    hardware = FakeSection(
        "ace_hardware",
        {"driver_version": "3", "device_count": "1"},
    )
    ace0 = FakeSection("ace_device ace0", device())
    machine = FakeSection("ace_machine", {"pause_on_error_macro": "PAUSE"})
    root = FakeSection(
        "ace",
        {"driver_version": "3", "feed_speed": "81"},
        {
            "ace_hardware": hardware,
            "ace_device ace0": ace0,
            "ace_machine": machine,
        },
    )

    parsed = parse_config(root)

    assert parsed.shared.feed_speed == 81
    assert parsed.devices[0].device_id == "ace0"
    assert parsed.machine.pause_on_error_macro == "PAUSE"
