"""Central physical-action policy for the shared filament path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Optional, Set

from .errors import (
    AceCapabilityError,
    AceDeviceOfflineError,
    AceSafetyError,
)


PHYSICAL_ACTIONS: Set[str] = {
    "select_tool",
    "unload",
    "feed",
    "retract",
    "start_drying",
    "stop_drying",
    "enable_feed_assist",
    "disable_feed_assist",
    "calibrate",
}

CONFIRMATION_ACTIONS: Set[str] = {
    "select_tool",
    "unload",
    "feed",
    "retract",
    "calibrate",
    "enable_feed_assist",
}

IDLE_PRINT_STATES: Set[str] = {"idle", "standby", "ready", "complete", "completed"}
RISK_REDUCING_ACTIONS: Set[str] = {"stop_drying", "disable_feed_assist"}


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


@dataclass(frozen=True)
class SafetyContext:
    action: str
    confirmed: bool = False
    source: str = "gcode"
    print_state: str = "standby"


class SafetyPolicy:
    """Validate an action without guessing printer-specific behavior."""

    def __init__(
        self,
        *,
        require_confirmation: bool = True,
        blocked_print_states: Optional[Iterable[str]] = None,
    ) -> None:
        self.require_confirmation = require_confirmation
        self.blocked_print_states = {
            str(state).lower()
            for state in (blocked_print_states or ("paused", "error", "cancelled"))
        }

    def assert_allowed(self, device: Any, context: SafetyContext) -> None:
        action = context.action
        if action not in PHYSICAL_ACTIONS:
            return

        model = str(_read(device, "model", "unknown")).lower()
        if model == "ace2":
            raise AceCapabilityError(
                "ACE2 is read-only until its physical protocol is validated",
                details={"model": model, "action": action},
            )

        if not bool(_read(device, "physical_actions_enabled", False)):
            raise AceSafetyError(
                "Physical actions are disabled for this ACE device",
                details={"action": action},
            )

        if not bool(_read(device, "connected", False)):
            raise AceDeviceOfflineError(
                "The selected ACE device is offline",
                retryable=True,
                details={"action": action},
            )

        capabilities = _read(device, "capabilities", set())
        if isinstance(capabilities, dict):
            aliases = {
                "select_tool": ("select_tool", "change_tool", "physical_actions"),
                "unload": ("unload", "retract", "physical_actions"),
                "start_drying": ("start_drying", "dryer", "drying"),
                "stop_drying": ("stop_drying", "dryer", "drying"),
                "enable_feed_assist": ("enable_feed_assist", "feed_assist"),
                "disable_feed_assist": ("disable_feed_assist", "feed_assist"),
            }
            supported = any(bool(capabilities.get(name, False)) for name in aliases.get(action, (action,)))
        else:
            names = set(capabilities or ())
            aliases = {
                "select_tool": {"select_tool", "change_tool", "physical_actions"},
                "unload": {"unload", "retract", "physical_actions"},
                "start_drying": {"start_drying", "dryer", "drying"},
                "stop_drying": {"stop_drying", "dryer", "drying"},
                "enable_feed_assist": {"enable_feed_assist", "feed_assist"},
                "disable_feed_assist": {"disable_feed_assist", "feed_assist"},
            }
            supported = bool(names.intersection(aliases.get(action, {action})))
        if capabilities and not supported:
            raise AceCapabilityError(
                "The selected ACE device does not support this action",
                details={"action": action},
            )

        state = str(context.print_state or "unknown").lower()
        confirmation_source = context.source in {
            "fluidd-card",
            "dashboard",
            "moonraker",
        }
        printing_feed_assist = action == "enable_feed_assist" and state == "printing"
        if (
            self.require_confirmation
            and action in CONFIRMATION_ACTIONS
            and (confirmation_source or printing_feed_assist)
            and not context.confirmed
        ):
            raise AceSafetyError(
                "This action requires explicit confirmation",
                details={"action": action},
            )

        if action in RISK_REDUCING_ACTIONS:
            return
        if context.source == "runout" and state == "paused" and action in {
            "select_tool",
            "unload",
        }:
            return
        if state in self.blocked_print_states:
            raise AceSafetyError(
                "The printer state blocks this physical action",
                details={"action": action, "print_state": state},
            )
        if state == "printing":
            if action in {"start_drying", "enable_feed_assist"}:
                return
            if context.source == "gcode" and action in {"select_tool", "unload"}:
                return
            raise AceSafetyError(
                "Manual ACE motion is blocked while printing",
                details={"action": action, "print_state": state, "source": context.source},
            )
        if state not in IDLE_PRINT_STATES:
            raise AceSafetyError(
                "The printer state is not safe for this physical action",
                details={"action": action, "print_state": state},
            )
