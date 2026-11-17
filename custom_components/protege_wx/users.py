"""User PINs for arming and disarming from Home Assistant.

PINs are checked by Home Assistant (the controller's own keypad users are
separate). Only a salted PBKDF2 hash of each PIN is stored in the config entry.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    OPT_CODE_ARM_REQUIRED,
    OPT_PANEL_CODE,
    OPT_USERS,
    USER_CAN_ARM,
    USER_CAN_DISARM,
    USER_CODE_HASH,
    USER_DAYS,
    USER_ENABLED,
    USER_EXPIRES,
    USER_FROM,
    USER_NAME,
    USER_SALT,
    USER_UNTIL,
    WEEKDAYS,
)

_ITERATIONS = 100_000


def hash_code(code: str, salt: str | None = None) -> tuple[str, str]:
    """Return (hash, salt) for a PIN."""
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", code.encode(), bytes.fromhex(salt), _ITERATIONS)
    return digest.hex(), salt


def make_user(name: str, code: str, can_arm: bool = True, can_disarm: bool = True) -> dict[str, Any]:
    code_hash, salt = hash_code(code)
    return {
        USER_NAME: name.strip(),
        USER_CODE_HASH: code_hash,
        USER_SALT: salt,
        USER_CAN_ARM: can_arm,
        USER_CAN_DISARM: can_disarm,
    }


def _parse_time(value: Any) -> time | None:
    if not value:
        return None
    try:
        return time.fromisoformat(str(value))
    except ValueError:
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def access_problem(user: dict[str, Any], now: datetime | None = None) -> str | None:
    """Why this user's PIN doesn't work right now, or None if it does.

    Returns "user_disabled", "user_expired" or "outside_schedule".
    """
    if not user.get(USER_ENABLED, True):
        return "user_disabled"
    now = now or dt_util.now()
    expires = _parse_date(user.get(USER_EXPIRES))
    if expires and now.date() > expires:
        return "user_expired"
    start, end = _parse_time(user.get(USER_FROM)), _parse_time(user.get(USER_UNTIL))
    days = [d for d in user.get(USER_DAYS) or [] if d in WEEKDAYS]
    if not days and not start and not end:
        return None
    clock = now.time().replace(tzinfo=None)
    day = WEEKDAYS[now.weekday()]
    if start and end and end <= start:  # overnight, e.g. 22:00-06:00
        if clock >= start:
            in_hours, schedule_day = True, day
        elif clock < end:
            in_hours, schedule_day = True, WEEKDAYS[(now.weekday() - 1) % 7]  # started yesterday
        else:
            in_hours, schedule_day = False, day
    else:
        in_hours = (not start or clock >= start) and (not end or clock < end)
        schedule_day = day
    if not in_hours or (days and schedule_day not in days):
        return "outside_schedule"
    return None


def describe_schedule(user: dict[str, Any]) -> str | None:
    """A short description such as "mon, tue 08:00-17:00 until 2026-12-31"."""
    parts = []
    days = [d for d in user.get(USER_DAYS) or [] if d in WEEKDAYS]
    if days and len(days) < 7:
        parts.append(", ".join(days))
    start, end = _parse_time(user.get(USER_FROM)), _parse_time(user.get(USER_UNTIL))
    if start or end:
        parts.append(f"{start.strftime('%H:%M') if start else '00:00'}-{end.strftime('%H:%M') if end else '24:00'}")
    if user.get(USER_EXPIRES):
        parts.append(f"until {user[USER_EXPIRES]}")
    if not user.get(USER_ENABLED, True):
        parts.append("disabled")
    return " ".join(parts) or None


@dataclass(frozen=True)
class CodeCheck:
    """Outcome of checking a code for an action."""

    allowed: bool
    user: str | None = None
    # "no_code", "invalid_code", "not_permitted", "user_disabled", "user_expired",
    # "outside_schedule"
    reason: str | None = None


class UserCodes:
    """The configured users, and code checks against them."""

    def __init__(self, options: dict[str, Any]) -> None:
        self.users: list[dict[str, Any]] = list(options.get(OPT_USERS, []))
        # A v0.1 single panel code, compared directly (no hashing in the event
        # loop); the options flow converts it to a hashed user when saved.
        self._legacy = (options.get(OPT_PANEL_CODE) or "").strip() if not self.users else ""
        self.arm_requires_code = bool(options.get(OPT_CODE_ARM_REQUIRED, True))

    @property
    def enabled(self) -> bool:
        return bool(self.users) or bool(self._legacy)

    def _match(self, code: str) -> dict[str, Any] | None:
        if self._legacy:
            if hmac.compare_digest(code.encode(), self._legacy.encode()):
                return {USER_NAME: "Panel code", USER_CAN_ARM: True, USER_CAN_DISARM: True}
            return None
        for user in self.users:
            digest, _ = hash_code(code, user[USER_SALT])
            if hmac.compare_digest(digest, user[USER_CODE_HASH]):
                return user
        return None

    def check(self, code: str | None, action: str, now: datetime | None = None) -> CodeCheck:
        """Check ``code`` for ``action`` ("arm" or "disarm")."""
        if not self.enabled:
            return CodeCheck(True)
        if action == "arm" and not self.arm_requires_code and not code:
            return CodeCheck(True)
        if not code:
            return CodeCheck(False, reason="no_code")
        user = self._match(code.strip())
        if user is None:
            return CodeCheck(False, reason="invalid_code")
        permitted = user.get(USER_CAN_ARM if action == "arm" else USER_CAN_DISARM, True)
        if not permitted:
            return CodeCheck(False, user[USER_NAME], reason="not_permitted")
        if problem := access_problem(user, now):
            return CodeCheck(False, user[USER_NAME], reason=problem)
        return CodeCheck(True, user[USER_NAME])
