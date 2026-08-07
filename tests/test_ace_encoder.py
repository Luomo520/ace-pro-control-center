from __future__ import annotations

from types import SimpleNamespace

import pytest

from klipper_extras import ace_encoder


class FakeCounter:
    instances = []

    def __init__(self, printer, pin, sample_time, poll_time):
        self.printer = printer
        self.pin = pin
        self.sample_time = sample_time
        self.poll_time = poll_time
        self.callback = None
        self.instances.append(self)

    def setup_callback(self, callback):
        self.callback = callback

    def sample(self, count, count_time):
        self.callback(count_time, count, count_time)


class FakeConfig:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.reactor = SimpleNamespace(monotonic=lambda: 123.0)
        self.printer = SimpleNamespace(get_reactor=lambda: self.reactor)

    def get_name(self):
        return "ace_encoder shared"

    def get_printer(self):
        return self.printer

    def get(self, name, default=None):
        return self.values.get(name, default)

    def getfloat(self, name, default=None, minval=None, above=None):
        value = float(self.values.get(name, default))
        if minval is not None and value < minval:
            raise ValueError(name)
        if above is not None and value <= above:
            raise ValueError(name)
        return value

    @staticmethod
    def error(message):
        return RuntimeError(message)


@pytest.fixture(autouse=True)
def fake_pulse_counter(monkeypatch):
    FakeCounter.instances = []
    monkeypatch.setattr(
        ace_encoder,
        "pulse_counter",
        SimpleNamespace(MCU_counter=FakeCounter),
    )


def make_encoder(**values):
    values.setdefault("encoder_pin", "^PC3")
    return ace_encoder.AceEncoder(FakeConfig(values))


def test_counter_reports_availability_distance_and_tracking_ratio():
    encoder = make_encoder(encoder_resolution=0.5, mode="monitor")
    counter = FakeCounter.instances[-1]
    counter.sample(10, 1.0)
    token = encoder.begin_motion(
        "extruder_load", "extruder", 10, validation="tracking"
    )
    counter.sample(30, 2.0)

    event = encoder.finish_motion(token)
    status = encoder.get_status()

    assert event["pulses"] == 20
    assert event["measured_length"] == pytest.approx(10)
    assert event["tracking_ratio"] == pytest.approx(1)
    assert event["fault"] is None
    assert status["available"] is True
    assert status["position"] == pytest.approx(10)


def test_ace_dc_motion_never_uses_commanded_reference_as_tracking_distance():
    encoder = make_encoder(
        encoder_resolution=0.5,
        detection_length=20,
        min_tracking_ratio=0.9,
        mode="protect",
    )
    counter = FakeCounter.instances[-1]
    counter.sample(10, 1.0)
    token = encoder.begin_motion("load", "ace0", 100, validation="movement")
    counter.sample(30, 2.0)

    event = encoder.finish_motion(token)

    assert event["pulses"] == 20
    assert event["measured_length"] == pytest.approx(10)
    assert event["tracking_ratio"] is None
    assert event["fault"] is None


def test_extruder_tracking_reports_ratio_below_configured_minimum():
    encoder = make_encoder(
        encoder_resolution=0.5,
        detection_length=20,
        min_tracking_ratio=0.6,
        mode="protect",
    )
    counter = FakeCounter.instances[-1]
    counter.sample(10, 1.0)
    token = encoder.begin_motion(
        "extruder_load", "extruder", 25, validation="tracking"
    )
    counter.sample(20, 2.0)

    event = encoder.finish_motion(token)

    assert event["tracking_ratio"] == pytest.approx(0.2)
    assert event["fault"]["code"] == "encoder_tracking_low"
    assert event["fault"]["details"]["minimum_tracking_ratio"] == pytest.approx(0.6)


def test_protect_mode_reports_no_motion_after_detection_length():
    encoder = make_encoder(
        encoder_resolution=0.5,
        detection_length=20,
        mode="protect",
    )
    counter = FakeCounter.instances[-1]
    counter.sample(10, 1.0)

    event = encoder.finish_motion(
        encoder.begin_motion("unload", "ace0", 25)
    )

    assert event["fault"]["code"] == "encoder_no_motion"
    assert encoder.get_status()["armed"] is False
    encoder.clear_fault()
    assert encoder.get_status()["fault"] is None
    assert encoder.get_status()["armed"] is True


def test_short_motion_without_any_pulse_triggers_no_motion_fault():
    encoder = make_encoder(
        encoder_resolution=0.5,
        detection_length=20,
        mode="protect",
    )
    FakeCounter.instances[-1].sample(10, 1.0)

    event = encoder.finish_motion(encoder.begin_motion("load", "ace0", 10))

    assert event["fault"]["code"] == "encoder_no_motion"
    assert event["fault"]["details"]["minimum_pulses"] == 1


def test_short_motion_with_one_pulse_confirms_movement_without_ratio_check():
    encoder = make_encoder(
        encoder_resolution=0.5,
        detection_length=20,
        mode="protect",
    )
    counter = FakeCounter.instances[-1]
    counter.sample(10, 1.0)
    token = encoder.begin_motion("load", "ace0", 10)
    counter.sample(11, 2.0)

    event = encoder.finish_motion(token)

    assert event["pulses"] == 1
    assert event["tracking_ratio"] is None
    assert event["fault"] is None


def test_separate_movement_windows_detect_a_stall_after_initial_pulses():
    encoder = make_encoder(
        encoder_resolution=0.5,
        detection_length=20,
        mode="protect",
    )
    counter = FakeCounter.instances[-1]
    counter.sample(10, 1.0)
    first = encoder.begin_motion("load", "ace0", 20)
    counter.sample(12, 2.0)

    assert encoder.finish_motion(first)["fault"] is None

    second = encoder.begin_motion("load", "ace0", 20)
    stalled = encoder.finish_motion(second)

    assert stalled["fault"]["code"] == "encoder_no_motion"


def test_default_three_segment_calibration_records_each_segment_and_saves_mean():
    encoder = make_encoder(mode="off")
    counter = FakeCounter.instances[-1]
    counter.sample(5, 1.0)
    started = encoder.start_calibration()
    assert started["start_counts"] == 0
    assert started["segment_length"] == pytest.approx(150)
    assert started["required_segments"] == 3
    counter.sample(105, 2.0)

    first = encoder.finish_calibration(150)
    counter.sample(205, 3.0)
    second = encoder.finish_calibration(150)
    counter.sample(305, 4.0)
    result = encoder.finish_calibration(150)

    assert first["calibrated"] is False
    assert first["current_segment"] == 2
    assert second["current_segment"] == 3
    assert result["calibrated"] is True
    assert result["quality"] == "pass"
    assert result["pulses"] == 300
    assert result["resolution"] == pytest.approx(1.5)
    assert [item["pulses"] for item in result["segments"]] == [100, 100, 100]
    assert [item["mm_per_pulse"] for item in result["segments"]] == pytest.approx(
        [1.5, 1.5, 1.5]
    )
    assert encoder.get_status()["calibrated"] is True


def test_calibration_deviation_boundaries_pass_warn_and_reject():
    cases = [
        ([100, 105, 95], "pass", True),
        ([100, 110, 90], "warning", True),
        ([100, 111, 89], "rejected", False),
    ]
    for lengths, quality, accepted in cases:
        encoder = make_encoder(encoder_resolution=0.75, mode="off")
        counter = FakeCounter.instances[-1]
        counter.sample(5, 1.0)
        encoder.start_calibration()
        counter.sample(105, 2.0)
        encoder.finish_calibration(lengths[0])
        counter.sample(205, 3.0)
        encoder.finish_calibration(lengths[1])
        counter.sample(305, 4.0)

        if accepted:
            result = encoder.finish_calibration(lengths[2])
            assert result["quality"] == quality
            assert result["calibrated"] is True
            assert result["max_deviation_percent"] == pytest.approx(
                5.0 if quality == "pass" else 10.0
            )
            assert bool(result["warning"]) is (quality == "warning")
            assert encoder.get_status()["resolution"] == pytest.approx(1.0)
        else:
            with pytest.raises(RuntimeError, match="超过 10%"):
                encoder.finish_calibration(lengths[2])
            status = encoder.get_status()
            assert status["calibration_active"] is False
            assert status["calibration"]["state"] == "rejected"
            assert status["calibration"]["last_result"]["quality"] == "rejected"
            assert status["resolution"] == pytest.approx(0.75)


def test_too_few_pulses_rejects_only_current_segment_and_keeps_session_active():
    encoder = make_encoder(encoder_resolution=0.5, mode="off")
    counter = FakeCounter.instances[-1]
    counter.sample(5, 1.0)
    encoder.start_calibration()
    counter.sample(6, 2.0)

    with pytest.raises(RuntimeError, match="第 1 段.*至少需要 2"):
        encoder.finish_calibration(150)

    status = encoder.get_status()
    assert status["calibration_active"] is True
    assert status["calibration"]["current_segment"] == 1
    assert status["calibration"]["current_segment_pulses"] == 1
    assert status["calibration"]["segments"] == []
    assert status["resolution"] == pytest.approx(0.5)


def test_calibration_rejects_non_finite_and_out_of_range_lengths():
    for value in (0.009, 2000.01, float("nan"), float("inf"), float("-inf")):
        encoder = make_encoder(mode="off")
        counter = FakeCounter.instances[-1]
        counter.sample(5, 1.0)
        encoder.start_calibration()
        counter.sample(105, 2.0)

        with pytest.raises(ValueError, match="0.01 到 2000"):
            encoder.finish_calibration(value)

        assert encoder.get_status()["calibration_active"] is True


def test_calibration_cannot_be_started_twice():
    encoder = make_encoder(mode="off")
    FakeCounter.instances[-1].sample(5, 1.0)
    encoder.start_calibration()

    with pytest.raises(RuntimeError, match="已在进行"):
        encoder.start_calibration()


def test_calibration_can_be_cancelled_without_changing_resolution():
    encoder = make_encoder(encoder_resolution=0.5, mode="off")
    counter = FakeCounter.instances[-1]
    counter.sample(5, 1.0)
    encoder.start_calibration()
    counter.sample(25, 2.0)

    result = encoder.cancel_calibration()

    assert result == {"cancelled": True, "calibration_active": False}
    assert encoder.get_status()["calibration_active"] is False
    assert encoder.get_status()["resolution"] == pytest.approx(0.5)
    assert encoder.cancel_calibration()["cancelled"] is False


def test_calibration_reports_only_new_pulses_until_finished():
    encoder = make_encoder(mode="off")
    counter = FakeCounter.instances[-1]
    reports = []
    encoder.set_calibration_reporter(reports.append)

    counter.sample(5, 1.0)
    counter.sample(8, 1.1)
    assert reports == []

    assert encoder.start_calibration()["start_counts"] == 3
    counter.sample(8, 1.2)
    counter.sample(15, 1.3)
    counter.sample(20, 1.4)

    assert reports == [
        {
            "increment": 7,
            "calibration_counts": 7,
            "total_counts": 10,
            "segment": 1,
            "required_segments": 3,
        },
        {
            "increment": 5,
            "calibration_counts": 12,
            "total_counts": 15,
            "segment": 1,
            "required_segments": 3,
        },
    ]

    encoder.cancel_calibration()
    counter.sample(25, 1.5)
    assert len(reports) == 2


def test_cancelled_calibration_stops_reporting_and_reporter_failure_is_isolated():
    encoder = make_encoder(mode="off")
    counter = FakeCounter.instances[-1]
    attempts = []

    def failing_reporter(event):
        attempts.append(event)
        raise RuntimeError("test reporter failure")

    encoder.set_calibration_reporter(failing_reporter)
    counter.sample(5, 1.0)
    encoder.start_calibration()
    counter.sample(12, 1.1)

    assert attempts == [
        {
            "increment": 7,
            "calibration_counts": 7,
            "total_counts": 7,
            "segment": 1,
            "required_segments": 3,
        }
    ]
    assert encoder.get_status()["counts"] == 7

    encoder.cancel_calibration()
    counter.sample(20, 1.2)
    assert len(attempts) == 1
    assert encoder.get_status()["counts"] == 15


def test_off_mode_does_not_create_motion_tokens():
    encoder = make_encoder(mode="off")

    assert encoder.begin_motion("load", "ace0", 100) is None
