"""Plain-English descriptions of controller events, for the logbook.

``describe()`` turns a parsed event-log line into the ``(name, message)`` pair
the logbook shows as "<name> <message>", for example::

    Alarm          armed (home) by Home Assistant
    Front Door     access granted to Mark Maller (PIN)
    Alarm          failed to arm: Living and Kitchen open
    Gate           unlocked by Front Door
    Mains Failure  trouble started

Zone (input) events and unrecognised lines return ``None``: zone sensors
already log every open and close, and raw lines would only add noise.
"""
from __future__ import annotations

from .wxapi.events import (
    KIND_ACCESS,
    KIND_AREA,
    KIND_DOOR,
    KIND_SYSTEM,
    KIND_TROUBLE,
    ParsedEvent,
)

# Home Assistant's names for the controller's arming modes.
MODE_LABELS = {"away": "away", "stay": "home", "instant": "night"}
METHOD_LABELS = {"pin": "PIN", "card": "card", "card_and_pin": "card and PIN"}
CONTROLLER_NAME = "Protege WX"


def join_names(names: list[str]) -> str:
    """'A', 'A and B', 'A, B and C'."""
    names = [n for n in names if n]
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def actor(by: str | None) -> str | None:
    """Who did it, tidied: 'Door Front Door' becomes 'Front Door'."""
    if not by:
        return None
    if by.startswith("Door "):
        return by[5:].strip() or None
    return by


def _by(by: str | None) -> str:
    who = actor(by)
    return f" by {who}" if who else ""


def describe(
    parsed: ParsedEvent, zones: list[str] | None = None, by: str | None = None
) -> tuple[str, str] | None:
    """Return ``(name, message)`` for the logbook, or ``None`` to skip.

    ``zones`` are the zones behind a failed arm; ``by`` overrides who did it
    (for example to name the Home Assistant user behind the integration).
    """
    who = by if by is not None else parsed.by
    kind, kind_type, subject = parsed.kind, parsed.event_type, parsed.subject

    if kind == KIND_AREA:
        name = subject or CONTROLLER_NAME
        mode = MODE_LABELS.get(parsed.mode or "", parsed.mode or "")
        mode_text = f" ({mode})" if mode else ""
        if kind_type == "armed":
            return name, f"armed{mode_text}{_by(who)}"
        if kind_type == "arming_started":
            return name, f"started arming{mode_text}{_by(who)}"
        if kind_type == "arming_cancelled":
            return name, f"arming cancelled{_by(who)}"
        if kind_type == "disarmed":
            return name, f"disarmed{_by(who)}"
        if kind_type == "failed_to_arm":
            if zones:
                verb = "is" if len(zones) == 1 else "are"
                return name, f"failed to arm{_by(who)}: {join_names(zones)} {verb} open"
            return name, f"failed to arm{_by(who)}"
        if kind_type == "alarm":
            return name, "alarm activated"
        return name, _fallback(parsed)

    if kind == KIND_ACCESS:
        name = subject or CONTROLLER_NAME
        method = METHOD_LABELS.get(parsed.method or "", parsed.method)
        method_text = f" ({method})" if method else ""
        person = parsed.user or actor(who)
        if kind_type == "access_granted":
            return name, f"access granted to {person or 'someone'}{method_text}"
        return name, f"access denied{(' to ' + person) if person else ''}{method_text}"

    if kind == KIND_DOOR:
        name = subject or CONTROLLER_NAME
        messages = {
            "unlocked": f"unlocked{_by(who)}",
            "locked": f"locked{_by(who)}",
            "opened": "opened",
            "closed": "closed",
            "forced_open": "was forced open",
            "left_open": "was left open",
        }
        return name, messages.get(kind_type) or _fallback(parsed)

    if kind == KIND_TROUBLE:
        name = subject or CONTROLLER_NAME
        if kind_type == "trouble":
            return name, "trouble started"
        if kind_type == "trouble_restored":
            return name, "trouble cleared"
        return name, _fallback(parsed)

    if kind == KIND_SYSTEM and kind_type == "power_up":
        return CONTROLLER_NAME, "powered up"

    # Inputs are logged by their own sensors. Anything unrecognised (operator
    # logins, or areas, doors and inputs added after setup) is left out rather
    # than flooding the logbook with raw lines; it's still on the event bus.
    return None


def _fallback(parsed: ParsedEvent) -> str:
    action = parsed.extra.get("action") if parsed.extra else None
    return f"logged: {action or parsed.event.text}"
