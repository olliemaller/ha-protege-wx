"""Input bypass as a select (not bypassed / until disarmed / permanent)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from . import ProtegeConfigEntry
from .arm_when_ready import night_mode_for
from .compat import AddConfigEntryEntitiesCallback
from .const import OPT_NIGHT_MODE
from .coordinator import AreaInfo, InputInfo, ProtegeCoordinator
from .entity import ProtegeEntity

PARALLEL_UPDATES = 1

BYPASS_OPTIONS = ["none", "temporary", "permanent"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    night_modes: dict[str, str] = entry.options.get(OPT_NIGHT_MODE, {})
    entities: list[SelectEntity] = [
        ProtegeBypassSelect(data.coordinator, info) for info in data.site.inputs.values()
    ]
    entities += [
        ProtegeArmWhenReadyModeSelect(
            data.coordinator,
            area,
            night_mode_for(area, night_modes.get(str(area.id), "instant")),
        )
        for area in data.site.areas.values()
        if area.has_inputs is not False
    ]
    async_add_entities(entities)


class ProtegeBypassSelect(ProtegeEntity, SelectEntity):
    """Bypass state of an input."""

    _attr_translation_key = "bypass"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = BYPASS_OPTIONS

    def __init__(self, coordinator: ProtegeCoordinator, info: InputInfo) -> None:
        super().__init__(coordinator, "input", info.id, key="bypass", own_device=True)
        self._attr_entity_registry_enabled_default = info.in_use

    @property
    def _status(self):
        return self.coordinator.data.inputs.get(self.rec_id)

    @property
    def available(self) -> bool:
        return super().available and self._status is not None

    @property
    def current_option(self) -> str | None:
        status = self._status
        return None if status is None else status.bypass

    async def async_select_option(self, option: str) -> None:
        # No PIN can be entered here: with PINs set up, only while disarmed.
        await self.coordinator.async_authorise_bypass(self.rec_id, None)
        await self._command(self.coordinator.client.set_bypass(self.rec_id, option))


class ProtegeArmWhenReadyModeSelect(ProtegeEntity, SelectEntity, RestoreEntity):
    """The mode the area's "Arm when ready" switch arms in."""

    _attr_translation_key = "arm_when_ready_mode"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: ProtegeCoordinator, area: AreaInfo, night_mode: str) -> None:
        super().__init__(coordinator, "area", area.id, key="arm_when_ready_mode", own_device=True)
        options = ["away"]
        if area.stay_enabled:
            options.append("home")
        if night_mode != "off":
            options.append("night")
        self._attr_options = options
        self._attr_current_option = "away"

    @property
    def _waits(self):
        return self.coordinator.config_entry.runtime_data.arm_when_ready

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self.options:
            self._attr_current_option = last.state
        self._waits.preferred[self.rec_id] = self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        self._attr_current_option = option
        self._waits.preferred[self.rec_id] = option
        self.async_write_ha_state()
