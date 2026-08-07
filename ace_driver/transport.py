"""Synchronous serial transport with per-device isolation and bounded retries.

The lifecycle and stale-response concerns follow Kobra-S1/ACEPRO's serial
manager. V3 keeps a small synchronous contract suitable for generic Klipper
and permits dependency injection for offline tests.
"""

from __future__ import annotations

from collections import deque
import json
import struct
import threading
import time
from typing import Any, Callable, Deque, Optional, Tuple

try:  # Klipper installations provide pyserial; unit tests do not require it.
    import serial as _pyserial
except ImportError:  # pragma: no cover - exercised by deployment environments.
    _pyserial = None


class SerialTransport:
    """One serial connection and request queue for one logical transport."""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 2.0,
        retries: int = 2,
        *,
        write_timeout: float = 1.0,
        retry_delay: float = 0.05,
        serial_factory: Optional[Callable[..., Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        max_frame_size: int = 4096,
        wire_mode: str = "ace1",
    ) -> None:
        if not port:
            raise ValueError("A stable serial port path is required")
        if timeout <= 0 or retries < 0 or max_frame_size < 10:
            raise ValueError("Invalid serial timeout, retry count, or frame limit")
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.write_timeout = float(write_timeout)
        self.retry_delay = float(retry_delay)
        self.max_frame_size = int(max_frame_size)
        self.wire_mode = str(wire_mode).strip().lower()
        if self.wire_mode not in {"ace1", "ace2"}:
            raise ValueError("wire_mode must be ace1 or ace2")
        self._serial_factory = serial_factory
        self._clock = clock
        self._sleep = sleep
        self._serial: Any = None
        self._request_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._unsolicited: Deque[bytes] = deque(maxlen=64)

    @property
    def is_open(self) -> bool:
        serial_port = self._serial
        return bool(serial_port is not None and getattr(serial_port, "is_open", True))

    def open(self) -> None:
        with self._lifecycle_lock:
            if self.is_open:
                return
            factory = self._serial_factory
            if factory is None:
                if _pyserial is None:
                    raise RuntimeError(
                        "pyserial is required for a real ACE serial connection"
                    )
                factory = _pyserial.Serial
            self._serial = factory(
                port=self.port,
                baudrate=self.baudrate,
                timeout=min(self.timeout, 0.1),
                write_timeout=self.write_timeout,
            )
            if hasattr(self._serial, "open") and not getattr(self._serial, "is_open", True):
                self._serial.open()
            self._reset_input()

    def close(self) -> None:
        with self._request_lock:
            with self._lifecycle_lock:
                serial_port, self._serial = self._serial, None
                if serial_port is not None and hasattr(serial_port, "close"):
                    serial_port.close()

    def request(self, payload: bytes, timeout: Optional[float] = None) -> bytes:
        """Send an idempotent request using the configured retry policy."""
        return self._request(payload, timeout, self.retries)

    def request_once(self, payload: bytes, timeout: Optional[float] = None) -> bytes:
        """Send a non-idempotent request exactly once."""
        return self._request(payload, timeout, 0)

    def _request(
        self, payload: bytes, timeout: Optional[float], retries: int
    ) -> bytes:
        """Write one frame and return the response with the same request ID."""
        frame = bytes(payload)
        effective_timeout = self.timeout if timeout is None else float(timeout)
        if effective_timeout <= 0:
            raise ValueError("timeout must be positive")
        mode = self.wire_mode
        if len(frame) < 7 or frame[:2] != b"\xFF\xAA":
            raise ValueError("ACE request is not a supported framed payload")
        request_id = _frame_id(frame, mode)
        last_error: Optional[BaseException] = None
        with self._request_lock:
            for attempt in range(retries + 1):
                try:
                    if not self.is_open:
                        self.open()
                    self._reset_input()
                    written = self._serial.write(frame)
                    if written is not None and int(written) != len(frame):
                        raise IOError("ACE serial write was incomplete")
                    if hasattr(self._serial, "flush"):
                        self._serial.flush()
                    return self._read_matching(mode, request_id, effective_timeout)
                except Exception as exc:
                    last_error = exc
                    if attempt >= retries:
                        break
                    self._reopen_after_failure()
                    if self.retry_delay:
                        self._sleep(self.retry_delay)
        if isinstance(last_error, TimeoutError):
            raise last_error
        raise IOError("ACE serial request failed: %s" % last_error) from last_error

    def drain_unsolicited(self) -> Tuple[bytes, ...]:
        """Return unmatched complete frames retained by this transport only."""
        with self._request_lock:
            values = tuple(self._unsolicited)
            self._unsolicited.clear()
            return values

    def _read_matching(self, mode: str, request_id: Optional[int], timeout: float) -> bytes:
        deadline = self._clock() + timeout
        buffer = bytearray()
        while self._clock() < deadline:
            chunk = self._serial.read(4096)
            if chunk:
                buffer.extend(chunk)
                if len(buffer) > self.max_frame_size * 2:
                    raise IOError("ACE serial receive buffer exceeded the safety limit")
                while True:
                    extracted = _extract_frame(buffer, mode, self.max_frame_size)
                    if extracted is None:
                        break
                    response, buffer = extracted
                    response_id = _frame_id(response, mode)
                    if request_id is None or response_id is None or response_id == request_id:
                        return response
                    self._unsolicited.append(response)
            else:
                self._sleep(0.001)
        raise TimeoutError(
            "ACE serial response timed out after %.3fs" % timeout
        )

    def _reset_input(self) -> None:
        if self._serial is not None and hasattr(self._serial, "reset_input_buffer"):
            self._serial.reset_input_buffer()

    def _reopen_after_failure(self) -> None:
        try:
            self.close()
        except Exception:
            self._serial = None
        self.open()


def _frame_id(frame: bytes, mode: str) -> Optional[int]:
    try:
        if mode == "ace2":
            return frame[3] | (frame[4] << 8)
        length = struct.unpack("<H", frame[2:4])[0]
        value = json.loads(frame[4 : 4 + length].decode("utf-8"))
        request_id = value.get("id")
        return int(request_id) if request_id is not None else None
    except (IndexError, KeyError, TypeError, ValueError, UnicodeDecodeError):
        return None


def _extract_frame(
    buffer: bytearray, mode: str, max_frame_size: int
) -> Optional[Tuple[bytes, bytearray]]:
    header = buffer.find(b"\xFF\xAA")
    if header < 0:
        if len(buffer) > 1:
            del buffer[:-1]
        return None
    if header:
        del buffer[:header]
    minimum = 7 if mode == "ace1" else 10
    if len(buffer) < minimum:
        return None
    if mode == "ace1":
        frame_size = 7 + struct.unpack("<H", buffer[2:4])[0]
    else:
        frame_size = 10 + int(buffer[6])
    if frame_size > max_frame_size:
        raise IOError("ACE response frame exceeds the safety limit")
    if len(buffer) < frame_size:
        return None
    frame = bytes(buffer[:frame_size])
    remaining = bytearray(buffer[frame_size:])
    return frame, remaining


__all__ = ["SerialTransport"]
