import json

import pytest

from ace_driver.models import (
    CapabilitySet,
    ConnectionState,
    DeviceModel,
    DeviceStatus,
    SlotInventory,
    SlotStatus,
)


def test_ace1_capabilities_are_json_serializable():
    status = DeviceStatus.initial("ace0", DeviceModel.ACE1, True, True)
    status.connection = ConnectionState.ONLINE
    status.slots[0] = SlotInventory(
        index=0,
        status=SlotStatus.READY,
        material="PLA",
        color=(10, 20, 30),
        temperature=210,
    )

    payload = status.to_dict()
    assert json.loads(json.dumps(payload))["slots"][0]["display_slot"] == 1
    assert payload["capabilities"]["change_tool"] is True
    assert payload["model"] == "ace1"


def test_ace2_is_read_only_even_when_initialized_with_action_request():
    status = DeviceStatus.initial("ace1", DeviceModel.ACE2, True, True)

    assert status.physical_actions_enabled is False
    assert status.capabilities.refresh is True
    assert status.capabilities.change_tool is False
    assert status.capabilities.blocked_reason == "ace2_read_only"


def test_auto_model_remains_read_only_until_resolved():
    capabilities = CapabilitySet.for_device(DeviceModel.AUTO, True)
    assert capabilities.physical_actions is False
    assert capabilities.blocked_reason == "device_model_unresolved"


def test_device_status_requires_four_continuous_slots():
    with pytest.raises(ValueError, match="exactly four"):
        DeviceStatus(device_id="ace0", model=DeviceModel.ACE1, slots=[])

    with pytest.raises(ValueError, match="ordered continuously"):
        DeviceStatus(
            device_id="ace0",
            model=DeviceModel.ACE1,
            slots=[SlotInventory(index=index) for index in (0, 1, 3, 2)],
        )


def test_device_status_rejects_ace2_physical_gate_bypass():
    with pytest.raises(ValueError, match="only ACE1"):
        DeviceStatus(
            device_id="ace0",
            model=DeviceModel.ACE2,
            physical_actions_enabled=True,
        )


def test_slot_inventory_validates_rgb_channels():
    with pytest.raises(ValueError, match="RGB"):
        SlotInventory(index=0, color=(0, 0, 256))
