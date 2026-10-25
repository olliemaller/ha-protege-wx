"""Parsing of the Protege WX event log.

Each event is a line such as::

    Sun 25/10/2026 19:21:35 Area Alarm Stay Arming Started By Home Assistant
    Sun 25/10/2026 19:21:06 Input Living Opened
    Sun 25/10/2026 19:21:06 Area Alarm Failure To ARM By Home Assistant
    Sun 25/10/2026 15:34:50 User Jane Citizen Entry Granted Front Door Using User By Pin
    Sun 25/10/2026 15:34:50 Door Gate Unlocked By Door Front Door
    Sun 25/10/2026 18:38:56 Trouble Input System Restarted Opened

Names can contain spaces, so lines are matched against the names the
integration already knows (areas, doors, inputs, trouble inputs) instead of
splitting on words. Anything unrecognised is kept as ``other`` with its text.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

_DATE_FORMATS = ("%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S")
_STAMP = re.compile(r"^(?:[A-Za-z]{3}\s+)?(\S+\s+\d{1,2}:\d{2}:\d{2})\s+(.*)$")
_NOISE_PREFIXES = ("Output ", "Report In ", "Module ")

# Event kinds
KIND_AREA = "area"
KIND_DOOR = "door"
KIND_ACCESS = "access"
KIND_INPUT = "input"
KIND_TROUBLE = "trouble"
KIND_SYSTEM = "system"
KIND_NOISE = "noise"
KIND_EMERGENCY = "emergency"

AREA_EVENT_TYPES = (
    "armed", "arming_started", "arming_cancelled", "failed_to_arm",
    "disarmed", "alarm", "other",
)
DOOR_EVENT_TYPES = (
    "access_granted", "access_denied", "unlocked", "locked",
    "opened", "closed", "forced_open", "left_open", "other",
)
CONTROLLER_EVENT_TYPES = (
    "trouble", "trouble_restored", "power_up", "duress", "panic", "medical", "other",
)
EMERGENCY_TYPES = ("duress", "panic", "medical")
# Words the controller uses for user-raised emergencies. Matched as whole
# words so names like "Panic Room" in an unrelated line are unlikely to trip it.
_EMERGENCY = re.compile(r"\b(duress|panic|medical|hold[ -]?up)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ProtegeEvent:
    """One line of the event log."""

    time: datetime | None
    text: str

    @property
    def key(self) -> tuple[str, str]:
        """Identity used to recognise an event already seen."""
        return (self.time.isoformat() if self.time else "", self.text)

    @property
    def is_noise(self) -> bool:
        """Keypad LEDs/beepers, monitoring reports and module housekeeping."""
        return self.text.startswith(_NOISE_PREFIXES)


@dataclass(frozen=True)
class ParsedEvent:
    """What an event means, as far as it can be worked out."""

    event: ProtegeEvent
    kind: str
    subject: str | None = None  # area, door, input or trouble-input name
    event_type: str = "other"
    by: str | None = None  # "Home Assistant", a user name, "Door Front Door"...
    mode: str | None = None  # away / stay / instant for arming events
    user: str | None = None
    method: str | None = None
    extra: dict = field(default_factory=dict)


def parse_line(line: str) -> ProtegeEvent:
    """Split the timestamp off one event line."""
    line = line.strip()
    match = _STAMP.match(line)
    if match:
        for fmt in _DATE_FORMATS:
            try:
                return ProtegeEvent(datetime.strptime(match.group(1), fmt), match.group(2).strip())
            except ValueError:
                continue
    return ProtegeEvent(None, line)


def parse_event_reply(reply: str) -> list[ProtegeEvent]:
    """Parse an ``Event0=...&EventCodes0=...`` reply, oldest first."""
    items: list[tuple[int, ProtegeEvent]] = []
    for part in reply.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.startswith("Event") and key[5:].isdigit() and value.strip():
            items.append((int(key[5:]), parse_line(value)))
    return sort_events(event for _, event in items)


def sort_events(events: Iterable[ProtegeEvent]) -> list[ProtegeEvent]:
    """Order by timestamp (pages can arrive out of order), keeping log order for ties."""
    indexed = list(enumerate(events))
    indexed.sort(key=lambda item: (item[1].time or datetime.min, item[0]))
    return [event for _, event in indexed]


def _match_name(text: str, names: Iterable[str]) -> tuple[str, str] | None:
    """Return (name, rest) for the longest known name that starts ``text``."""
    best: tuple[str, str] | None = None
    for name in names:
        if name and text.startswith(name + " ") and (best is None or len(name) > len(best[0])):
            best = (name, text[len(name) + 1:])
    if best is None:
        for name in names:
            if name and text == name:
                return (name, "")
    return best


def _split_by(rest: str) -> tuple[str, str | None]:
    if " By " in rest:
        action, by = rest.split(" By ", 1)
        return action.strip(), by.strip() or None
    return rest.strip(), None


def _clean_user(by: str | None) -> str | None:
    if by and by.startswith("User "):
        return by[5:].strip() or None
    return by


def _arming_mode(action: str) -> str:
    lowered = action.lower()
    if "stay" in lowered:
        return "stay"
    if "instant" in lowered:
        return "instant"
    return "away"


def _area_type(action: str) -> str:
    lowered = action.lower()
    if "failure to arm" in lowered or "fail to arm" in lowered:
        return "failed_to_arm"
    if "cancel" in lowered:
        return "arming_cancelled"
    if "arming started" in lowered or lowered.endswith("arming"):
        return "arming_started"
    if "disarm" in lowered:
        return "disarmed"
    if lowered.endswith("armed"):
        return "armed"
    if "alarm" in lowered or "siren" in lowered:
        return "alarm"
    return "other"


def _door_type(action: str) -> str:
    lowered = action.lower()
    for needle, event_type in (
        ("forced", "forced_open"),
        ("left open", "left_open"),
        ("unlock", "unlocked"),
        ("lock", "locked"),
        ("open", "opened"),
        ("close", "closed"),
    ):
        if needle in lowered:
            return event_type
    return "other"


_ACCESS = re.compile(
    r"^User (?P<rest>.+?) (?P<direction>Entry|Exit|Access) (?P<result>Granted|Denied) (?P<tail>.+)$"
)


class EventParser:
    """Turns event lines into ``ParsedEvent``s using the site's known names."""

    def __init__(
        self,
        areas: Iterable[str],
        doors: Iterable[str],
        inputs: Iterable[str],
        troubles: Iterable[str],
    ) -> None:
        self.areas = [name for name in areas if name]
        self.doors = [name for name in doors if name]
        self.inputs = [name for name in inputs if name]
        self.troubles = [name for name in troubles if name]

    def parse(self, event: ProtegeEvent) -> ParsedEvent:
        text = event.text
        if event.is_noise:
            return ParsedEvent(event, KIND_NOISE)

        emergency = _EMERGENCY.search(text)
        if emergency and not text.startswith(("Input ", "Door ", "Trouble Input ")):
            word = emergency.group(1).lower()
            event_type = "duress" if word == "duress" else "medical" if word == "medical" else "panic"
            area = None
            if text.startswith("Area "):
                found = _match_name(text[5:], self.areas)
                area = found[0] if found else None
            _, by = _split_by(text)
            if by is None and text.startswith("User "):
                by = text[5:emergency.start()].strip() or None
            return ParsedEvent(event, KIND_EMERGENCY, area, event_type, by=_clean_user(by))

        if text.startswith("Area "):
            found = _match_name(text[5:], self.areas)
            if found:
                name, rest = found
                action, by = _split_by(rest)
                event_type = _area_type(action)
                mode = _arming_mode(action) if event_type in ("armed", "arming_started") else None
                return ParsedEvent(
                    event, KIND_AREA, name, event_type, by=_clean_user(by), mode=mode,
                    extra={"action": action},
                )

        if text.startswith("Trouble Input "):
            found = _match_name(text[14:], self.troubles)
            if found:
                name, rest = found
                lowered = rest.lower()
                event_type = "trouble" if lowered.startswith("open") else (
                    "trouble_restored" if lowered.startswith("close") else "other"
                )
                return ParsedEvent(event, KIND_TROUBLE, name, event_type)

        if text.startswith("Input "):
            found = _match_name(text[6:], self.inputs)
            if found:
                name, rest = found
                return ParsedEvent(event, KIND_INPUT, name, rest.strip().lower() or "other")

        if text.startswith("Door "):
            found = _match_name(text[5:], self.doors)
            if found:
                name, rest = found
                action, by = _split_by(rest)
                return ParsedEvent(
                    event, KIND_DOOR, name, _door_type(action), by=_clean_user(by),
                    extra={"action": action},
                )

        access = _ACCESS.match(text)
        if access:
            user = access.group("rest").strip()
            tail = access.group("tail")
            method = None
            if " Using " in tail:
                tail, method = tail.split(" Using ", 1)
                method = method.strip()
            door = _match_name(tail.strip(), self.doors)
            door_name = door[0] if door else tail.strip()
            event_type = "access_granted" if access.group("result") == "Granted" else "access_denied"
            return ParsedEvent(
                event, KIND_ACCESS, door_name, event_type, by=user, user=user,
                method=_method(method), extra={"direction": access.group("direction").lower()},
            )

        if text.startswith("System Power Up"):
            return ParsedEvent(event, KIND_SYSTEM, None, "power_up")
        return ParsedEvent(event, KIND_SYSTEM, None, "other")


def _method(method: str | None) -> str | None:
    if not method:
        return None
    lowered = method.lower()
    if "pin" in lowered and "card" in lowered:
        return "card_and_pin"
    if "pin" in lowered:
        return "pin"
    if "card" in lowered or "credential" in lowered:
        return "card"
    return lowered.replace(" ", "_")
