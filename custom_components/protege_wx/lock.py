"""Doors as locks."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .coordinator import DoorInfo, ProtegeCoordinator
from .entity import ProtegeEntity

PARALLEL_UPDATES = 1

SERVICE_UNLOCK_DOOR = "unlock_door"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    async_add_entities(ProtegeDoorLock(data.coordinator, door) for door in data.site.doors.values())
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_UNLOCK_DOOR,
        {vol.Optional("hold_open", default=False): cv.boolean},
        "async_service_unlock",
    )


class ProtegeDoorLock(ProtegeEntity, LockEntity):
    """A Protege door.

    Unlocking uses the controller's normal unlock, which releases the door for
    its programmed unlock time and then re-locks it. Holding it open (latched)
    is the door's "Hold open" switch or the protege_wx.unlock_door action.
    """

    _attr_name = None

    def __init__(self, coordinator: ProtegeCoordinator, door: DoorInfo) -> None:
        super().__init__(coordinator, "door", door.id, own_device=True)

    @property
    def _status(self):
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
        return {"controller_state": status.lock, "held_open": bool(status.is_latched)}

    async def async_lock(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.lock_door(self.rec_id))

    async def async_unlock(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.unlock_door(self.rec_id))

    async def async_service_unlock(self, hold_open: bool = False) -> None:
        await self._command(self.coordinator.client.unlock_door(self.rec_id, latched=hold_open))
