"""Compatibility with older Home Assistant releases."""
from __future__ import annotations

import inspect
from collections.abc import Iterable

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import service
from homeassistant.helpers.entity import Entity

try:  # Home Assistant 2025.3 and later
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # pragma: no cover - older releases
    from homeassistant.helpers.entity_platform import (  # type: ignore[assignment]
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )

try:  # Home Assistant 2026.10 moved its schemas to probatio.
    import probatio as vol
except ImportError:  # pragma: no cover - older Home Assistant
    import voluptuous as vol  # type: ignore[no-redef]


async def async_extract_entities(
    hass: HomeAssistant, entities: Iterable[Entity], call: ServiceCall
) -> list[Entity]:
    """The entities an action call targets. Newer Home Assistant releases dropped the
    hass argument from service.async_extract_entities."""
    if "hass" in inspect.signature(service.async_extract_entities).parameters:  # pragma: no cover - older Home Assistant
        found: list[Entity] = await service.async_extract_entities(hass, entities, call)  # type: ignore[arg-type]
        return found
    return await service.async_extract_entities(entities, call)


__all__ = ["AddConfigEntryEntitiesCallback", "async_extract_entities", "vol"]
