from __future__ import annotations

import json
import struct
import threading
import time

from ace_driver.protocol import crc16_mcrf4xx
from ace_driver.protocol_ace1 import Ace1Protocol
from ace_driver.transport import SerialTransport


def ace1_frame(value):
    body = json.dumps(value, separators=(",", ":")).encode("utf-8")
    return (
        b"\xFF\xAA"
        + struct.pack("<H", len(body))
        + body
        + struct.pack("<H", crc16_mcrf4xx(body))
        + b"\xFE"
    )


def request_id(frame):
    length = struct.unpack("<H", frame[2:4])[0]
    return json.loads(frame[4 : 4 + length])["id"]


class FakeSerial:
    def __init__(self, responder=None, read_delay=0):
        self.responder = responder
        self.read_delay = read_delay
        self.is_open = True
        self.buffer = bytearray()
        self.writes = []
        self.active = 0
        self.max_active = 0

    def write(self, payload):
        self.writes.append(bytes(payload))
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.responder:
            response = self.responder(bytes(payload))
            if response:
                self.buffer.extend(response)
        return len(payload)

    def read(self, _size):
        if self.read_delay:
            time.sleep(self.read_delay)
        if not self.buffer:
            return b""
        result = bytes(self.buffer)
        self.buffer.clear()
        self.active = max(0, self.active - 1)
        return result

    def reset_input_buffer(self):
        self.buffer.clear()

    def flush(self):
        pass

    def close(self):
        self.is_open = False

    def open(self):
        self.is_open = True


def success_response(frame):
    return ace1_frame({"id": request_id(frame), "code": 0, "result": {"ok": True}})


def ace2_frame(request_id_value, command=6, *, response=True):
    flags = 0x80 if response else 0
    inner = bytes(
        [flags, request_id_value & 0xFF, request_id_value >> 8, command, 0]
    )
    return (
        b"\xFF\xAA"
        + inner
        + struct.pack("<H", crc16_mcrf4xx(inner))
        + b"\xFE"
    )


def test_transport_lifecycle_and_stable_interface():
    endpoint = FakeSerial(success_response)
    transport = SerialTransport("fake0", serial_factory=lambda **_kwargs: endpoint)
    assert transport.is_open is False
    transport.open()
    assert transport.is_open is True
    request = Ace1Protocol().encode_request("get_status")
    assert request_id(transport.request(request)) == request_id(request)
    transport.close()
    assert transport.is_open is False


def test_transport_skips_stale_response_and_retains_it_per_instance():
    def responder(frame):
        current = request_id(frame)
        return ace1_frame({"id": current - 1, "code": 0}) + success_response(frame)

    endpoint = FakeSerial(responder)
    transport = SerialTransport("fake0", serial_factory=lambda **_kwargs: endpoint)
    request = Ace1Protocol(request_id=10).encode_request("get_status")
    response = transport.request(request)
    assert request_id(response) == 10
    stale = transport.drain_unsolicited()
    assert len(stale) == 1
    assert request_id(stale[0]) == 9


def test_transport_retries_after_timeout_with_same_request_id():
    endpoints = [FakeSerial(), FakeSerial(success_response)]

    def factory(**_kwargs):
        return endpoints.pop(0)

    transport = SerialTransport(
        "fake0", timeout=0.01, retries=1, retry_delay=0, serial_factory=factory
    )
    request = Ace1Protocol(request_id=22).encode_request("get_status")
    response = transport.request(request)
    assert request_id(response) == 22
    assert len(endpoints) == 0


def test_non_idempotent_request_is_never_retried():
    endpoints = [FakeSerial(), FakeSerial(success_response)]

    def factory(**_kwargs):
        return endpoints.pop(0)

    transport = SerialTransport(
        "fake0", timeout=0.01, retries=2, retry_delay=0, serial_factory=factory
    )
    request = Ace1Protocol(request_id=23).encode_request(
        "feed", {"index": 0, "length": 10, "speed": 5}
    )
    try:
        transport.request_once(request)
    except TimeoutError:
        pass
    else:
        raise AssertionError("non-idempotent timeout must be reported")
    assert len(endpoints) == 1


def test_shared_transport_serializes_concurrent_requests():
    endpoint = FakeSerial(success_response, read_delay=0.01)
    transport = SerialTransport("shared-bus", serial_factory=lambda **_kwargs: endpoint)
    protocol = Ace1Protocol()
    requests = [protocol.encode_request("get_status") for _ in range(4)]
    responses = []

    def worker(frame):
        responses.append(transport.request(frame))

    threads = [threading.Thread(target=worker, args=(frame,)) for frame in requests]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert len(responses) == 4
    assert endpoint.max_active == 1
    assert sorted(request_id(item) for item in responses) == [1, 2, 3, 4]


def test_separate_transports_do_not_share_unsolicited_queues():
    first = SerialTransport("first", serial_factory=lambda **_kwargs: FakeSerial(success_response))
    second = SerialTransport("second", serial_factory=lambda **_kwargs: FakeSerial(success_response))
    assert first.drain_unsolicited() == ()
    assert second.drain_unsolicited() == ()


def test_ace2_wire_mode_does_not_depend_on_request_id_bytes():
    def responder(frame):
        current = frame[3] | (frame[4] << 8)
        return ace2_frame(current)

    endpoint = FakeSerial(responder)
    transport = SerialTransport(
        "ace2-bus",
        wire_mode="ace2",
        serial_factory=lambda **_kwargs: endpoint,
    )
    for current in (0x7AFF, 0x7B00, 0x7BFF):
        response = transport.request(ace2_frame(current, response=False))
        assert response[3] | (response[4] << 8) == current
