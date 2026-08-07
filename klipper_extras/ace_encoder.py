"""Optional shared filament encoder for Ace Pro Control Center.

The counter model is informed by Happy Hare's GPLv3 ``mmu_encoder`` extra,
but keeps only generic pulse measurement and ACE motion validation.
"""

from __future__ import annotations

import logging
import math
import threading
import uuid

try:
    from . import pulse_counter
except ImportError:  # Allows repository tests to inject a fake Klipper module.
    pulse_counter = None


class AceEncoder:
    MODES = {"off", "monitor", "protect"}
    VALIDATION_MODES = {"movement", "tracking"}
    MINIMUM_VALID_PULSES = 2
    DEFAULT_CALIBRATION_SEGMENT_LENGTH = 150.0
    DEFAULT_CALIBRATION_SEGMENTS = 3
    MAX_CALIBRATION_SEGMENTS = 10
    CALIBRATION_PASS_DEVIATION = 0.05
    CALIBRATION_WARN_DEVIATION = 0.10

    def __init__(self, config):
        if pulse_counter is None:
            raise config.error("ACE 编码器需要 Klipper pulse_counter 模块")
        self.name = config.get_name().split()[-1]
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self._lock = threading.RLock()
        self._counts = 0
        self._last_hardware_count = None
        self._last_sample_time = None
        self._available = False
        self._calibration_start = None
        self._calibration_last_reported_counts = None
        self._calibration_reporter = None
        self._calibration_target_length = self.DEFAULT_CALIBRATION_SEGMENT_LENGTH
        self._calibration_required_segments = self.DEFAULT_CALIBRATION_SEGMENTS
        self._calibration_segments = []
        self._calibration_state = "idle"
        self._calibration_last_result = None
        self._last_event = None
        self._fault = None
        self._tracking_ratio = None
        self.resolution = config.getfloat("encoder_resolution", 0.0, minval=0.0)
        self.detection_length = config.getfloat(
            "detection_length", 20.0, above=0.0
        )
        self.min_tracking_ratio = config.getfloat(
            "min_tracking_ratio", 0.6, above=0.0
        )
        if not math.isfinite(self.resolution):
            raise config.error("ACE 编码器分辨率必须是有限数值")
        if not math.isfinite(self.detection_length):
            raise config.error("ACE 编码器检测长度必须是有限数值")
        if (
            not math.isfinite(self.min_tracking_ratio)
            or self.min_tracking_ratio > 1.0
        ):
            raise config.error(
                "ACE 编码器最小跟踪比例必须在 0 到 1 之间"
            )
        self.mode = str(config.get("mode", "off")).strip().lower()
        if self.mode not in self.MODES:
            raise config.error("ACE 编码器模式必须是 off、monitor 或 protect")

        self.sample_time = config.getfloat("sample_time", 0.1, above=0.0)
        self.poll_time = config.getfloat("poll_time", 0.001, above=0.0)
        encoder_pin = config.get("encoder_pin")
        self._counter = pulse_counter.MCU_counter(
            self.printer, encoder_pin, self.sample_time, self.poll_time
        )
        self._counter.setup_callback(self._counter_callback)

    def set_calibration_reporter(self, reporter):
        if reporter is not None and not callable(reporter):
            raise ValueError("编码器校准计数报告器必须是可调用对象")
        with self._lock:
            self._calibration_reporter = reporter

    def configure(
        self,
        *,
        resolution=None,
        detection_length=None,
        min_tracking_ratio=None,
        mode=None
    ):
        with self._lock:
            if resolution is not None:
                value = float(resolution)
                if not math.isfinite(value) or value < 0:
                    raise ValueError(
                        "编码器分辨率必须是有限的非负数"
                    )
                self.resolution = value
            if detection_length is not None:
                value = float(detection_length)
                if not math.isfinite(value) or value <= 0:
                    raise ValueError(
                        "编码器检测长度必须是有限的正数"
                    )
                self.detection_length = value
            if min_tracking_ratio is not None:
                value = float(min_tracking_ratio)
                if not math.isfinite(value) or not 0 < value <= 1.0:
                    raise ValueError(
                        "编码器最小跟踪比例必须在 0 到 1 之间"
                    )
                self.min_tracking_ratio = value
            if mode is not None:
                value = str(mode).strip().lower()
                if value not in self.MODES:
                    raise ValueError("编码器模式必须是 off、monitor 或 protect")
                self.mode = value

    def set_resolution(self, resolution):
        self.configure(resolution=resolution)

    def clear_fault(self):
        with self._lock:
            self._fault = None

    def get_settle_time(self):
        return self.sample_time + self.poll_time * 2.0

    def begin_motion(
        self,
        action,
        device_id,
        commanded_length,
        *,
        validation="movement"
    ):
        with self._lock:
            if self.mode == "off":
                return None
            validation_mode = str(validation).strip().lower()
            if validation_mode not in self.VALIDATION_MODES:
                raise ValueError("编码器验证方式必须是 movement 或 tracking")
            return {
                "id": uuid.uuid4().hex,
                "action": str(action),
                "device_id": str(device_id),
                "commanded_length": abs(float(commanded_length)),
                "validation": validation_mode,
                "start_counts": self._counts,
                "started_at": self.reactor.monotonic(),
            }

    def cancel_motion(self, token):
        if token is None:
            return
        with self._lock:
            self._last_event = {
                "id": token.get("id"),
                "state": "cancelled",
                "action": token.get("action"),
                "device_id": token.get("device_id"),
            }

    def finish_motion(
        self,
        token,
        *,
        command_completed=True,
        commanded_length=None
    ):
        if token is None:
            return None
        with self._lock:
            pulses = max(0, self._counts - int(token["start_counts"]))
            commanded = abs(
                float(
                    token["commanded_length"]
                    if commanded_length is None
                    else commanded_length
                )
            )
            validation = str(token.get("validation") or "movement")
            measured = pulses * self.resolution if self.resolution > 0 else None
            ratio = (
                measured / commanded
                if (
                    validation == "tracking"
                    and measured is not None
                    and commanded > 0
                    and command_completed
                )
                else None
            )
            minimum_pulses = (
                self.MINIMUM_VALID_PULSES
                if commanded >= self.detection_length
                else 1
            )
            fault = None
            if not self._available:
                fault = {
                    "code": "encoder_unavailable",
                    "message": "共享编码器尚未收到有效计数样本。",
                }
            elif commanded > 0 and pulses < minimum_pulses:
                fault = {
                    "code": "encoder_no_motion",
                    "message": "共享编码器未确认耗材移动。",
                    "details": {
                        "pulses": pulses,
                        "minimum_pulses": minimum_pulses,
                    },
                }
            elif (
                validation == "tracking"
                and commanded >= self.detection_length
                and ratio is not None
                and ratio < self.min_tracking_ratio
            ):
                fault = {
                    "code": "encoder_tracking_low",
                    "message": "共享编码器检测到的移动比例低于配置的挤出机跟踪比例。",
                    "details": {
                        "tracking_ratio": ratio,
                        "minimum_tracking_ratio": self.min_tracking_ratio,
                    },
                }

            event = {
                "id": token["id"],
                "state": "fault" if fault else "measured",
                "action": token["action"],
                "device_id": token["device_id"],
                "commanded_length": commanded,
                "command_completed": bool(command_completed),
                "validation": validation,
                "pulses": pulses,
                "measured_length": measured,
                "tracking_ratio": ratio,
                "finished_at": self.reactor.monotonic(),
            }
            self._last_event = event
            self._tracking_ratio = ratio
            self._fault = fault
            result = dict(event)
            result["fault"] = None if fault is None else dict(fault)
            result["mode"] = self.mode
            return result

    def start_calibration(
        self,
        segment_length=DEFAULT_CALIBRATION_SEGMENT_LENGTH,
        segments=DEFAULT_CALIBRATION_SEGMENTS,
    ):
        target_length = self._validated_calibration_length(segment_length)
        try:
            required_segments = int(segments)
        except (TypeError, ValueError) as exc:
            raise ValueError("编码器校准段数必须是 1 到 10 之间的整数") from exc
        if (
            required_segments != segments
            or not 1 <= required_segments <= self.MAX_CALIBRATION_SEGMENTS
        ):
            raise ValueError("编码器校准段数必须是 1 到 10 之间的整数")
        with self._lock:
            if not self._available:
                raise RuntimeError("共享编码器尚未报告有效脉冲。")
            if self._calibration_start is not None:
                raise RuntimeError("共享编码器校准已在进行中。")
            self._calibration_start = self._counts
            self._calibration_last_reported_counts = self._counts
            self._calibration_target_length = target_length
            self._calibration_required_segments = required_segments
            self._calibration_segments = []
            self._calibration_state = "collecting"
            self._calibration_last_result = None
            return {
                "started": True,
                "state": self._calibration_state,
                "start_counts": self._calibration_start,
                "segment_length": target_length,
                "required_segments": required_segments,
                "current_segment": 1,
            }

    def finish_calibration(self, measured_length):
        length = self._validated_calibration_length(measured_length)
        with self._lock:
            if self._calibration_start is None:
                raise RuntimeError("共享编码器校准尚未开始。")
            pulses = self._counts - self._calibration_start
            if pulses < self.MINIMUM_VALID_PULSES:
                raise RuntimeError(
                    "编码器校准第 %d 段收到的脉冲过少，至少需要 %d 个脉冲。"
                    % (
                        len(self._calibration_segments) + 1,
                        self.MINIMUM_VALID_PULSES,
                    )
                )
            segment = {
                "index": len(self._calibration_segments) + 1,
                "measured_length": length,
                "pulses": pulses,
                "mm_per_pulse": length / float(pulses),
            }
            self._calibration_segments.append(segment)
            completed = len(self._calibration_segments)
            if completed < self._calibration_required_segments:
                self._calibration_start = self._counts
                self._calibration_last_reported_counts = self._counts
                return {
                    "calibrated": False,
                    "segment_complete": True,
                    "state": self._calibration_state,
                    "segment": dict(segment),
                    "segments": self._copy_calibration_segments(),
                    "completed_segments": completed,
                    "required_segments": self._calibration_required_segments,
                    "current_segment": completed + 1,
                    "remaining_segments": self._calibration_required_segments - completed,
                    "segment_length": self._calibration_target_length,
                }

            resolutions = [item["mm_per_pulse"] for item in self._calibration_segments]
            mean_resolution = sum(resolutions) / float(len(resolutions))
            max_deviation = max(
                abs(value - mean_resolution) / mean_resolution
                for value in resolutions
            )
            quality = "pass"
            warning = None
            if max_deviation > self.CALIBRATION_WARN_DEVIATION + 1e-12:
                quality = "rejected"
            elif max_deviation > self.CALIBRATION_PASS_DEVIATION + 1e-12:
                quality = "warning"
                warning = (
                    "各段校准结果最大偏差为 %.2f%%，超过 5%%；结果已保存，"
                    "建议检查编码轮压力和耗材打滑后重新校准。"
                    % (max_deviation * 100.0)
                )

            result = {
                "calibrated": quality != "rejected",
                "segment_complete": True,
                "state": "completed" if quality != "rejected" else "rejected",
                "quality": quality,
                "warning": warning,
                "measured_length": sum(
                    item["measured_length"] for item in self._calibration_segments
                ),
                "pulses": sum(item["pulses"] for item in self._calibration_segments),
                "resolution": mean_resolution,
                "segments": self._copy_calibration_segments(),
                "completed_segments": completed,
                "required_segments": self._calibration_required_segments,
                "max_deviation": max_deviation,
                "max_deviation_percent": max_deviation * 100.0,
            }
            self._calibration_start = None
            self._calibration_last_reported_counts = None
            self._calibration_state = result["state"]
            self._calibration_last_result = self._copy_calibration_result(result)
            if quality == "rejected":
                raise RuntimeError(
                    "编码器各段校准结果最大偏差为 %.2f%%，超过 10%%，"
                    "本次结果已拒绝保存。请检查编码轮压力和耗材打滑后重试。"
                    % (max_deviation * 100.0)
                )
            self.resolution = mean_resolution
            self._fault = None
            return result

    def cancel_calibration(self):
        with self._lock:
            was_active = self._calibration_start is not None
            self._calibration_start = None
            self._calibration_last_reported_counts = None
            if was_active:
                self._calibration_state = "cancelled"
                self._calibration_last_result = {
                    "state": "cancelled",
                    "calibrated": False,
                    "segments": self._copy_calibration_segments(),
                    "completed_segments": len(self._calibration_segments),
                    "required_segments": self._calibration_required_segments,
                }
            return {
                "cancelled": was_active,
                "calibration_active": False,
            }

    def get_status(self, eventtime=None):
        del eventtime
        with self._lock:
            position = (
                self._counts * self.resolution if self.resolution > 0 else None
            )
            return {
                "configured": True,
                "available": self._available,
                "mode": self.mode,
                "calibrated": self.resolution > 0,
                "resolution": self.resolution if self.resolution > 0 else None,
                "detection_length": self.detection_length,
                "min_tracking_ratio": self.min_tracking_ratio,
                "counts": self._counts,
                "position": position,
                "tracking_ratio": self._tracking_ratio,
                "armed": (
                    self.mode == "protect"
                    and self._available
                    and self.resolution > 0
                    and self._fault is None
                ),
                "last_sample_time": self._last_sample_time,
                "calibration_active": self._calibration_start is not None,
                "calibration": self._calibration_status(),
                "last_event": (
                    None if self._last_event is None else dict(self._last_event)
                ),
                "fault": None if self._fault is None else dict(self._fault),
            }

    @staticmethod
    def _validated_calibration_length(measured_length):
        try:
            length = float(measured_length)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "编码器校准长度必须在 0.01 到 2000 mm 之间"
            ) from exc
        if not math.isfinite(length) or not 0.01 <= length <= 2000.0:
            raise ValueError(
                "编码器校准长度必须在 0.01 到 2000 mm 之间"
            )
        return length

    def _copy_calibration_segments(self):
        return [dict(item) for item in self._calibration_segments]

    @staticmethod
    def _copy_calibration_result(result):
        copied = dict(result)
        if "segments" in copied:
            copied["segments"] = [dict(item) for item in copied["segments"]]
        return copied

    def _calibration_status(self):
        active = self._calibration_start is not None
        completed = len(self._calibration_segments)
        return {
            "active": active,
            "state": self._calibration_state,
            "segment_length": self._calibration_target_length,
            "required_segments": self._calibration_required_segments,
            "completed_segments": completed,
            "current_segment": (
                min(completed + 1, self._calibration_required_segments)
                if active
                else None
            ),
            "current_segment_pulses": (
                max(0, self._counts - self._calibration_start)
                if active
                else 0
            ),
            "segments": self._copy_calibration_segments(),
            "last_result": (
                None
                if self._calibration_last_result is None
                else self._copy_calibration_result(self._calibration_last_result)
            ),
        }

    def _counter_callback(self, print_time, count, count_time):
        del print_time
        report = None
        reporter = None
        with self._lock:
            if self._last_hardware_count is not None:
                delta = int(count) - self._last_hardware_count
                if delta > 0:
                    self._counts += delta
                    if (
                        self._calibration_start is not None
                        and self._calibration_reporter is not None
                    ):
                        report_base = self._calibration_last_reported_counts
                        if report_base is None:
                            report_base = self._calibration_start
                        increment = self._counts - report_base
                        if increment > 0:
                            report = {
                                "increment": increment,
                                "calibration_counts": (
                                    self._counts - self._calibration_start
                                ),
                                "total_counts": self._counts,
                                "segment": len(self._calibration_segments) + 1,
                                "required_segments": self._calibration_required_segments,
                            }
                            self._calibration_last_reported_counts = self._counts
                            reporter = self._calibration_reporter
            self._last_hardware_count = int(count)
            self._last_sample_time = float(count_time)
            self._available = True
        if report is not None and reporter is not None:
            try:
                reporter(report)
            except Exception:
                logging.exception("ACE 编码器校准实时计数输出失败")


def load_config_prefix(config):
    return AceEncoder(config)


__all__ = ["AceEncoder", "load_config_prefix"]
