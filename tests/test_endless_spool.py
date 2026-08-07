from ace_driver.endless_spool import EndlessSpoolSelector, MatchMode
from ace_driver.models import (
    ConnectionState,
    DeviceModel,
    DeviceStatus,
    SlotInventory,
    SlotStatus,
)
from ace_driver.tool_map import ToolMap


def online_device(device_id, model=DeviceModel.ACE1, actions=True):
    status = DeviceStatus.initial(device_id, model, True, actions)
    status.connection = ConnectionState.ONLINE
    return status


def ready(device, slot, material="PLA", color=(255, 255, 255)):
    device.slots[slot] = SlotInventory(
        index=slot,
        status=SlotStatus.READY,
        material=material,
        color=color,
    )


def test_exact_mode_prefers_next_matching_tool_across_devices():
    ace0 = online_device("ace0")
    ace1 = online_device("ace1")
    ready(ace0, 0)
    ready(ace0, 3)
    ready(ace1, 0)

    decision = EndlessSpoolSelector(ToolMap(2)).select("T0", [ace0, ace1])

    assert decision.candidate.tool_name == "T3"
    assert [item.tool_name for item in decision.candidates] == ["T3", "T4"]
    assert decision.reason == "candidate_selected"


def test_wraparound_order_is_stable():
    ace0 = online_device("ace0")
    ace1 = online_device("ace1")
    ready(ace1, 3)
    ready(ace0, 0)
    ready(ace1, 0)

    decision = EndlessSpoolSelector(ToolMap(2)).select("T7", [ace0, ace1])
    assert [item.tool_name for item in decision.candidates] == ["T0", "T4"]


def test_exact_and_material_modes_handle_color_differently():
    ace0 = online_device("ace0")
    ready(ace0, 0, color=(255, 0, 0))
    ready(ace0, 1, color=(0, 0, 255))

    exact = EndlessSpoolSelector(ToolMap(1), MatchMode.EXACT).select(0, [ace0])
    material = EndlessSpoolSelector(ToolMap(1), MatchMode.MATERIAL).select(0, [ace0])

    assert exact.candidate is None
    assert material.candidate.tool == 1


def test_unknown_material_never_matches_for_safety():
    ace0 = online_device("ace0")
    ready(ace0, 0, material="Unknown")
    ready(ace0, 1, material="unknown")

    decision = EndlessSpoolSelector(ToolMap(1), MatchMode.MATERIAL).select(0, [ace0])
    assert decision.candidate is None
    assert decision.reason == "source_material_unknown"


def test_ace2_and_offline_devices_are_excluded():
    ace0 = online_device("ace0")
    ace1 = online_device("ace1", DeviceModel.ACE2, actions=True)
    ace2 = online_device("ace2")
    ace2.connection = ConnectionState.OFFLINE
    ready(ace0, 0)
    ready(ace1, 0)
    ready(ace2, 0)

    decision = EndlessSpoolSelector(ToolMap(3)).select(0, [ace0, ace1, ace2])

    assert decision.candidate is None
    assert decision.rejected["T4"] == "ace2_read_only"
    assert decision.rejected["T8"] == "device_offline"


def test_excluded_tools_and_cross_device_policy_are_applied():
    ace0 = online_device("ace0")
    ace1 = online_device("ace1")
    ready(ace0, 0)
    ready(ace0, 1)
    ready(ace1, 0)

    selector = EndlessSpoolSelector(ToolMap(2), allow_cross_device=False)
    decision = selector.select(0, [ace0, ace1], excluded_tools=["T1"])

    assert decision.candidate is None
    assert decision.rejected["T4"] == "cross_device_disabled"
