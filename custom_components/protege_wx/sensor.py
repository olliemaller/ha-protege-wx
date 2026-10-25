"""Sensors: supply voltage, memory, last event, connection and open zones."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant, callback

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .coordinator import AreaInfo, ProtegeCoordinator
from .entity import ProtegeEntity
from .wxapi.events import ParsedEvent

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    entities: list[SensorEntity] = [
        ProtegeSupplyVoltage(coordinator),
        ProtegeMemoryUsed(coordinator),
        ProtegeLastEvent(coordinator),
        ProtegeConnection(coordinator),
    ]
    entities += [
        ProtegeOpenZones(coordinator, area) for area in entry.runtime_data.site.areas.values()
    ]
    async_add_entities(entities)


def _number(value: str | None) -> float | None:
    try:
        return float((value or "").strip())
    except ValueError:
        return None


class ProtegeSupplyVoltage(ProtegeEntity, SensorEntity):
    """Controller supply voltage (reported in millivolts)."""

    _attr_translation_key = "supply_voltage"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: ProtegeCoordinator) -> None:
        super().__init__(coordinator, "controller", 0, key="supply_voltage")

    @property
    def native_value(self) -> float | None:
        millivolts = _number(self.coordinator.data.health.get("NetworkVoltage"))
        return None if millivolts is None else round(millivolts / 1000, 3)


class ProtegeMemoryUsed(ProtegeEntity, SensorEntity):
    """Controller memory in use."""

    _attr_translation_key = "memory_used"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: ProtegeCoordinator) -> None:
        super().__init__(coordinator, "controller", 0, key="memory_used")

    @property
    def native_value(self) -> float | None:
        used = _number(self.coordinator.data.health.get("MemUsed"))
        total = _number(self.coordinator.data.health.get("MemTotal"))
        if used is None or not total:
            return None
        return round(used / total * 100, 1)


class ProtegeLastEvent(ProtegeEntity, SensorEntity):
    """The most recent meaningful line from the controller's event log."""

    _attr_translation_key = "last_event"

    def __init__(self, coordinator: ProtegeCoordinator) -> None:
        super().__init__(coordinator, "controller", 0, key="last_event")
        self._last: ParsedEvent | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.coordinator.history:
            self._last = self.coordinator.history[-1]
        self.async_on_remove(self.coordinator.async_add_event_listener(self._on_event))

    @callback
    def _on_event(self, parsed: ParsedEvent) -> None:
        self._last = parsed
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return None if self._last is None else self._last.event.text[:255]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self._last is None:
            return {}
        event = self._last.event
        return {
            "time": event.time.isoformat() if event.time else None,
            "kind": self._last.kind,
            "subject": self._last.subject,
            "type": self._last.event_type,
            "by": self._last.by,
        }


CONNECTION_STATES = ["connected", "reconnecting", "backing_off", "login_failed"]


class ProtegeConnection(ProtegeEntity, SensorEntity):
    """How the link to the controller is doing. Stays available when it isn't."""

    _attr_translation_key = "connection"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CONNECTION_STATES
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # These change on every poll: keep them out of the recorder.
    _unrecorded_attributes = frozenset({"last_success", "response_time_ms"})

    def __init__(self, coordinator: ProtegeCoordinator) -> None:
        super().__init__(coordinator, "controller", 0, key="connection")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_status_listener(self._on_status))

    @callback
    def _on_status(self) -> None:
        # The coordinator only tells entities about the first of a run of
        # failures; this keeps "backing off" and "login failed" current.
        current = self.hass.states.get(self.entity_id) if self.entity_id else None
        if current is None or current.state != self.native_value:
            self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return self.coordinator.connection_state


    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coordinator = self.coordinator
        times = coordinator.response_times
        return {
            "last_success": coordinator.last_success.isoformat() if coordinator.last_success else None,
            "protocol": coordinator.client.protocol,
            "response_time_ms": round(sum(times) / len(times) * 1000) if times else None,
            "logins_last_10_min": coordinator.logins_last_window(),
        }


class ProtegeOpenZones(ProtegeEntity, SensorEntity):
    """How many zones in an area are open (and not bypassed) right now."""

    _attr_translation_key = "open_zones"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo) -> None:
        super().__init__(coordinator, "area", area.id, key="open_zones", own_device=True)
        self._attr_entity_registry_enabled_default = area.has_inputs is not False

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.zones_known(self.rec_id):
            return None
        return len(self.coordinator.open_zones(self.rec_id))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coordinator = self.coordinator
        if not coordinator.zones_known(self.rec_id):
            return {}
        away = coordinator.open_zones(self.rec_id)
        home = coordinator.open_zones(self.rec_id, stay=True)
        return {
            "zones": away,
            "zones_home": home,
            "ready_away": not away,
            "ready_home": not home,
        }
