"""Input bypass as a select (not bypassed / until disarmed / permanent)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .coordinator import InputInfo, ProtegeCoordinator
from .entity import ProtegeEntity

PARALLEL_UPDATES = 1

BYPASS_OPTIONS = ["none", "temporary", "permanent"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    async_add_entities(
        ProtegeBypassSelect(data.coordinator, info) for info in data.site.inputs.values()
    )


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
