"""Binary sensors: inputs, tamper, door position, troubles, readiness and faults."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .const import DEFAULT_INPUT_TYPE, DOMAIN, OPT_INPUT_TYPES
from .coordinator import AreaInfo, DoorInfo, InputInfo, ProtegeCoordinator
from .entity import ProtegeEntity

PARALLEL_UPDATES = 0

SERVICE_BYPASS = "bypass"
BYPASS_MODES = ("none", "temporary", "permanent")

# Trouble inputs that report a one-off event rather than a fault to fix.
_INFORMATIONAL_TROUBLES = ("system restarted", "installer logged in", "service test report")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    coordinator = data.coordinator
    input_types: dict[str, str] = entry.options.get(OPT_INPUT_TYPES, {})

    entities: list[BinarySensorEntity] = []
    for info in data.site.inputs.values():
        device_class = input_types.get(str(info.id), DEFAULT_INPUT_TYPE)
        entities.append(ProtegeInputSensor(coordinator, info, device_class))
        entities.append(ProtegeInputTamperSensor(coordinator, info))
    for door in data.site.doors.values():
        if door.has_position_input:
            entities.append(ProtegeDoorPositionSensor(coordinator, door))
    for rec_id, name in data.site.trouble_inputs.items():
        entities.append(ProtegeTroubleSensor(coordinator, rec_id, name))
    for area in data.site.areas.values():
        entities.append(ProtegeReadySensor(coordinator, area, stay=False))
        if area.stay_enabled:
            entities.append(ProtegeReadySensor(coordinator, area, stay=True))
    entities.append(ProtegeFaultSensor(coordinator))
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_BYPASS,
        {vol.Required("mode"): vol.In(BYPASS_MODES), vol.Optional("code"): cv.string},
        "async_service_bypass",
    )


class _ProtegeBinarySensor(ProtegeEntity, BinarySensorEntity):
    async def async_service_bypass(self, mode: str, code: str | None = None) -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_an_input",
            translation_placeholders={"entity": self.entity_id},
        )


class _InputBase(_ProtegeBinarySensor):
    def __init__(self, coordinator: ProtegeCoordinator, info: InputInfo, key: str | None) -> None:
        super().__init__(coordinator, "input", info.id, key=key, own_device=True)
        self.info = info
        # Spare inputs (not in any area) start disabled.
        self._attr_entity_registry_enabled_default = info.in_use

    @property
    def _status(self):
        return self.coordinator.data.inputs.get(self.rec_id)

    @property
    def available(self) -> bool:
        status = self._status
        return super().available and status is not None and status.known


class ProtegeInputSensor(_InputBase):
    """An input (zone). On while open; tamper or short also reads as on, so a
    damaged sensor never looks quiet."""

    _attr_name = None

    def __init__(self, coordinator: ProtegeCoordinator, info: InputInfo, device_class: str) -> None:
        super().__init__(coordinator, info, None)
        self._attr_device_class = BinarySensorDeviceClass(device_class)

    @property
    def is_on(self) -> bool | None:
        status = self._status
        return None if status is None else status.is_open

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status
        if status is None:
            return {}
        return {"controller_state": status.state, "bypass": status.bypass}

    async def async_service_bypass(self, mode: str, code: str | None = None) -> None:
        await self.coordinator.async_authorise_bypass(self.rec_id, code)
        await self._command(self.coordinator.client.set_bypass(self.rec_id, mode))


class ProtegeInputTamperSensor(_InputBase):
    """Tamper or short-circuit on an input's wiring."""

    _attr_translation_key = "tamper"
    _attr_device_class = BinarySensorDeviceClass.TAMPER
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ProtegeCoordinator, info: InputInfo) -> None:
        super().__init__(coordinator, info, "tamper")

    @property
    def is_on(self) -> bool | None:
        status = self._status
        return None if status is None else status.is_tampered


class ProtegeDoorPositionSensor(_ProtegeBinarySensor):
    """Door open/closed, only for doors with a door-position input."""

    _attr_translation_key = "door_position"
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, coordinator: ProtegeCoordinator, door: DoorInfo) -> None:
        super().__init__(coordinator, "door", door.id, key="position", own_device=True)

    @property
    def _status(self):
        return self.coordinator.data.doors.get(self.rec_id)

    @property
    def available(self) -> bool:
        status = self._status
        return super().available and status is not None and status.is_open is not None

    @property
    def is_on(self) -> bool | None:
        status = self._status
        return None if status is None else status.is_open

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status
        return {} if status is None else {"controller_state": status.position}


class ProtegeTroubleSensor(_ProtegeBinarySensor):
    """A controller trouble input (mains failure, low battery, tamper...)."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ProtegeCoordinator, rec_id: int, name: str) -> None:
        super().__init__(coordinator, "trouble", rec_id)
        self._attr_name = name

    @property
    def _status(self):
        return self.coordinator.data.trouble_inputs.get(self.rec_id)

    @property
    def available(self) -> bool:
        status = self._status
        return super().available and status is not None and status.known

    @property
    def is_on(self) -> bool | None:
        status = self._status
        return None if status is None else status.is_open


class ProtegeReadySensor(_ProtegeBinarySensor):
    """On when the area could be armed now (no unbypassed zone open)."""

    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo, *, stay: bool) -> None:
        super().__init__(
            coordinator, "area", area.id, key="ready_stay" if stay else "ready", own_device=True
        )
        self._stay = stay
        self._attr_translation_key = "ready_to_arm_stay" if stay else "ready_to_arm"
        self._attr_entity_registry_enabled_default = area.has_inputs is not False

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.zones_known(self.rec_id, stay=self._stay):
            return None  # an unknown zone can't be called ready
        return not self.coordinator.open_zones(self.rec_id, stay=self._stay)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"open_zones": self.coordinator.open_zones(self.rec_id, stay=self._stay)}


class ProtegeFaultSensor(_ProtegeBinarySensor):
    """One sensor for "something needs attention": any active trouble input
    (ignoring one-off notices like "System Restarted") or controller trouble."""

    _attr_translation_key = "alarm_fault"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: ProtegeCoordinator) -> None:
        super().__init__(coordinator, "controller", 0, key="fault")

    def _active(self) -> list[str]:
        data = self.coordinator.data
        active = [
            name
            for rec_id, name in self.coordinator.site.trouble_inputs.items()
            if (status := data.trouble_inputs.get(rec_id)) is not None
            and status.is_open
            and not name.lower().startswith(_INFORMATIONAL_TROUBLES)
        ]
        return active + list(data.health_troubles)

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if not data.trouble_inputs:
            return None
        if self._active():
            return True
        if any(not status.known for status in data.trouble_inputs.values()):
            return None  # can't say "no fault" while a trouble input is unknown
        return False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"active": self._active()}
