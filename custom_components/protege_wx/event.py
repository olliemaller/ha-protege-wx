"""Event entities from the controller's event log, for automation triggers.

* one per area: armed, arming started/cancelled, failed to arm, disarmed, alarm
* one per door: access granted/denied (with user and method), unlocked,
  locked, opened, closed, forced open, left open
* one for the controller: trouble raised/restored, power up
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .coordinator import AreaInfo, DoorInfo, ProtegeCoordinator
from .entity import ProtegeEntity
from .wxapi.events import (
    AREA_EVENT_TYPES,
    CONTROLLER_EVENT_TYPES,
    DOOR_EVENT_TYPES,
    KIND_ACCESS,
    KIND_AREA,
    KIND_DOOR,
    KIND_SYSTEM,
    KIND_TROUBLE,
    ParsedEvent,
)

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    coordinator = data.coordinator
    entities: list[EventEntity] = [
        ProtegeAreaEvents(coordinator, area) for area in data.site.areas.values()
    ]
    entities += [ProtegeDoorEvents(coordinator, door) for door in data.site.doors.values()]
    entities.append(ProtegeControllerEvents(coordinator))
    async_add_entities(entities)


def _attributes(parsed: ParsedEvent) -> dict[str, Any]:
    event = parsed.event
    return {
        key: value
        for key, value in {
            "by": parsed.by,
            "user": parsed.user,
            "method": parsed.method,
            "mode": parsed.mode,
            "subject": parsed.subject,
            "text": event.text,
            "time": event.time.isoformat() if event.time else None,
        }.items()
        if value is not None
    }


class _ProtegeEvents(ProtegeEntity, EventEntity):
    def _matches(self, parsed: ParsedEvent) -> bool:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_event_listener(self._on_event))

    @callback
    def _on_event(self, parsed: ParsedEvent) -> None:
        if not self._matches(parsed):
            return
        event_type = parsed.event_type if parsed.event_type in self.event_types else "other"
        self._trigger_event(event_type, _attributes(parsed))
        self.async_write_ha_state()


class ProtegeAreaEvents(_ProtegeEvents):
    _attr_translation_key = "area_events"
    _attr_event_types = list(AREA_EVENT_TYPES)

    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo) -> None:
        super().__init__(coordinator, "area", area.id, key="events", own_device=True)
        self._name = area.name
        self._attr_entity_registry_enabled_default = area.has_inputs is not False

    def _matches(self, parsed: ParsedEvent) -> bool:
        return parsed.kind == KIND_AREA and parsed.subject == self._name


class ProtegeDoorEvents(_ProtegeEvents):
    _attr_translation_key = "door_events"
    _attr_event_types = list(DOOR_EVENT_TYPES)

    def __init__(self, coordinator: ProtegeCoordinator, door: DoorInfo) -> None:
        super().__init__(coordinator, "door", door.id, key="events", own_device=True)
        self._name = door.name

    def _matches(self, parsed: ParsedEvent) -> bool:
        return parsed.kind in (KIND_DOOR, KIND_ACCESS) and parsed.subject == self._name


class ProtegeControllerEvents(_ProtegeEvents):
    _attr_translation_key = "controller_events"
    _attr_event_types = list(CONTROLLER_EVENT_TYPES)

    def __init__(self, coordinator: ProtegeCoordinator) -> None:
        super().__init__(coordinator, "controller", 0, key="events")

    def _matches(self, parsed: ParsedEvent) -> bool:
        return parsed.kind in (KIND_TROUBLE, KIND_SYSTEM)
