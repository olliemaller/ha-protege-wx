"""Repairs fix flows: acknowledging an emergency alert."""
from __future__ import annotations

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Emergency alerts are cleared by confirming you've seen them."""
    return ConfirmRepairFlow()
