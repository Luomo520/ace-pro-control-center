from __future__ import annotations

import json
import struct

import pytest

from ace_driver.protocol import AceProtocolError, AceResponseMismatchError, crc16_mcrf4xx
from ace_driver.protocol_ace1 import Ace1Protocol


def make_frame(value):
    payload = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return (
        b"\xFF\xAA"
        + struct.pack("<H", len(payload))
        + payload
        + struct.pack("<H", crc16_mcrf4xx(payload))
        + b"\xFE"
    )


def decode_request(frame):
    length = struct.unpack("<H", frame[2:4])[0]
    return json.loads(frame[4 : 4 + length])


def test_ace1_request_has_json_crc_and_monotonic_rpc_id():
    protocol = Ace1Protocol(request_id=41)
    first = protocol.encode_request("get_status")
    second = protocol.encode_request(
        "feed", {"index": 2, "length": 120, "speed": 25}
    )
    first_value = decode_request(first)
    second_value = decode_request(second)
    assert first_value == {"id": 41, "method": "get_status"}
    assert second_value == {
        "id": 42,
        "method": "feed_filament",
        "params": {"index": 2, "length": 120.0, "speed": 25.0},
    }
    assert first[-1] == 0xFE
    body_length = struct.unpack("<H", second[2:4])[0]
    assert struct.unpack("<H", second[4 + body_length : 6 + body_length])[0] == crc16_mcrf4xx(
        second[4 : 4 + body_length]
    )


def test_ace1_response_matches_request_id_and_ignores_preceding_stale_frame():
    protocol = Ace1Protocol(request_id=10)
    protocol.encode_request("get_status")
    response = protocol.decode_response(
        make_frame({"id": 9, "code": 0, "result": {}})
        + make_frame({"id": 10, "code": 0, "result": {"status": "ready"}})
    )
    assert response["id"] == 10
    assert response["ok"] is True
    assert protocol.pending_request_ids == ()


def test_ace1_rejects_wrong_id_crc_and_truncation():
    protocol = Ace1Protocol(request_id=5)
    protocol.encode_request("get_info")
    with pytest.raises(AceResponseMismatchError):
        protocol.decode_response(make_frame({"id": 6, "code": 0}))

    damaged = bytearray(make_frame({"id": 5, "code": 0}))
    damaged[-2] ^= 0x20
    with pytest.raises(AceProtocolError, match="CRC"):
        protocol.decode_response(bytes(damaged))
    with pytest.raises(AceProtocolError, match="truncated"):
        protocol.decode_response(make_frame({"id": 5, "code": 0})[:-1])


def test_ace1_action_mapping_and_status_normalization():
    protocol = Ace1Protocol()
    drying = decode_request(protocol.start_drying(55, 240))
    assert drying["method"] == "drying"
    assert drying["params"] == {"temp": 55, "fan_speed": 7000, "duration": 240}

    status = protocol.normalize_status(
        {
            "status": "ready",
            "temp": 31,
            "dryer_status": {
                "status": "drying",
                "target_temp": 55,
                "remain_time": 120,
            },
            "slots": [
                {
                    "index": 0,
                    "status": "ready",
                    "type": "PLA",
                    "color": [12, 34, 56],
                    "rfid": 2,
                }
            ],
        }
    )
    assert status["state"] == "ready"
    assert status["dryer"]["active"] is True
    assert status["slots"][0]["material"] == "PLA"
    assert status["slots"][0]["color"] == "#0C2238"


def test_ace1_invalid_params_do_not_leave_pending_requests():
    protocol = Ace1Protocol()
    with pytest.raises(KeyError):
        protocol.encode_request("feed", {"index": 0})
    assert protocol.pending_request_ids == ()
