"""Visitor unlock: hold a door unlocked for a set time, then lock it again.

The door is latched open on the controller and Home Assistant locks it when
the time is up. The controller's own timed unlock only lasts the door's
programmed unlock time (seconds), and the web interface has no unlock for a
chosen time, so the re-lock has to come from here. The end time is saved, so
a restart in between still locks the door (straight away, if the time ran out
while Home Assistant was down). Unloading or removing the entry locks the door
straight away; if that fails, the door stays saved and the next setup locks
it. After 3 failed re-locks in a row a Repairs issue says the door may still
be unlocked; it clears once the door locks.
Locking the door by any other means (a keypad, the app, a schedule) cancels
the visitor unlock, so it never re-locks a door someone else has since
unlocked on purpose.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, ISSUE_VISITOR_RELOCK, VISITOR_RELOCK_ATTEMPTS

if TYPE_CHECKING:
    from .coordinator import ProtegeCoordinator

_LOGGER = logging.getLogger(__name__)
_STORE_VERSION = 1


def visitor_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, _STORE_VERSION, f"{DOMAIN}.{entry_id}.visitor")


def _handover_store(hass: HomeAssistant, unique_id: str) -> Store[dict[str, Any]]:
    """Re-locks left by a removed entry, for the next entry on the same controller."""
    return Store(hass, _STORE_VERSION, f"{DOMAIN}.controller_{unique_id}.visitor")


async def async_hand_over_visitors(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """On removal: delete the entry's visitor store, passing any door that
    couldn't be locked to the next entry set up for the same controller."""
    store = visitor_store(hass, entry.entry_id)
    doors = (await store.async_load() or {}).get("doors")
    if doors and entry.unique_id:
        _LOGGER.warning(
            "Doors %s may still be unlocked after a visitor unlock; they will be locked "
            "when this controller is added again", ", ".join(doors)
        )
        await _handover_store(hass, entry.unique_id).async_save({"doors": doors})
    await store.async_remove()
    registry = ir.async_get(hass)
    prefix = f"{ISSUE_VISITOR_RELOCK}_{entry.entry_id}_"
    for domain, issue_id in list(registry.issues):
        if domain == DOMAIN and issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


class VisitorUnlocks:
    """The visitor unlocks running on one controller's doors."""

    def __init__(self, hass: HomeAssistant, coordinator: ProtegeCoordinator) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._store = visitor_store(hass, coordinator.config_entry.entry_id)
        self.until: dict[int, datetime] = {}
        self._timers: dict[int, CALLBACK_TYPE] = {}
        self._latched: dict[int, bool | None] = {}
        # Door -> number of the last poll started before the unlock command
        # finished. Door readings from that poll or earlier are stale.
        self._after: dict[int, int] = {}
        # Newest door reading handled, so an older poll finishing late can't
        # undo it.
        self._seen_poll = 0
        self._remove_listener: CALLBACK_TYPE | None = None
        # Door -> re-lock attempts failed in a row.
        self._failures: dict[int, int] = {}

    async def async_start(self) -> None:
        """Pick up visitor unlocks that were running before a restart, or
        left by a removed entry for the same controller."""
        saved = (await self._store.async_load() or {}).get("doors", {})
        unique_id = self.coordinator.config_entry.unique_id
        if unique_id:
            handover = _handover_store(self.hass, unique_id)
            if left := (await handover.async_load() or {}).get("doors"):
                saved = {**left, **saved}
                await self._store.async_save({"doors": saved})
                await handover.async_remove()
        for key, iso in saved.items():
            when = dt_util.parse_datetime(iso)
            door_id = int(key)
            if when is None or door_id not in self.coordinator.site.doors:
                continue
            self.until[door_id] = when
            self._schedule(door_id, when)
        for door_id, status in self.coordinator.data.doors.items():
            self._latched[door_id] = status.is_latched
        self._seen_poll = self.coordinator.data.doors_poll_id
        self._remove_listener = self.coordinator.async_add_listener(self._on_update)

    async def async_stop(self) -> None:
        """Stop the timers (on unload) and save now, so a reload or restart
        straight after an unlock still knows to lock the door."""
        if self._remove_listener:
            self._remove_listener()
            self._remove_listener = None
        for cancel in self._timers.values():
            cancel()
        self._timers.clear()
        await self._store.async_save(self._data())

    async def async_unlock(self, door_id: int, minutes: int) -> None:
        """Latch the door open now and lock it again after ``minutes``."""
        await self.coordinator.client.unlock_door(door_id, latched=True)
        when = dt_util.utcnow() + timedelta(minutes=minutes)
        self.until[door_id] = when
        # Readings already under way say "not latched": wait for a fresh one.
        self._after[door_id] = self.coordinator.polls_started
        self._latched[door_id] = None
        self._schedule(door_id, when)
        self._save()

    async def async_relock_all(self) -> None:
        """Lock every door still held for a visitor (on unload). A door that
        won't lock stays saved, so the next setup locks it."""
        for door_id in list(self.until):
            if cancel := self._timers.pop(door_id, None):
                cancel()
            try:
                await self._lock_if_latched(door_id)
            except Exception:  # noqa: BLE001 - kept for the next setup
                _LOGGER.warning(
                    "Couldn't lock door %s after a visitor unlock; it will be locked at the next setup",
                    door_id,
                )
                self.until[door_id] = dt_util.utcnow()  # due now, not at the original end
                continue
            self._locked(door_id)

    @callback
    def cancel(self, door_id: int) -> None:
        if cancel := self._timers.pop(door_id, None):
            cancel()
        self._clear_issue(door_id)
        if self.until.pop(door_id, None) is not None:
            self._save()
            self.coordinator.async_update_listeners()

    async def _lock_if_latched(self, door_id: int) -> None:
        # Read the door now rather than trust the last poll. Still latched (or
        # unknown): lock it. Already locked: leave it.
        status = (await self.coordinator.client.door_status()).get(door_id)
        if status is None or status.is_latched is not False:
            await self.coordinator.client.lock_door(door_id)

    def _locked(self, door_id: int) -> None:
        self.until.pop(door_id, None)
        self._clear_issue(door_id)
        self._save()

    def _issue_id(self, door_id: int) -> str:
        return f"{ISSUE_VISITOR_RELOCK}_{self.coordinator.config_entry.entry_id}_{door_id}"

    def _clear_issue(self, door_id: int) -> None:
        if self._failures.pop(door_id, 0) >= VISITOR_RELOCK_ATTEMPTS:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(door_id))

    def _relock_failed(self, door_id: int) -> None:
        self._failures[door_id] = self._failures.get(door_id, 0) + 1
        if self._failures[door_id] == VISITOR_RELOCK_ATTEMPTS:
            door = self.coordinator.site.doors.get(door_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id(door_id),
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=ISSUE_VISITOR_RELOCK,
                translation_placeholders={
                    "door": door.name if door else str(door_id),
                    "attempts": str(VISITOR_RELOCK_ATTEMPTS),
                },
            )

    def _schedule(self, door_id: int, when: datetime) -> None:
        if cancel := self._timers.pop(door_id, None):
            cancel()

        async def _relock(_now: datetime) -> None:
            self._timers.pop(door_id, None)
            try:
                await self._lock_if_latched(door_id)
            except Exception:  # noqa: BLE001 - try again shortly
                _LOGGER.warning("Couldn't lock door %s after a visitor unlock; retrying", door_id)
                self._relock_failed(door_id)
                self._schedule(door_id, dt_util.utcnow() + timedelta(seconds=30))
                return
            self._locked(door_id)
            await self.coordinator.async_refresh_all()

        self._timers[door_id] = async_track_point_in_utc_time(
            self.hass, _relock, max(when, dt_util.utcnow() + timedelta(seconds=1))
        )

    @callback
    def _on_update(self) -> None:
        data = self.coordinator.data
        if data.doors_poll_id <= self._seen_poll:
            return  # no new door reading (or an older one finishing late)
        self._seen_poll = data.doors_poll_id
        for door_id, status in data.doors.items():
            if door_id in self._after:
                if data.doors_poll_id <= self._after[door_id]:
                    continue  # read before the unlock took effect
                del self._after[door_id]
            latched = status.is_latched
            if door_id in self.until and self._latched.get(door_id) is True and latched is False:
                # Locked by someone else before the time was up.
                if cancel := self._timers.pop(door_id, None):
                    cancel()
                self._locked(door_id)
            if latched is not None:
                self._latched[door_id] = latched

    def _data(self) -> dict[str, Any]:
        return {"doors": {str(k): v.isoformat() for k, v in self.until.items()}}

    def _save(self) -> None:
        self._store.async_delay_save(self._data, 1)
