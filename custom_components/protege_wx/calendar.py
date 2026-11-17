"""Alarm history calendar: when each area was armed, by whom, and any alarms.

Each armed period is one calendar entry, from arming to disarming, titled with
the mode and who armed it ("Alarm armed away by Jane"). Alarms and failures to
arm are short entries of their own. The last 500 entries are kept across
restarts, so the calendar view answers "who armed it last night?".
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .const import DOMAIN
from .coordinator import ProtegeCoordinator
from .entity import ProtegeEntity
from .wxapi.events import KIND_AREA, KIND_EMERGENCY, ParsedEvent

PARALLEL_UPDATES = 0
MAX_ENTRIES = 500
STORAGE_VERSION = 1
# A short entry (alarm, failure to arm) shows as this long.
_MARK = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    calendar = ProtegeAlarmHistory(entry.runtime_data.coordinator)
    await calendar.async_load()
    async_add_entities([calendar])


def _when(parsed: ParsedEvent) -> datetime:
    """Controller times are local wall-clock time."""
    if parsed.event.time is None:
        return dt_util.now()
    return parsed.event.time.replace(tzinfo=dt_util.get_default_time_zone())


class ProtegeAlarmHistory(ProtegeEntity, CalendarEntity):
    """Arm/disarm periods and alarms for every area, as a calendar."""

    _attr_translation_key = "alarm_history"

    def __init__(self, coordinator: ProtegeCoordinator) -> None:
        super().__init__(coordinator, "controller", 0, key="alarm_history")
        self._store: Store[dict[str, Any]] = Store(
            coordinator.hass, STORAGE_VERSION,
            f"{DOMAIN}.{coordinator.config_entry.entry_id}.alarm_history",
        )
        # Finished entries: {"start", "end", "summary", "description", "area"}
        self._entries: list[dict[str, Any]] = []
        # Open armed periods per area: {"start", "summary", "description", "area"}
        self._open: dict[str, dict[str, Any]] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        self._entries = list(data.get("entries", []))[-MAX_ENTRIES:]
        self._open = dict(data.get("open", {}))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_event_listener(self._on_event))

    @property
    def available(self) -> bool:
        return True  # history is still worth reading while the controller is away

    def _save(self) -> None:
        self._entries = self._entries[-MAX_ENTRIES:]
        self._store.async_delay_save(lambda: {"entries": self._entries, "open": self._open}, 5)

    @callback
    def _on_event(self, parsed: ParsedEvent) -> None:
        if parsed.kind not in (KIND_AREA, KIND_EMERGENCY):
            return
        area = parsed.subject or "Controller"
        when = _when(parsed).isoformat()
        who = self.coordinator.actor_name(parsed)
        by = f" by {who}" if who else ""
        kind = parsed.event_type
        if parsed.kind == KIND_AREA and kind == "armed":
            self._open[area] = {
                "start": when,
                "summary": f"{area} armed {parsed.mode or 'away'}{by}",
                "description": parsed.event.text,
                "area": area,
            }
        elif parsed.kind == KIND_AREA and kind == "disarmed":
            started = self._open.pop(area, None)
            if started is not None:
                self._entries.append(
                    {**started, "end": when, "description": f"{started['description']}\n{parsed.event.text}"}
                )
        elif kind in ("alarm", "failed_to_arm") or parsed.kind == KIND_EMERGENCY:
            label = {"alarm": "Alarm", "failed_to_arm": "Failed to arm"}.get(kind, kind.capitalize())
            self._entries.append(
                {
                    "start": when,
                    "end": (_when(parsed) + _MARK).isoformat(),
                    "summary": f"{label}: {area}{by}",
                    "description": parsed.event.text,
                    "area": area,
                }
            )
        else:
            return
        self._save()
        self.async_write_ha_state()

    def _all(self) -> list[CalendarEvent]:
        now = dt_util.now()
        events = []
        for item in self._entries:
            start, end = dt_util.parse_datetime(item["start"]), dt_util.parse_datetime(item["end"])
            if start and end:
                events.append(
                    CalendarEvent(start=start, end=max(end, start + timedelta(seconds=1)),
                                  summary=item["summary"], description=item.get("description"),
                                  location=item.get("area"))
                )
        for item in self._open.values():  # still armed: runs until now
            start = dt_util.parse_datetime(item["start"])
            if start:
                events.append(
                    CalendarEvent(start=start, end=max(now + _MARK, start + timedelta(seconds=1)),
                                  summary=item["summary"], description=item.get("description"),
                                  location=item.get("area"))
                )
        return sorted(events, key=lambda e: e.start)

    @property
    def event(self) -> CalendarEvent | None:
        """The most recent entry (the current armed period, if any)."""
        events = self._all()
        return events[-1] if events else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        return [e for e in self._all() if e.end > start_date and e.start < end_date]
