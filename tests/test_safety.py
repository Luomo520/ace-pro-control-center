from types import SimpleNamespace

import pytest

from ace_driver.errors import AceCapabilityError, AceSafetyError
from ace_driver.safety import SafetyContext, SafetyPolicy


def device(**overrides):
    values = dict(
        model="ace1",
        connected=True,
        physical_actions_enabled=True,
        capabilities={"select_tool"},
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_ui_physical_action_requires_confirmation():
    with pytest.raises(AceSafetyError):
        SafetyPolicy().assert_allowed(
            device(), SafetyContext("select_tool", False, "fluidd-card", "standby")
        )


def test_ace2_is_always_read_only():
    with pytest.raises(AceCapabilityError):
        SafetyPolicy().assert_allowed(
            device(model="ace2"), SafetyContext("select_tool", True, "gcode", "printing")
        )


def test_internal_runout_change_is_allowed_while_paused():
    SafetyPolicy().assert_allowed(
        device(), SafetyContext("select_tool", True, "runout", "paused")
    )


def test_manual_change_remains_blocked_while_paused():
    with pytest.raises(AceSafetyError):
        SafetyPolicy().assert_allowed(
            device(), SafetyContext("select_tool", True, "gcode", "paused")
        )


@pytest.mark.parametrize("action", ["feed", "retract"])
def test_manual_motion_is_blocked_while_printing(action):
    with pytest.raises(AceSafetyError, match="blocked while printing"):
        SafetyPolicy().assert_allowed(
            device(capabilities={action}),
            SafetyContext(action, True, "gcode", "printing"),
        )


@pytest.mark.parametrize("state", ["paused", "error", "cancelled", "unknown"])
def test_stopping_dryer_is_allowed_in_non_idle_states(state):
    SafetyPolicy().assert_allowed(
        device(capabilities={"stop_drying"}),
        SafetyContext("stop_drying", True, "moonraker", state),
    )


def test_printing_gcode_toolchange_remains_allowed():
    SafetyPolicy().assert_allowed(
        device(), SafetyContext("select_tool", True, "gcode", "printing")
    )


def test_printing_gcode_feed_assist_requires_explicit_confirmation():
    target = device(capabilities={"enable_feed_assist"})
    with pytest.raises(AceSafetyError, match="explicit confirmation"):
        SafetyPolicy().assert_allowed(
            target,
            SafetyContext("enable_feed_assist", False, "gcode", "printing"),
        )
    SafetyPolicy().assert_allowed(
        target,
        SafetyContext("enable_feed_assist", True, "gcode", "printing"),
    )


def test_unknown_print_state_fails_closed():
    with pytest.raises(AceSafetyError, match="not safe"):
        SafetyPolicy().assert_allowed(
            device(), SafetyContext("select_tool", True, "gcode", "unknown")
        )
