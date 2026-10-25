"""Buttons per area: force arm (away / night) and silence the siren."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant

from . import ProtegeConfigEntry
from .compat import AddConfigEntryEntitiesCallback
from .const import OPT_NIGHT_MODE
from .coordinator import AreaInfo, ProtegeCoordinator
from .entity import ProtegeEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ProtegeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    data = entry.runtime_data
    night_modes: dict[str, str] = entry.options.get(OPT_NIGHT_MODE, {})
    entities: list[ButtonEntity] = []
    for area in data.site.areas.values():
        entities.append(ProtegeForceArmButton(entry, data.coordinator, area, "away"))
        # "Force arm night" forces an instant arm; the controller can't force stay.
        if area.instant_enabled and night_modes.get(str(area.id), "instant") == "instant":
            entities.append(ProtegeForceArmButton(entry, data.coordinator, area, "instant"))
        entities.append(ProtegeSilenceButton(entry, data.coordinator, area))
    async_add_entities(entities)


class _AreaButton(ProtegeEntity, ButtonEntity):
    def __init__(
        self, entry: ProtegeConfigEntry, coordinator: ProtegeCoordinator, area: AreaInfo, key: str
    ) -> None:
        super().__init__(coordinator, "area", area.id, key=key, own_device=True)
        self._entry = entry
        self._attr_entity_registry_enabled_default = area.has_inputs is not False

    @property
    def _area_entity(self):
        return self._entry.runtime_data.areas[self.rec_id]


class ProtegeForceArmButton(_AreaButton):
    """Arm even with zones open; the controller bypasses them until disarmed."""

    def __init__(
        self, entry: ProtegeConfigEntry, coordinator: ProtegeCoordinator, area: AreaInfo, mode: str
    ) -> None:
        super().__init__(entry, coordinator, area, f"force_arm_{mode}")
        self._mode = mode
        self._attr_translation_key = f"force_arm_{mode}"

    async def async_press(self) -> None:
        await self._area_entity.async_force_arm(self._mode)


class ProtegeSilenceButton(_AreaButton):
    """Silence a sounding siren without disarming."""

    _attr_translation_key = "silence"

    def __init__(self, entry: ProtegeConfigEntry, coordinator: ProtegeCoordinator, area: AreaInfo) -> None:
        super().__init__(entry, coordinator, area, "silence")

    async def async_press(self) -> None:
        await self._area_entity.async_silence()
