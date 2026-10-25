"""Sensors: supply voltage, memory, last event, connection, open zones, alarm
cause, delay countdown, zone last-triggered and person last-seen."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfElectricPotential
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .const import DOMAIN
from .coordinator import AreaInfo, InputInfo, ProtegeCoordinator
from .entity import ProtegeEntity
from .wxapi.events import KIND_ACCESS, ParsedEvent

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
    site = entry.runtime_data.site
    for area in site.areas.values():
        entities.append(ProtegeOpenZones(coordinator, area))
        entities.append(ProtegeAlarmCause(coordinator, area))
        entities.append(ProtegeDelayEnds(coordinator, area))
    entities += [ProtegeLastTriggered(coordinator, info) for info in site.inputs.values()]
    async_add_entities(entities)
    await _setup_people(hass, entry, coordinator, async_add_entities)


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


class _AreaSensor(ProtegeEntity, SensorEntity):
    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo, key: str) -> None:
        super().__init__(coordinator, "area", area.id, key=key, own_device=True)
        self._attr_entity_registry_enabled_default = area.has_inputs is not False


class ProtegeAlarmCause(_AreaSensor):
    """The zone that set the alarm off. Kept until the area is disarmed."""

    _attr_translation_key = "alarm_cause"

    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo) -> None:
        super().__init__(coordinator, area, "alarm_cause")

    @property
    def native_value(self) -> str:
        return self.coordinator.alarm_cause.get(self.rec_id) or "none"


class ProtegeDelayEnds(_AreaSensor):
    """When the current exit or entry delay ends (shown as a countdown)."""

    _attr_translation_key = "delay_ends"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo) -> None:
        super().__init__(coordinator, area, "delay_ends")

    @property
    def native_value(self) -> datetime | None:
        delay = self.coordinator.delay_ends.get(self.rec_id)
        return delay[1] if delay else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        delay = self.coordinator.delay_ends.get(self.rec_id)
        return {
            "phase": delay[0] if delay else None,
            "exit_delay": self.coordinator.area_delay(self.rec_id, "exit"),
            "entry_delay": self.coordinator.area_delay(self.rec_id, "entry"),
        }


class ProtegeLastTriggered(ProtegeEntity, RestoreSensor):
    """When a zone last opened (motion seen, a door opened...)."""

    _attr_translation_key = "last_triggered"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: ProtegeCoordinator, info: InputInfo) -> None:
        super().__init__(coordinator, "input", info.id, key="last_triggered", own_device=True)
        self._attr_entity_registry_enabled_default = info.in_use

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.rec_id in self.coordinator.last_triggered:
            return
        last = await self.async_get_last_sensor_data()
        value = last.native_value if last is not None else None
        if isinstance(value, str):
            value = dt_util.parse_datetime(value)
        if isinstance(value, datetime):
            self.coordinator.last_triggered[self.rec_id] = value

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.last_triggered.get(self.rec_id)


# ── people ────────────────────────────────────────────────────────────────

_PEOPLE_STORE_VERSION = 1


async def _setup_people(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    coordinator: ProtegeCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """One "last seen" sensor per person who badges in at a door, created on
    first sight and remembered (when and where) across restarts."""
    # Kept in memory across reloads too, since a delayed save may not have
    # been written yet when the entry reloads.
    cache: dict = hass.data.setdefault(DOMAIN, {})
    key = ("people", entry.entry_id)
    if key not in cache:
        store: Store[dict[str, Any]] = Store(
            hass, _PEOPLE_STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.people"
        )
        cache[key] = (store, (await store.async_load() or {}).get("people", {}))
    store, people = cache[key]
    sensors: dict[str, ProtegePersonLastSeen] = {}

    def add(name: str) -> None:
        sensors[name] = ProtegePersonLastSeen(coordinator, name, people)
        async_add_entities([sensors[name]])

    for name in people:
        add(name)

    @callback
    def on_event(parsed: ParsedEvent) -> None:
        if parsed.kind != KIND_ACCESS or parsed.event_type != "access_granted" or not parsed.user:
            return
        name = parsed.user
        people[name] = {
            "time": dt_util.utcnow().isoformat(),
            "door": parsed.subject,
            "method": parsed.method,
        }
        store.async_delay_save(lambda: {"people": people}, 5)
        if name in sensors:
            if sensors[name].hass is not None:
                sensors[name].async_write_ha_state()
        else:
            add(name)

    entry.async_on_unload(coordinator.async_add_event_listener(on_event))


def person_slug(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_") or "unknown"


class ProtegePersonLastSeen(ProtegeEntity, SensorEntity):
    """When and where a person last badged in (card or PIN at a door)."""

    _attr_translation_key = "last_seen"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(
        self, coordinator: ProtegeCoordinator, name: str, people: dict[str, dict[str, Any]]
    ) -> None:
        super().__init__(coordinator, "person", 0, key=person_slug(name))
        self._person = name
        self._people = people
        self._attr_translation_placeholders = {"person": name}

    @property
    def available(self) -> bool:
        return True  # history, not live status

    @property
    def native_value(self) -> datetime | None:
        record = self._people.get(self._person, {})
        return dt_util.parse_datetime(record["time"]) if record.get("time") else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        record = self._people.get(self._person, {})
        return {"person": self._person, "door": record.get("door"), "method": record.get("method")}
