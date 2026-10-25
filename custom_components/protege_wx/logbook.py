"""Logbook descriptions for ICT Protege WX events."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.logbook import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_LOGBOOK


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Describe the integration's logbook-only events."""

    @callback
    def describe(event: Event) -> dict[str, Any]:
        data = event.data
        entry = {
            LOGBOOK_ENTRY_NAME: data.get("name", "Protege WX"),
            LOGBOOK_ENTRY_MESSAGE: data.get("message", ""),
        }
        if data.get("entity_id"):
            entry[LOGBOOK_ENTRY_ENTITY_ID] = data["entity_id"]
        return entry

    async_describe_event(DOMAIN, EVENT_LOGBOOK, describe)
