"""User PINs for arming and disarming from Home Assistant.

PINs are checked by Home Assistant (the controller's own keypad users are
separate). Only a salted PBKDF2 hash of each PIN is stored in the config entry.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any

from .const import (
    OPT_CODE_ARM_REQUIRED,
    OPT_PANEL_CODE,
    OPT_USERS,
    USER_CAN_ARM,
    USER_CAN_DISARM,
    USER_CODE_HASH,
    USER_NAME,
    USER_SALT,
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


@dataclass(frozen=True)
class CodeCheck:
    """Outcome of checking a code for an action."""

    allowed: bool
    user: str | None = None
    reason: str | None = None  # "no_code", "invalid_code", "not_permitted"


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

    def check(self, code: str | None, action: str) -> CodeCheck:
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
        return CodeCheck(True, user[USER_NAME])
