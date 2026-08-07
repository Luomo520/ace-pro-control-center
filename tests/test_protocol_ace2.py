from __future__ import annotations

import struct

import pytest

from ace_driver.protocol import AceProtocolError, AceReadOnlyError, crc16_mcrf4xx
from ace_driver.protocol_ace2 import Ace2BusController, Ace2BusRouter, Ace2Protocol


def varint(value):
    result = bytearray()
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def pb_uint(field, value):
    return varint(field << 3) + varint(value)


def pb_bytes(field, value):
    return varint((field << 3) | 2) + varint(len(value)) + value


def response_frame(request_id, command, payload=b"", device_id=0):
    flags = 0x80 | device_id
    inner = bytes(
        [flags, request_id & 0xFF, request_id >> 8, command, len(payload)]
    ) + payload
    return b"\xFF\xAA" + inner + struct.pack("<H", crc16_mcrf4xx(inner)) + b"\xFE"


def frame_id(frame):
    return frame[3] | (frame[4] << 8)


def test_unbound_ace2_cannot_direct_poll_and_all_physical_actions_are_rejected():
    protocol = Ace2Protocol(device_uid=(1, 2, 3))
    with pytest.raises(AceProtocolError, match="unique bus address"):
        protocol.encode_request("get_status")
    assert protocol.pending_request_ids == ()
    for action in (
        "feed",
        "retract",
        "enable_feed_assist",
        "start_drying",
        "stop_drying",
    ):
        with pytest.raises(AceReadOnlyError):
            protocol.encode_request(action, {})
    with pytest.raises(AceReadOnlyError):
        protocol.feed(0, 10, 5)


def test_uid_discovery_assignment_and_directed_polling_contract():
    first_uid = (101, 102, 103)
    second_uid = (201, 202, 203)
    controller = Ace2BusController([first_uid, second_uid])

    discover = controller.encode_discover()
    discovered = controller.decode_discovery_response(
        response_frame(
            frame_id(discover),
            0,
            pb_uint(1, first_uid[0])
            + pb_uint(2, first_uid[1])
            + pb_uint(3, first_uid[2]),
        )
    )
    assert discovered["result"]["configured_device_id"] == 1

    assignment = controller.encode_assignment(first_uid)
    assert assignment[5] == 1
    assigned = controller.decode_assignment_response(
        response_frame(frame_id(assignment), 1, pb_uint(1, 0))
    )
    assert assigned["result"] == {
        "assigned": True,
        "uid": first_uid,
        "device_id": 1,
    }

    first = controller.protocol_for(first_uid)
    poll = first.encode_request("get_status")
    assert poll[2] == 1
    assert poll[5] == 6
    with pytest.raises(AceProtocolError, match="discovered and assigned"):
        controller.protocol_for(second_uid)


def test_assignment_payload_contains_uid_triplet_and_unique_address():
    controller = Ace2BusController([(1, 2, 3), (4, 5, 6)])
    controller.verify_discovered_uid((1, 2, 3))
    controller.verify_discovered_uid((4, 5, 6))
    first = controller.encode_assignment((1, 2, 3))
    second = controller.encode_assignment((4, 5, 6))
    assert first[5] == second[5] == 1
    assert first[7 : 7 + first[6]].endswith(pb_uint(4, 1))
    assert second[7 : 7 + second[6]].endswith(pb_uint(4, 2))


def test_router_rejects_duplicate_uid_or_address():
    router = Ace2BusRouter()
    router.configure((1, 2, 3), 1)
    with pytest.raises(ValueError, match="configured more than once"):
        router.configure((1, 2, 3), 2)
    with pytest.raises(ValueError, match="configured more than once"):
        router.configure((4, 5, 6), 1)


def test_ace2_status_frame_decodes_and_normalizes_read_only_state():
    router = Ace2BusRouter()
    router.configure((1, 2, 3), 2)
    router.bind((1, 2, 3), 2)
    protocol = Ace2Protocol(device_uid=(1, 2, 3), device_id=2, router=router)
    request = protocol.encode_request("get_status")
    dryer = pb_uint(1, 2) + pb_uint(2, 50) + pb_uint(4, 90)
    occupied_slot = pb_uint(1, 0) + pb_uint(2, 2)
    empty_slot = pb_uint(1, 0) + pb_uint(2, 0)
    payload = (
        pb_uint(1, 1)
        + pb_bytes(2, dryer)
        + pb_uint(3, 29)
        + pb_uint(4, 43)
        + pb_bytes(9, occupied_slot)
        + pb_bytes(9, empty_slot)
    )
    response = protocol.decode_response(
        response_frame(frame_id(request), 6, payload, device_id=2)
    )
    normalized = protocol.normalize_status(response["result"])
    assert normalized["state"] == "ready"
    assert normalized["temperature"] == 29
    assert normalized["dryer"]["active"] is True
    assert [slot["status"] for slot in normalized["slots"]] == ["ready", "empty"]
    assert protocol.capabilities.to_dict()["physical_actions"] is False
