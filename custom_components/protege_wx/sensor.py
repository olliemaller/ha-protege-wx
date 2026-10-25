"""Sensors: supply voltage, memory use and the last event-log line."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import ProtegeConfigEntry
from .coordinator import ProtegeCoordinator
from .entity import ProtegeEntity
from .wxapi.events import ParsedEvent

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            ProtegeSupplyVoltage(coordinator),
            ProtegeMemoryUsed(coordinator),
            ProtegeLastEvent(coordinator),
        ]
    )


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
