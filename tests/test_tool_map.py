import pytest

from ace_driver.tool_map import ToolMap, ToolMapError, parse_tool


@pytest.mark.parametrize("device_count", [1, 2, 3, 4])
def test_mapping_is_stable_for_each_supported_device_count(device_count):
    mapping = ToolMap(device_count)

    assert mapping.tool_count == device_count * 4
    for tool in range(mapping.tool_count):
        target = mapping.resolve("T%d" % tool)
        assert target.device_id == "ace%d" % (tool // 4)
        assert target.slot == tool % 4
        assert target.display_slot == (tool % 4) + 1


def test_full_mapping_reaches_t15():
    target = ToolMap(4).resolve("T15")
    assert target.device_id == "ace3"
    assert target.slot == 3


def test_unload_aliases_resolve_to_no_target():
    mapping = ToolMap(1)
    assert mapping.resolve("TR") is None
    assert mapping.resolve(-1) is None
    assert parse_tool("-1") == -1


def test_unconfigured_tool_is_rejected_without_changing_mapping():
    mapping = ToolMap(2)
    with pytest.raises(ToolMapError, match="not configured"):
        mapping.resolve("T8")
    assert mapping.resolve("T7").device_id == "ace1"


@pytest.mark.parametrize("value", [0, 5, "two", True])
def test_invalid_device_counts_are_rejected(value):
    with pytest.raises(ToolMapError):
        ToolMap(value)


def test_device_and_slot_reverse_mapping():
    target = ToolMap(4).for_slot("ace2", 1)
    assert target.tool_name == "T9"

    with pytest.raises(ToolMapError, match="not configured"):
        ToolMap(1).for_slot("ace1", 0)
