"""Health tracking and Repairs issues for an ICT Protege WX config entry.

``EntryHealth`` lives in ``hass.data`` for the whole Home Assistant run, not on
the coordinator, so it keeps counting across setup retries: a controller that
is down when Home Assistant starts still gets its "unreachable" issue after
15 minutes, even though setup is retried with a new coordinator each time.

Issues are persistent, so they survive a restart; the first good poll (or the
entry being unloaded) clears any left over from before.
"""
from __future__ import annotations

import statistics
import time
from collections.abc import Iterable

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import (
    CLOCK_DRIFT_CLEAR,
    CLOCK_DRIFT_SECONDS,
    DOMAIN,
    EVENT_LOG_EMPTY_SECONDS,
    ISSUE_CLOCK,
    ISSUE_EMERGENCY,
    ISSUE_EVENT_LOG,
    ISSUE_LOW_VOLTAGE,
    ISSUE_UNREACHABLE,
    LOW_VOLTAGE,
    LOW_VOLTAGE_CLEAR,
    LOW_VOLTAGE_SECONDS,
    UNREACHABLE_ISSUE_SECONDS,
)

# Cleared automatically when the condition ends. ISSUE_EMERGENCY is not in
# this list: it stays until someone acknowledges it in Repairs.
ALL_ISSUES = (ISSUE_UNREACHABLE, ISSUE_LOW_VOLTAGE, ISSUE_EVENT_LOG, ISSUE_CLOCK)


def entry_health(hass: HomeAssistant, entry_id: str) -> EntryHealth:
    """The health tracker for an entry, kept across setup retries and reloads."""
    store: dict = hass.data.setdefault(DOMAIN, {})
    key = ("health", entry_id)
    if key not in store:
        store[key] = EntryHealth(hass, entry_id)
    return store[key]


class EntryHealth:
    """Tracks failures, supply voltage and event-log access; raises and clears issues."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.failing_since: float | None = None
        self._low_voltage_since: float | None = None
        self._events_empty_since: float | None = None
        # Raised in this run, with the placeholders last shown.
        self._raised: dict[str, dict[str, str]] = {}
        # May be left from a previous run until a poll shows they're over.
        self._stale: set[str] = set(ALL_ISSUES)

    # ── inputs ─────────────────────────────────────────────────────────────

    @callback
    def record_failure(self, host: str, now: float | None = None) -> None:
        """A poll (or a setup attempt) couldn't reach the controller."""
        now = time.monotonic() if now is None else now
        if self.failing_since is None:
            self.failing_since = now
        if now - self.failing_since >= UNREACHABLE_ISSUE_SECONDS:
            self._raise(
                ISSUE_UNREACHABLE,
                ir.IssueSeverity.ERROR,
                {"host": host, "minutes": str(UNREACHABLE_ISSUE_SECONDS // 60)},
            )

    @callback
    def record_success(self) -> None:
        self.failing_since = None
        self._clear(ISSUE_UNREACHABLE)

    @callback
    def check_voltage(self, volts: float | None, now: float) -> None:
        """``volts`` is a fresh reading, or None when there isn't one."""
        if volts is None:
            return
        if volts >= LOW_VOLTAGE_CLEAR:
            self._low_voltage_since = None
            self._clear(ISSUE_LOW_VOLTAGE)
            return
        placeholders = {"volts": f"{volts:.1f}", "threshold": f"{LOW_VOLTAGE:.1f}"}
        if volts >= LOW_VOLTAGE:
            # Between the thresholds: keep a raised issue up to date, but don't
            # let an old dip count towards a new one.
            if ISSUE_LOW_VOLTAGE in self._raised:
                self._raise(ISSUE_LOW_VOLTAGE, ir.IssueSeverity.WARNING, placeholders)
            else:
                self._low_voltage_since = None
            return
        if self._low_voltage_since is None:
            self._low_voltage_since = now
        if now - self._low_voltage_since >= LOW_VOLTAGE_SECONDS:
            self._raise(ISSUE_LOW_VOLTAGE, ir.IssueSeverity.WARNING, placeholders)

    @callback
    def check_event_log(self, page_empty: bool, operator: str, now: float) -> None:
        if not page_empty:
            self._events_empty_since = None
            self._clear(ISSUE_EVENT_LOG)
            return
        if self._events_empty_since is None:
            self._events_empty_since = now
        if now - self._events_empty_since >= EVENT_LOG_EMPTY_SECONDS:
            self._raise(ISSUE_EVENT_LOG, ir.IssueSeverity.WARNING, {"operator": operator})

    @callback
    def check_clock(self, drift: Iterable[float]) -> None:
        """``drift``: recent (controller - Home Assistant) clock differences, s."""
        samples = list(drift)
        if len(samples) < 3:
            return
        median = statistics.median(samples)
        if abs(median) < CLOCK_DRIFT_CLEAR:
            self._clear(ISSUE_CLOCK)
        elif abs(median) > CLOCK_DRIFT_SECONDS:
            self._raise(
                ISSUE_CLOCK,
                ir.IssueSeverity.WARNING,
                {
                    "minutes": str(round(abs(median) / 60)),
                    "direction": "ahead of" if median > 0 else "behind",
                },
            )

    @callback
    def raise_emergency(self, kind: str, area: str, by: str, text: str) -> None:
        """A duress, panic or medical alarm. Stays until acknowledged."""
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id(ISSUE_EMERGENCY),
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.CRITICAL,
            translation_key=ISSUE_EMERGENCY,
            translation_placeholders={
                "kind": kind, "area": area or "-", "by": by or "-", "text": text,
            },
            data={"entry_id": self.entry_id},
        )

    @callback
    def clear_all(self) -> None:
        """Remove every issue for this entry (on unload)."""
        for issue in ALL_ISSUES:
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id(issue))
        self._raised.clear()
        self._stale.clear()
        self.failing_since = None
        self._low_voltage_since = None
        self._events_empty_since = None

    # ── issue registry ─────────────────────────────────────────────────────

    def issue_id(self, issue: str) -> str:
        return f"{issue}_{self.entry_id}"

    def _raise(self, issue: str, severity: ir.IssueSeverity, placeholders: dict[str, str]) -> None:
        if self._raised.get(issue) == placeholders:
            return  # already showing exactly this
        self._raised[issue] = placeholders
        self._stale.discard(issue)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id(issue),
            is_fixable=False,
            is_persistent=True,
            severity=severity,
            translation_key=issue,
            translation_placeholders=placeholders,
        )

    def _clear(self, issue: str) -> None:
        if issue in self._raised or issue in self._stale:
            self._raised.pop(issue, None)
            self._stale.discard(issue)
            ir.async_delete_issue(self.hass, DOMAIN, self.issue_id(issue))
