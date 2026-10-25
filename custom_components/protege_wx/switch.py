"""Switches: "Hold open" per door, walk test per area, and outputs (PGMs)
chosen in the options."""
from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_platform

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .const import DOMAIN, OPT_OUTPUTS
from .coordinator import AreaInfo, DoorInfo, ProtegeCoordinator
from .entity import ProtegeEntity
from .wxapi.client import MAX_TIMED_SECONDS
from .wxapi.events import KIND_AREA, ParsedEvent

PARALLEL_UPDATES = 1

SERVICE_PULSE_OUTPUT = "pulse_output"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    chosen = {int(rec_id) for rec_id in entry.options.get(OPT_OUTPUTS, [])}
    entities: list[SwitchEntity] = [
        ProtegeHoldOpenSwitch(data.coordinator, door) for door in data.site.doors.values()
    ]
    entities += [
        ProtegeWalkTestSwitch(data.coordinator, area)
        for area in data.site.areas.values()
        if area.has_inputs is not False
    ]
    entities += [
        ProtegeOutputSwitch(data.coordinator, rec_id, name)
        for rec_id, name in data.site.outputs.items()
        if rec_id in chosen
    ]
    async_add_entities(entities)
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_PULSE_OUTPUT,
        {vol.Required("seconds"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_TIMED_SECONDS))},
        "async_service_pulse",
    )


class ProtegeHoldOpenSwitch(ProtegeEntity, SwitchEntity):
    """Latch a door unlocked until switched off (which locks it).

    A config entity, so voice assistants and the HomeKit Bridge leave it out by
    default: "turn on all switches" must never hold every door open.
    """

    _attr_translation_key = "hold_open"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ProtegeCoordinator, door: DoorInfo) -> None:
        super().__init__(coordinator, "door", door.id, key="hold_open", own_device=True)

    @property
    def _status(self):
        return self.coordinator.data.doors.get(self.rec_id)

    @property
    def available(self) -> bool:
        status = self._status
        return super().available and status is not None and status.is_latched is not None

    @property
    def is_on(self) -> bool | None:
        status = self._status
        return None if status is None else status.is_latched

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.unlock_door(self.rec_id, latched=True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Only undo our own latch; don't lock a door a schedule has unlocked.
        if self.is_on:
            await self._command(self.coordinator.client.lock_door(self.rec_id))

    async def async_service_pulse(self, seconds: int) -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_an_output",
            translation_placeholders={"entity": self.entity_id},
        )


class ProtegeOutputSwitch(ProtegeEntity, SwitchEntity):
    """A Protege output."""

    def __init__(self, coordinator: ProtegeCoordinator, rec_id: int, name: str) -> None:
        super().__init__(coordinator, "output", rec_id)
        self._attr_name = name

    @property
    def _status(self):
        return self.coordinator.data.outputs.get(self.rec_id)

    @property
    def available(self) -> bool:
        status = self._status
        return super().available and status is not None and status.is_on is not None

    @property
    def is_on(self) -> bool | None:
        status = self._status
        return None if status is None else status.is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self._status
        return {} if status is None else {"controller_state": status.state}

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.set_output(self.rec_id, True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.set_output(self.rec_id, False))

    async def async_service_pulse(self, seconds: int) -> None:
        """Turn the output on for ``seconds``; the controller turns it off."""
        await self._command(self.coordinator.client.set_output(self.rec_id, True, seconds))


class ProtegeWalkTestSwitch(ProtegeEntity, SwitchEntity):
    """Walk test: zones chime as they're tested instead of setting off the alarm.

    The controller doesn't report walk-test status, so this follows what Home
    Assistant asked for and any walk-test lines in the event log, and turns
    itself off when the area arms.
    """

    _attr_translation_key = "walk_test"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_assumed_state = True

    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo) -> None:
        super().__init__(coordinator, "area", area.id, key="walk_test", own_device=True)
        self._area_name = area.name
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.coordinator.async_add_event_listener(self._on_event))

    @callback
    def _on_event(self, parsed: ParsedEvent) -> None:
        text = parsed.event.text.lower()
        if parsed.kind != KIND_AREA or parsed.subject != self._area_name or "walk test" not in text:
            return
        on = not any(word in text for word in ("end", "stop", "finish", "cancel", "off"))
        if on != self._attr_is_on:
            self._attr_is_on = on
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        status = self.coordinator.data.areas.get(self.rec_id)
        if self._attr_is_on and status is not None and status.is_armed_or_arming:
            self._attr_is_on = False  # arming ends a walk test
        super()._handle_coordinator_update()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.walk_test(self.rec_id, True))
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._command(self.coordinator.client.walk_test(self.rec_id, False))
        self._attr_is_on = False
        self.async_write_ha_state()

    async def async_service_pulse(self, seconds: int) -> None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_an_output",
            translation_placeholders={"entity": self.entity_id},
        )
