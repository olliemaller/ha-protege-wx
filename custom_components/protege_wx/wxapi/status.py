"""Decoders for Protege WX live-status replies.

A status reply looks like ``Area0=128,0,5,0&Area16=128,0,0,0``: one
``{Type}{RecId}={codes}`` pair per record, plus a sentinel record 2147483647
that is never real. The code meanings come from the controller's web UI.

Unknown or unparseable codes decode to ``None`` (unknown) rather than to a
"safe-looking" state such as disarmed, locked or closed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

NO_RECORD = 2147483647

AREA_STATE = {
    0: "disarmed", 1: "zone_open", 2: "trouble", 3: "bypass_error",
    4: "bypass_warning", 5: "user_count_not_zero", 128: "armed",
    129: "exit_delay", 130: "entry_delay", 131: "disarm_delay", 132: "code_delay",
}
# Disarmed, but the panel is waiting for something before it can arm.
AREA_NOT_READY = frozenset({1, 2, 3, 4, 5})
AREA_FLAGS = {
    0: "alarm_activated", 1: "siren_activated", 2: "alarms_in_memory",
    3: "remote_armed", 4: "force_armed", 5: "instant_armed", 6: "partial_armed",
}

DOOR_LOCK = {
    0: "locked", 1: "unlocked_by_user", 2: "unlocked_by_schedule",
    3: "unlocked_by_user_timed", 4: "unlocked_by_user_latched",
    5: "unlocked_by_exit_device", 6: "unlocked_by_entry_device",
    7: "unlocked_by_operator", 8: "unlocked_by_operator_timed",
    9: "unlocked_by_operator_latched", 10: "unlocked_by_area",
    11: "unlocked_by_fire_alarm", 12: "locked_by_calendar",
    13: "unlocked_by_calendar", 18: "locked_extended",
    19: "lockdown_entry_allowed", 20: "lockdown_entry_exit_allowed",
    21: "lockdown_exit_allowed", 22: "lockdown_denied",
    23: "not_locked", 24: "not_locked", 255: "unknown",
}
DOOR_LOCKED_CODES = frozenset({0, 12, 18, 19, 20, 21, 22})
DOOR_LATCHED_CODES = frozenset({4, 9})
DOOR_POSITION = {
    0: "closed", 1: "open", 2: "open_alert", 3: "left_open",
    4: "forced_open", 5: "bonding_fault", 255: "unknown",
}

INPUT_STATE = {0: "closed", 1: "open", 2: "tamper", 3: "short"}
INPUT_FLAGS = {0: "bypassed", 1: "bypass_latched", 2: "siren_lockout"}

OUTPUT_STATE = {0: "off", 1: "on", 2: "pulse_on", 3: "on_timed", 4: "on_pulse_timed"}

_KEY = re.compile(r"^(\D+)(\d+)$")


def _ints(csv: str, count: int) -> list[int | None]:
    values: list[int | None] = []
    for part in csv.split(","):
        try:
            values.append(int(part.strip()))
        except ValueError:
            values.append(None)
    values += [None] * (count - len(values))
    return values


def _flags(code: int | None, names: dict[int, str]) -> frozenset[str]:
    if not code:
        return frozenset()
    return frozenset(name for bit, name in names.items() if code & (1 << bit))


def split_records(raw: str) -> dict[int, str]:
    """Split a status reply into {record id: csv codes}, dropping the sentinel."""
    out: dict[int, str] = {}
    for part in raw.strip().split("&"):
        if "=" not in part:
            continue
        key, csv = part.split("=", 1)
        match = _KEY.match(key.strip())
        if not match:
            continue
        rec_id = int(match.group(2))
        if rec_id != NO_RECORD:
            out[rec_id] = csv
    return out


@dataclass(frozen=True)
class AreaStatus:
    """Live state of an area."""

    state_code: int | None
    flags_code: int | None
    raw: str
    flags: frozenset[str] = field(default_factory=frozenset)

    @property
    def known(self) -> bool:
        # Garbage flags could hide an alarm, so they make the area unknown too.
        return self.state_code in AREA_STATE and self.flags_code is not None

    @property
    def state(self) -> str:
        return AREA_STATE.get(self.state_code, f"unknown_{self.state_code}")

    @property
    def not_ready(self) -> bool:
        """Disarmed, but waiting (zone open, bypass error...)."""
        return self.state_code in AREA_NOT_READY

    @property
    def is_armed_or_arming(self) -> bool:
        return self.state_code in (128, 129, 130)

    @property
    def in_alarm(self) -> bool:
        """An alarm is happening now.

        ``alarm_activated`` stays set after an alarm (it's latched until the
        memory is cleared), so on its own it only counts while the area is
        armed or in entry delay. A sounding siren always counts.
        """
        if "siren_activated" in self.flags:
            return True
        return "alarm_activated" in self.flags and self.state_code in (128, 130)


@dataclass(frozen=True)
class DoorStatus:
    """Live state of a door."""

    lock_code: int | None
    position_code: int | None

    @property
    def lock(self) -> str:
        return DOOR_LOCK.get(self.lock_code, f"unknown_{self.lock_code}")

    @property
    def position(self) -> str:
        return DOOR_POSITION.get(self.position_code, f"unknown_{self.position_code}")

    @property
    def is_locked(self) -> bool | None:
        if self.lock_code not in DOOR_LOCK or self.lock_code == 255:
            return None
        return self.lock_code in DOOR_LOCKED_CODES

    @property
    def is_latched(self) -> bool | None:
        if self.lock_code not in DOOR_LOCK or self.lock_code == 255:
            return None
        return self.lock_code in DOOR_LATCHED_CODES

    @property
    def is_open(self) -> bool | None:
        if self.position_code not in DOOR_POSITION or self.position_code == 255:
            return None
        return self.position_code != 0


@dataclass(frozen=True)
class InputStatus:
    """Live state of an input (zone) or trouble input."""

    state_code: int | None
    flags_code: int | None
    flags: frozenset[str] = field(default_factory=frozenset)

    @property
    def known(self) -> bool:
        return self.state_code in INPUT_STATE

    @property
    def state(self) -> str:
        return INPUT_STATE.get(self.state_code, f"unknown_{self.state_code}")

    @property
    def is_open(self) -> bool | None:
        """Open (or tampered/shorted, which can't prove the zone is closed).

        ``None`` when the state is unknown, never a reassuring "closed".
        """
        if not self.known:
            return None
        return self.state_code != 0

    @property
    def is_tampered(self) -> bool | None:
        if not self.known:
            return None
        return self.state_code in (2, 3)

    @property
    def bypass(self) -> str:
        if "bypass_latched" in self.flags:
            return "permanent"
        if "bypassed" in self.flags:
            return "temporary"
        return "none"


@dataclass(frozen=True)
class OutputStatus:
    """Live state of an output (PGM)."""

    state_code: int | None

    @property
    def state(self) -> str:
        return OUTPUT_STATE.get(self.state_code, f"unknown_{self.state_code}")

    @property
    def is_on(self) -> bool | None:
        if self.state_code not in OUTPUT_STATE:
            return None
        return self.state_code != 0


def parse_areas(raw: str) -> dict[int, AreaStatus]:
    out = {}
    for rec_id, csv in split_records(raw).items():
        _, state, flags = _ints(csv, 3)[:3]
        out[rec_id] = AreaStatus(state, flags, csv, _flags(flags, AREA_FLAGS))
    return out


def parse_doors(raw: str) -> dict[int, DoorStatus]:
    out = {}
    for rec_id, csv in split_records(raw).items():
        lock, position = _ints(csv, 2)[:2]
        out[rec_id] = DoorStatus(lock, position)
    return out


def parse_inputs(raw: str) -> dict[int, InputStatus]:
    out = {}
    for rec_id, csv in split_records(raw).items():
        state, flags = _ints(csv, 2)[:2]
        out[rec_id] = InputStatus(state, flags, _flags(flags, INPUT_FLAGS))
    return out


def parse_outputs(raw: str) -> dict[int, OutputStatus]:
    return {
        rec_id: OutputStatus(_ints(csv, 1)[0])
        for rec_id, csv in split_records(raw).items()
    }
