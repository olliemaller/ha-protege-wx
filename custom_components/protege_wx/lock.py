"""Doors as locks."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aioprotegewx import DoorStatus
from homeassistant.components.lock import LockEntity
from homeassistant.const import ATTR_CODE
from homeassistant.core import HomeAssistant

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .const import DEFAULT_VISITOR_MINUTES, OPT_VISITOR_MINUTES
from .coordinator import DoorInfo, ProtegeCoordinator
from .entity import ProtegeEntity

if TYPE_CHECKING:
    from .visitor import VisitorUnlocks


PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    async_add_entities(
        ProtegeDoorLock(entry, data.coordinator, door) for door in data.site.doors.values()
    )


class ProtegeDoorLock(ProtegeEntity, LockEntity):
    """A Protege door.

    Unlocking uses the controller's normal unlock, which releases the door for
    its programmed unlock time and then re-locks it. Holding it open (latched)
    is the door's "Hold open" switch or the protege_wx.unlock_door action.
    """

    _attr_name = None

    def __init__(self, entry: ProtegeConfigEntry, coordinator: ProtegeCoordinator, door: DoorInfo) -> None:
        super().__init__(coordinator, "door", door.id, own_device=True)
        self._entry = entry
        if coordinator.unlock_needs_code:
            # Empty is allowed so locking still needs no PIN; unlocking checks it.
            self._attr_code_format = r"^\d*$"

    @property
    def _visitors(self) -> VisitorUnlocks:
        visitors = self._entry.runtime_data.visitors
        assert visitors is not None
        return visitors

    @property
    def _status(self) -> DoorStatus | None:
        return self.coordinator.data.doors.get(self.rec_id)

    @property
    def available(self) -> bool:
        status = self._status
        return super().available and status is not None and status.is_locked is not None

    @property
    def is_locked(self) -> bool | None:
        status = self._status
        return None if status is None else status.is_locked

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status
        if status is None:
            return {}
        until = self._visitors.until.get(self.rec_id) if self._visitors else None
        return {
            "controller_state": status.lock,
            "held_open": bool(status.is_latched),
            "visitor_until": until.isoformat() if until else None,
        }

    async def async_lock(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.lock_door(self.rec_id))
        # Only once it has locked: a failed lock must leave the relock pending.
        if self._visitors:
            self._visitors.cancel(self.rec_id)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.async_authorise_unlock(kwargs.get(ATTR_CODE))
        await self._command(self.coordinator.client.unlock_door(self.rec_id))

    async def async_service_unlock(self, hold_open: bool = False, code: str | None = None) -> None:
        await self.coordinator.async_authorise_unlock(code)
        await self._command(self.coordinator.client.unlock_door(self.rec_id, latched=hold_open))
        if hold_open and self._visitors:
            self._visitors.cancel(self.rec_id)  # held open on purpose: no relock

    async def async_visitor_unlock(self, minutes: int | None = None, code: str | None = None) -> None:
        """Hold the door unlocked for a while, then lock it again."""
        await self.coordinator.async_authorise_unlock(code)
        if minutes is None:
            minutes = int(self._entry.options.get(OPT_VISITOR_MINUTES, DEFAULT_VISITOR_MINUTES))
        await self._command(self._visitors.async_unlock(self.rec_id, minutes))
